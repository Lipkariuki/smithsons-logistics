"""Real Gunicorn/main startup + auth/report regression in a NEW disposable DB.
Requires PRODUCTION_SAFETY_TEST_URL: loopback PostgreSQL, name ending _test.
No production settings, provider initialization or real financial files are used.
"""
from pathlib import Path
import contextlib
from datetime import date,datetime,timedelta,timezone
import io,json,os,secrets,signal,subprocess,sys,tempfile,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sqlalchemy.engine import make_url


def run():
    target=os.environ.get('PRODUCTION_SAFETY_TEST_URL','')
    try:url=make_url(target)
    except Exception:raise RuntimeError('An explicit disposable test URL is required') from None
    if url.host not in {'localhost','127.0.0.1','::1'} or not (url.database or '').endswith('_test'):
        raise RuntimeError('Smoke test refuses nonlocal or non-test databases')
    key=secrets.token_urlsafe(40);password=secrets.token_urlsafe(24)
    os.environ.update(APP_ENV='production',DATABASE_URL=target,JWT_SECRET_KEY=key,
        AFRICASTALKING_USERNAME='synthetic-smoke-account',AFRICASTALKING_API_KEY='synthetic-smoke-provider-key',
        AFRICASTALKING_SENDER_ID='Smithsons',FLEET_SCHEDULER_ENABLED='false')
    from database import engine,Base,SessionLocal
    from models import User,Vehicle,DHLOrder
    from routers.auth import get_password_hash
    from sqlalchemy import text
    from jose import jwt
    from openpyxl import Workbook,load_workbook
    import requests
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        if c.execute(text('SELECT count(*) FROM users')).scalar_one():
            raise RuntimeError('Smoke test requires a fresh empty disposable database')
        c.exec_driver_sql((ROOT/'migrations/001_dhl_monthly_expenses.sql').read_text())
    with SessionLocal() as db:
        db.add_all([User(id=1,name='Synthetic security admin',phone='+254700000001',role='admin',password_hash=get_password_hash(password)),
                    User(id=2,name='Synthetic owner',role='owner',password_hash='unused')]);db.flush()
        db.add_all([Vehicle(id=1,plate_number='TEST100A',owner_id=2),Vehicle(id=2,plate_number='TEST200B',owner_id=2)]);db.flush()
        db.add(DHLOrder(date=date(2026,3,10),ref_no='SYNTHETIC',truck_plate='TEST100A',vehicle_id=1,distribution_cost=900,offloading_cost=100,total_revenue=1000));db.commit()
    # Token created BEFORE Gunicorn startup, with the same configured key.
    old_token=jwt.encode({'sub':'1','role':'admin','exp':datetime.now(timezone.utc)+timedelta(minutes=10)},key,algorithm='HS256')
    out=ROOT/'output/security-remediation';out.mkdir(parents=True,exist_ok=True)
    checks=[];logfile=Path('/tmp/smithsons-security-gunicorn.log');port=os.environ.get('PRODUCTION_SAFETY_TEST_PORT','8071');base='http://127.0.0.1:'+port
    session=requests.Session();session.headers['Authorization']='Bearer '+old_token
    def book(raw=False):
        wb=Workbook();ws=wb.active
        if raw:
            ws.append(['DATE','TRUCK','REF NO','COST','AMOUNT'])
            ws.append([date(2026,3,10),'TEST100A','SYNTHETIC','Dist',900]);ws.append([date(2026,3,10),'TEST100A','SYNTHETIC','Offloading',100])
            ws.append([date(2025,3,10),'TEST100A','OLD-SYNTHETIC','Dist',10])
        else:
            ws.append([None,'MARCH 2026 NET SUMMARY — SYNTHETIC ONLY'])
            ws.append(['TRUCK REG/NO','FUEL','BREAKAGES','TELEMATICS & VSS','GPRS','SHUNTING','TYRES'])
            ws.append(['TEST100A',None,20,30,0,50,75]);ws.append(['TEST200B',50,0,0,0,0,0])
        b=io.BytesIO();wb.save(b);wb.close();return b.getvalue()
    process=None
    with tempfile.TemporaryDirectory(prefix='smithsons-security-guard-') as temp,logfile.open('w') as logs:
        # Python loads this before Gunicorn; external connections cannot occur.
        Path(temp,'sitecustomize.py').write_text('''import socket
_original=socket.socket.connect
def guarded(self,address):
    if isinstance(address,tuple) and address[0] not in {'localhost','127.0.0.1','::1'}:
        raise RuntimeError('Security smoke test blocks nonlocal network access')
    return _original(self,address)
socket.socket.connect=guarded
''')
        env=dict(os.environ,PORT=port,WEB_CONCURRENCY='1',PYTHONPATH=temp)
        import yaml
        command=yaml.safe_load((ROOT/'render.yaml').read_text())['services'][0]['startCommand']
        # Execute the exact declared Render command with loopback HTTP test requests.
        env['PATH']=str(Path(sys.executable).parent)+os.pathsep+env.get('PATH','')
        process=subprocess.Popen(command,shell=True,env=env,cwd=ROOT,stdout=logs,stderr=logs,start_new_session=True)
        try:
            for _ in range(60):
                if process.poll() is not None:raise RuntimeError('Gunicorn failed to start')
                try:
                    if requests.get(base+'/openapi.json',timeout=1).status_code==200:break
                except requests.RequestException:pass
                time.sleep(.25)
            else:raise RuntimeError('Gunicorn readiness timeout')
            checks.append('Exact Render Gunicorn command boots real main.app with normal startup lifecycle and environment-only DB/JWT settings')
            response=session.get(base+'/users/me');response.raise_for_status();assert response.json()['id']==1
            checks.append('Pre-start token remains valid: effective signing key and algorithm unchanged')
            login=requests.post(base+'/login',data={'username':'0700000001','password':password});login.raise_for_status();new_token=login.json()['access_token']
            assert jwt.decode(new_token,key,algorithms=['HS256'])['sub']=='1';checks.append('Real login/password verification and token issuance succeed')
            assert requests.post(base+'/login',data={'username':'0700000001','password':'invalid-synthetic'}).status_code==401
            assert requests.get(base+'/users/me',headers={'Authorization':'Bearer invalid-synthetic-token'}).status_code==401
            net=book();raw=book(True)
            files={'file':('synthetic-expenses.xlsx',net),'raw_trips_file':('synthetic-trips.xlsx',raw)}
            preview=session.post(base+'/dhl-reports/expense-imports/preview',data={'month':'2026-03-01','options':'{}'},files=files);preview.raise_for_status();assert not preview.json()['ready']
            draft=session.post(base+'/dhl-reports/expense-imports',data={'month':'2026-03-01','options':'{}'},files=files);draft.raise_for_status();draft=draft.json()
            assert session.post(base+f"/dhl-reports/expense-imports/{draft['id']}/confirm").status_code==422
            options={'reason':'SYNTHETIC ONLY decisions','source_verification':'SYNTHETIC seeded source verified',
                     'corrections':{'B3':'100.00'},'approved_mappings':{'TYRES':'Tyres'},
                     'verified_no_activity':{'TEST200B':'SYNTHETIC no business'},
                     'date_dispositions':{'4':{'action':'exclude_from_period','reason':'SYNTHETIC historical row excluded'}}}
            form={'expected_file_sha256':draft['file_sha256'],'options':json.dumps(options),'mode':'preview'}
            review=session.post(base+f"/dhl-reports/expense-imports/{draft['id']}/revise",data=form);review.raise_for_status();assert review.json()['ready']
            form['mode']='save';revised=session.post(base+f"/dhl-reports/expense-imports/{draft['id']}/revise",data=form);revised.raise_for_status();revised=revised.json()
            confirmed=session.post(base+f"/dhl-reports/expense-imports/{revised['id']}/confirm");confirmed.raise_for_status();confirmed=confirmed.json()
            assert confirmed['totals']['net_payable']['amount']=='624.25'
            checks.append('Real monthly preview/date blocking/draft/stored revision/confirmation preserve dynamic expenses, positive-base commission and negative balances')
            summary=session.get(base+'/dhl-reports/monthly-net-summary',params={'month':'2026-03-01'});summary.raise_for_status();assert summary.json()['version']==2
            original=session.get(base+f"/dhl-reports/expense-imports/{draft['id']}");original.raise_for_status();assert original.json()['status']=='draft'
            for fmt in ['xlsx','pdf']:
                export=session.get(base+f"/dhl-reports/expense-imports/{revised['id']}/export",params={'format':fmt});export.raise_for_status();assert 'dhl' not in export.headers['content-disposition'].lower();(out/('synthetic-summary.'+fmt)).write_bytes(export.content)
            checks.append('Authenticated history, monthly summary and real Excel/PDF downloads succeed')
            manual=session.post(base+'/dhl-reports/payslips',json={'vehicle_id':1,'period_start':'2026-03-01','period_end':'2026-03-31','commission_rate':.07,'expenses':[{'name':'Fuel','amount':200}]});manual.raise_for_status();assert manual.json()['net_pay']==730
            checks.append('Legacy manual payslip arithmetic remains unchanged')
        finally:
            if process.poll() is None:
                os.killpg(process.pid,signal.SIGTERM)
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
    captured=logfile.read_text()
    for sensitive in [key,password,old_token,new_token,url.password,'synthetic-smoke-provider-key']:
        assert sensitive not in captured,'Sensitive input appeared in Gunicorn/application logs'
    assert 'Loaded SECRET_KEY' not in captured and 'Received token' not in captured
    checks.append('Gunicorn/application logs contain no test passwords, DB password, signing key, access tokens or provider key')
    engine.dispose()
    (out/'startup-and-workflow.json').write_text(json.dumps({'success':True,'checks':checks,'normal_startup':True,'sms_scheduler_disabled':True,'external_connections_blocked':True,'monthly_net':'624.25','legacy_manual_net':730},indent=2))
    print('Gunicorn startup, auth continuity, sanitized logs and monthly-report regression: PASS')


if __name__=='__main__':
    try:run()
    except Exception as exc:
        print('Security smoke test failed; exception type: '+type(exc).__name__)
        sys.exit(1)
