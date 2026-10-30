"""Configuration/logging regression. No production DB or provider connections."""
import ast
import contextlib
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import logging
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy import column, or_
import settings
from services import africastalking_client
from utils import sms

ROOT = Path(__file__).resolve().parents[1]
TEST_KEY = 'isolated-security-test-key-never-production'


def auth_code():
    namespace = dict(logger=logging.getLogger('tests.safe_auth'), Depends=Depends,
        HTTPException=HTTPException,status=status,Session=object,User=type('User',(),{'id':column('id'),'phone':column('phone')}),
        get_db=lambda:None,oauth2_scheme=OAuth2PasswordBearer(tokenUrl='login'),OAuth2PasswordRequestForm=OAuth2PasswordRequestForm,jwt=jwt,JWTError=JWTError,
        SECRET_KEY=TEST_KEY,ALGORITHM='HS256',ACCESS_TOKEN_EXPIRE_MINUTES=30,
        datetime=datetime,timedelta=timedelta,or_=or_,pwd_context=CryptContext(schemes=['bcrypt']))
    tree=ast.parse((ROOT/'routers/auth.py').read_text())
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef)]
    for function in functions: function.decorator_list=[]
    exec(compile(ast.Module(body=functions,type_ignores=[]),'actual-auth-functions','exec'),namespace)
    return namespace


