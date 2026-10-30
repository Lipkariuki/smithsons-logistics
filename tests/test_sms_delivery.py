"""Delivery acceptance and actual report handler; no SMS or database connections."""
import ast
import asyncio
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import Depends, FastAPI, HTTPException
from settings import ConfigurationError
from utils import sms


def result(code=100):
    return {'SMSMessageData': {'Recipients': [{'statusCode': code, 'status': 'Success' if code < 400 else 'Rejected'}]}}


class SMSDeliveryTests(unittest.TestCase):
    def test_processed_sent_and_queued_are_accepted_not_delivered(self):
        for code in [100, 101, 102]:
            with self.subTest(code=code), patch.object(sms, 'get_sms_client', return_value=Mock(send=Mock(return_value=result(code)))):
                response=sms.send_sms(['0700000007'], 'synthetic test')
                self.assertNotIn('error', response)

    def test_provider_rejection_is_failure_even_with_http_success(self):
        for code in [401, 402, 403, 405, 406, 502]:
            with self.subTest(code=code), patch.object(sms, 'get_sms_client', return_value=Mock(send=Mock(return_value=result(code)))):
                with self.assertLogs('utils.sms', level='WARNING') as logs:
                    response=sms.send_sms(['0700000007'], 'private-message')
                self.assertEqual(response['code'], 'provider_rejected')
                self.assertEqual(response['status_codes'], [code])
                self.assertNotIn('private-message', str(logs.output))
                self.assertNotIn('700000007', str(logs.output))

    def test_partial_and_missing_acknowledgements_are_not_success(self):
        partial=result();partial['SMSMessageData']['Recipients'].append({'statusCode':405})
        for response in [{}, {'SMSMessageData': {'Recipients': []}}, partial]:
            with patch.object(sms, 'get_sms_client', return_value=Mock(send=Mock(return_value=response))):
                self.assertIn('error',sms.send_sms(['0700000001','0700000002'], 'synthetic'))

    def test_safe_exception_diagnostics(self):
        for exc, expected in [(ConfigurationError('private-key'), 'configuration_missing'),(RuntimeError('private-key'), 'provider_request_failed')]:
            with patch.object(sms, 'get_sms_client', side_effect=exc), self.assertLogs('utils.sms', level='WARNING') as logs:
                response=sms.send_sms(['0700000001'], 'private-message')
            self.assertEqual(response['code'],expected)
            self.assertNotIn('private-key',str(logs.output)+str(response))
        exc=RuntimeError('private-key');exc.response=SimpleNamespace(status_code=401)
        with patch.object(sms, 'get_sms_client', side_effect=exc):
            self.assertEqual(sms.send_sms(['0700000001'],'synthetic')['code'],'provider_authentication')

    def test_report_endpoint_returns_502_for_failure_and_acceptance_for_success(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'routers/reports.py').read_text())
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='send_vehicle_report')
        function.decorator_list=[]
        report=SimpleNamespace(owner_phone='0700000001',owner_name='Synthetic Partner',plate_number='TEST100A',trip_count=1,gross_revenue=1000,fuel_cost=100,fuel_litres_total=10,other_expenses=0,extra_expenses=0,commission=63,net_profit=837,actual_payment=None)
        send=Mock()
        namespace=dict(SendReportPayload=object,Session=object,Depends=Depends,get_db=lambda:None,HTTPException=HTTPException,date=date,_default_dates=lambda *a:(date(2026,3,1),date(2026,3,31)),_build_vehicle_reports=lambda *a:[report],send_sms=send)
        exec(compile(ast.Module(body=[function],type_ignores=[]),'actual-report-handler','exec'),namespace)
        app=FastAPI()
        @app.post('/reports/send')
        def endpoint():
            return namespace['send_vehicle_report'](SimpleNamespace(vehicle_id=1,start_date=None,end_date=None),db=object())
        async def request():
            events=[]
            async def receive():
                return {'type':'http.request','body':b'', 'more_body':False}
            async def send(event):events.append(event)
            await app({'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':'POST','scheme':'http','path':'/reports/send','raw_path':b'/reports/send','query_string':b'','headers':[],'server':('test',80),'client':('test',1)},receive,send)
            return next(e['status'] for e in events if e['type']=='http.response.start'),json.loads(b''.join(e.get('body',b'') for e in events if e['type']=='http.response.body'))
        send.return_value={'error':'failed'}
        self.assertEqual(asyncio.run(request())[0],502)
        send.return_value=result()
        status,body=asyncio.run(request())
        self.assertEqual(status,200)
        self.assertEqual(body['status'],'accepted')
        self.assertIn('not yet confirmed',body['message'])


if __name__=='__main__':unittest.main()
