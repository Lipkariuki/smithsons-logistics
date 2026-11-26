import unittest
import os
from unittest.mock import patch
from types import SimpleNamespace
from fastapi import FastAPI,Response
import test_monthly_expense_api as api
from services.dhl_performance import install,timed,database_failure

class DiagnosticTests(unittest.TestCase):
    def request(self,app,method,path,**kw):
        return api.ApiTests.request(SimpleNamespace(app=app),method,path,**kw)
    def test_request_ids_and_503_diagnostics_do_not_log_secrets_or_plate_values(self):
        app=FastAPI();install(app)
        @app.post('/dhl-reports/probe/{plate}')
        @timed('probe')
        def probe(plate:str):
            database_failure(SimpleNamespace(orig=SimpleNamespace(sqlstate='55P03')))
            return Response('provider detail omitted',status_code=503)
        with self.assertLogs('services.dhl_performance',level='INFO') as logs,patch.dict(os.environ,{'RENDER_GIT_COMMIT':'a'*40}):
            status,_,headers=self.request(app,'POST','/dhl-reports/probe/PRIVATEPLATE',token='PRIVATE_TOKEN',json_body={'password':'PRIVATE_PASSWORD'})
        self.assertEqual(status,503);self.assertEqual(len(headers['x-request-id']),32)
        self.assertIn('probe;dur=',headers['server-timing'])
        self.assertEqual(headers['x-release-commit'],'a'*40)
        output=' '.join(logs.output)
        for secret in ['PRIVATEPLATE','PRIVATE_TOKEN','PRIVATE_PASSWORD']:self.assertNotIn(secret,output)
        self.assertIn('status=503',output);self.assertIn('/dhl-reports/probe/{plate}',output)
        self.assertIn('request_id='+headers['x-request-id']+' sqlstate=55P03',output)
    def test_new_requests_receive_distinct_identifiers(self):
        app=FastAPI();install(app)
        @app.get('/dhl-reports/ping')
        def ping():return {'ok':True}
        one=self.request(app,'GET','/dhl-reports/ping')[2];two=self.request(app,'GET','/dhl-reports/ping')[2]
        self.assertNotEqual(one['x-request-id'],two['x-request-id'])
if __name__=='__main__':unittest.main()