class ConfigurationTests(unittest.TestCase):
    def test_hosted_or_production_environment_never_loads_development_env(self):
        for environment in [{'APP_ENV':'production'},{'RENDER':'true'},{'RAILWAY_ENVIRONMENT_ID':'synthetic-host-environment'}]:
            with patch.dict(os.environ,environment,clear=True),patch.object(settings,'load_dotenv') as load:
                settings.load_environment();load.assert_not_called()
        with patch.dict(os.environ,{'APP_ENV':'development'},clear=True),patch.object(settings,'load_dotenv') as load:
            settings.load_environment();load.assert_called_once_with(override=False)
        with patch.dict(os.environ,{'APP_ENV':'typo'},clear=True),self.assertRaises(settings.ConfigurationError):settings.load_environment()

    def test_missing_database_fails_closed(self):
        for environment in [{},{'DATABASE_URL':''},{'DATABASE_URL':'   '}]:
            with patch.dict(os.environ,environment,clear=True), self.assertRaises(settings.ConfigurationError) as error:
                settings.database_url()
            self.assertIn('DATABASE_URL',str(error.exception))

    def test_url_schemes_preserve_exact_target_and_credentials(self):
        for scheme in ['postgres','postgresql','postgresql+psycopg']:
            with patch.dict(os.environ,{'DATABASE_URL':f'{scheme}://test_user:test_password@127.0.0.1:55485/safety_test?sslmode=disable'},clear=True):
                url=settings.database_url()
            self.assertTrue(url.drivername=='postgresql+psycopg' and url.host=='127.0.0.1' and url.port==55485 and url.database=='safety_test')
            self.assertTrue(url.username=='test_user' and url.password=='test_password')
            self.assertTrue(url.query['sslmode']=='disable')

    def test_invalid_url_errors_never_include_input(self):
        for value in ['not-a-url-containing-test-password','sqlite:///:memory:','postgresql://test:test-password@localhost:bad/db']:
            with patch.dict(os.environ,{'DATABASE_URL':value},clear=True), self.assertRaises(settings.ConfigurationError) as error:
                settings.database_url()
            self.assertTrue(value not in str(error.exception))
            self.assertNotIn('test-password',str(error.exception))

    def test_database_engine_has_no_sql_or_parameter_echo_and_does_not_connect(self):
        with patch.dict(os.environ,{'DATABASE_URL':'postgresql://test_user:test_password@127.0.0.1:1/safety_test'}):
            spec=importlib.util.spec_from_file_location('isolated_database_config',ROOT/'database.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertFalse(module.engine.echo);self.assertTrue(module.engine.hide_parameters)
        self.assertEqual(module.engine.pool.checkedout(),0);module.engine.dispose()

    def test_jwt_does_not_select_formerly_unused_alias_or_default(self):
        for environment in [{},{'SECRET_KEY':TEST_KEY},{'JWT_SECRET_KEY':''},{'JWT_SECRET_KEY':'default_if_missing'}]:
            with patch.dict(os.environ,environment,clear=True),self.assertRaises(settings.ConfigurationError):settings.jwt_secret()

    def test_existing_canonical_jwt_key_bytes_take_precedence_unchanged(self):
        key=' '+TEST_KEY+' '
        with patch.dict(os.environ,{'JWT_SECRET_KEY':key,'SECRET_KEY':'unused-legacy-setting'},clear=True):
            self.assertTrue(settings.jwt_secret()==key)

    def test_render_and_procfile_have_no_embedded_credentials(self):
        import yaml
        config=yaml.safe_load((ROOT/'render.yaml').read_text())['services'][0]
        fields={entry['key']:entry for entry in config['envVars']}
        for name in ['DATABASE_URL','JWT_SECRET_KEY','AFRICASTALKING_USERNAME','AFRICASTALKING_API_KEY']:
            self.assertFalse(fields[name]['sync']);self.assertNotIn('value',fields[name])
        self.assertNotIn('SECRET_KEY',fields);self.assertIn('$PORT',config['startCommand'])
        self.assertIn('gunicorn==26.2.0',(ROOT/'requirements.txt').read_text())
        self.assertIn('${PORT:-8000}',(ROOT/'Procfile').read_text())


class AuthenticationLoggingTests(unittest.TestCase):
    def setUp(self):
        self.auth=auth_code()
        self.user=SimpleNamespace(id=7,role='admin',is_active=True,password_hash=self.auth['get_password_hash']('synthetic-test-password'))
        self.db=Mock();self.db.query.return_value.filter.return_value.first.return_value=self.user

    def test_existing_key_validates_existing_tokens_and_new_tokens_keep_contract(self):
        old=jwt.encode({'sub':'7','role':'admin','exp':datetime.utcnow()+timedelta(minutes=5)},TEST_KEY,algorithm='HS256')
        self.assertIs(self.auth['get_current_user'](old,self.db),self.user)
        token=self.auth['create_access_token']({'sub':'7','role':'admin'})
        decoded=jwt.decode(token,TEST_KEY,algorithms=['HS256'])
        self.assertEqual(decoded['sub'],'7');self.assertEqual(decoded['role'],'admin')
        self.assertTrue(1700 <= decoded['exp']-int(datetime.now(timezone.utc).timestamp()) <= 1810)

    def test_expired_invalid_wrong_key_and_nonnumeric_subject_are_401(self):
        tokens=['not-a-token',jwt.encode({'sub':'7','exp':datetime.utcnow()-timedelta(seconds=1)},TEST_KEY,algorithm='HS256'),
                jwt.encode({'sub':'7'},'different-synthetic-key',algorithm='HS256'),jwt.encode({'sub':'not-an-integer'},TEST_KEY,algorithm='HS256')]
        for token in tokens:
            with self.assertRaises(HTTPException) as error:self.auth['get_current_user'](token,self.db)
            self.assertEqual(error.exception.status_code,401)

    def test_login_and_auth_logs_never_contain_secret_password_or_tokens(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output),self.assertLogs('tests.safe_auth',level='DEBUG') as captured:
            token=self.auth['create_access_token']({'sub':'7','role':'admin'})
            self.auth['get_current_user'](token,self.db)
            form=SimpleNamespace(username='0700000007',password='synthetic-test-password')
            login=self.auth['login'](form,self.db)
            with self.assertRaises(HTTPException):self.auth['get_current_user']('invalid-token-marker',self.db)
        logs=output.getvalue()+'\n'.join(captured.output)
        for secret in [TEST_KEY,token,login['access_token'],form.password,'invalid-token-marker']:
            self.assertTrue(secret not in logs,'Authentication logging exposed sensitive test input')
        self.assertIn('Authentication succeeded',logs)

    def test_inactive_accounts_and_role_checks_unchanged(self):
        token=self.auth['create_access_token']({'sub':'7'})
        self.user.is_active=False
        with self.assertRaises(HTTPException) as error:self.auth['get_current_user'](token,self.db)
        self.assertEqual(error.exception.status_code,401)
        with self.assertRaises(HTTPException) as error:self.auth['require_role']('owner')(self.user)
        self.assertEqual(error.exception.status_code,403)

    def test_invalid_password_login_does_not_log_credentials(self):
        output=io.StringIO()
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(output),self.assertRaises(HTTPException) as error:
            self.auth['login'](SimpleNamespace(username='0700000007',password='invalid-synthetic-password'),self.db)
        self.assertEqual(error.exception.status_code,401);self.assertEqual(output.getvalue(),'')


class SMSConfigurationTests(unittest.TestCase):
    def setUp(self):africastalking_client.get_sms_client.cache_clear()
    def tearDown(self):africastalking_client.get_sms_client.cache_clear()

    def test_missing_username_or_key_never_initializes_provider(self):
        for environment in [{},{'AFRICASTALKING_USERNAME':'test-account'},{'AFRICASTALKING_API_KEY':'synthetic-provider-key'}]:
            with patch.dict(os.environ,environment,clear=True),patch.object(africastalking_client.africastalking,'initialize') as initialize:
                with self.assertRaises(settings.ConfigurationError):africastalking_client.get_sms_client()
                initialize.assert_not_called()

    def test_environment_only_lazy_client_and_caching(self):
        with patch.dict(os.environ,{'AFRICASTALKING_USERNAME':'test-account','AFRICASTALKING_API_KEY':'synthetic-provider-key'},clear=True),patch.object(africastalking_client.africastalking,'initialize') as initialize:
            africastalking_client.get_sms_client();africastalking_client.get_sms_client()
            self.assertTrue(initialize.call_count==1)
            self.assertTrue(initialize.call_args.args==('test-account','synthetic-provider-key'))

    def test_provider_initialization_error_is_sanitized(self):
        with patch.dict(os.environ,{'AFRICASTALKING_USERNAME':'test-account','AFRICASTALKING_API_KEY':'synthetic-provider-key'},clear=True),patch.object(africastalking_client.africastalking,'initialize',side_effect=ValueError('synthetic-provider-key')):
            with self.assertRaises(settings.ConfigurationError) as error:africastalking_client.get_sms_client()
        self.assertNotIn('synthetic-provider-key',str(error.exception))

    def test_sms_success_preserves_send_contract_without_logging_payload(self):
        client=Mock();response={'SMSMessageData':{'Recipients':[{'status':'Success'}]},'test-sensitive-field':'synthetic-provider-key'};client.send.return_value=response
        with patch.object(sms,'get_sms_client',return_value=client),self.assertLogs('utils.sms',level='INFO') as captured:
            result=sms.send_sms(['0700000007','+254700000007'],'private-test-message')
        self.assertIs(result,response)
        self.assertTrue(client.send.call_args.args==('private-test-message',['+254700000007']))
        logs='\n'.join(captured.output)
        for private in ['private-test-message','synthetic-provider-key','254700000007']:self.assertTrue(private not in logs)

    def test_sms_errors_and_returned_diagnostics_do_not_include_provider_secrets(self):
        client=Mock();client.send.side_effect=ValueError('provider echoed synthetic-provider-key private-test-message')
        with patch.object(sms,'get_sms_client',return_value=client),self.assertLogs('utils.sms',level='WARNING') as captured:
            response=sms.send_sms(['0700000007'],'private-test-message')
        diagnostic=str(response)+'\n'.join(captured.output)
        self.assertTrue('synthetic-provider-key' not in diagnostic and 'private-test-message' not in diagnostic)
        self.assertTrue(bool(response['error']))

    def test_sender_keyword_compatibility_remains(self):
        client=Mock();client.send.side_effect=[TypeError("unexpected keyword argument 'sender_id'"),{'ok':True,'SMSMessageData':{'Recipients':[{'status':'Success'}]}}]
        with patch.object(sms,'get_sms_client',return_value=client):response=sms.send_sms(['0700000007'],'synthetic-message')
        self.assertTrue(response['ok']);self.assertEqual(client.send.call_count,2)
        self.assertIn('senderId',client.send.call_args.kwargs)

    def test_bootstrap_has_no_embedded_passwords_or_password_prints(self):
        source=(ROOT/'create_users.py').read_text();tree=ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='hash':
                self.assertTrue(not node.args or not isinstance(node.args[0],ast.Constant),'Bootstrap embeds a password')
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='print':
                self.assertNotIn('password',ast.unparse(node).casefold())
        self.assertIn('BOOTSTRAP_ADMIN_PASSWORD',source);self.assertIn('BOOTSTRAP_DRIVER_PASSWORD',source)


if __name__=='__main__':unittest.main()
