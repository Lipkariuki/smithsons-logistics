"""Acceptance through real HTTP. Explicit synthetic localhost fixtures only.

Never supplies production credentials or sends requests to nonlocal hosts.
"""
import io
import json
import os
from pathlib import Path
import unittest
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit

import requests
from openpyxl import Workbook
from pypdf import PdfReader
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BASE=os.environ.get('LEGACY_AUTH_HTTP_BASE')
FIXTURE=os.environ.get('LEGACY_AUTH_FIXTURE_JSON')
URL=os.environ.get('ACCEPTANCE_HTTP_DATABASE_URL')


def workbook(values):
    book=Workbook()
    for row in values:book.active.append(row)
    out=io.BytesIO();book.save(out);book.close();return out.getvalue()


@unittest.skipUnless(BASE and FIXTURE and URL,'Explicit synthetic local HTTP/database fixtures required')
class FinancialAcceptanceHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if urlsplit(BASE).hostname not in {'localhost','127.0.0.1'} or make_url(URL).host not in {'localhost','127.0.0.1'} or make_url(URL).database!='smithsons_auth_audit_test':
            raise RuntimeError('Acceptance tests refuse production/non-test targets')
        cls.config=json.loads(Path(FIXTURE).read_text())
        cls.engine=create_engine(URL)
        with cls.engine.begin() as conn:
            assert conn.execute(text('SELECT name FROM users WHERE id=1')).scalar_one()=='Synthetic admin 1'
            conn.execute(text("SELECT setval(pg_get_serial_sequence('dhl_orders','id'),(SELECT max(id) FROM dhl_orders))"))
            conn.execute(text("INSERT INTO vehicles (id,plate_number,owner_id,size) VALUES (3,'TEST300C',2,'10 Ton')"))

    @classmethod
    def tearDownClass(cls):cls.engine.dispose()

    def request(self,method,path,**kwargs):
        return requests.request(method,BASE+path,headers={'Authorization':'Bearer '+self.config['tokens']['admin']},timeout=30,**kwargs)

    def test_legacy_post_404_is_application_error_not_missing_route(self):
        payload={'vehicle_id':999999,'period_start':'2026-06-01','period_end':'2026-06-30','commission_rate':.07,'expenses':[]}
        response=self.request('POST','/dhl-reports/payslips',json=payload)
        self.assertEqual((response.status_code,response.json()),(404,{'detail':'Vehicle not found'}))
        payload['vehicle_id']=1
        response=self.request('POST','/dhl-reports/payslips',json=payload)
        self.assertEqual((response.status_code,response.json()),(404,{'detail':'No DHL revenue found for the selected period'}))
        with self.engine.begin() as conn:self.assertEqual(conn.execute(text('SELECT count(*) FROM dhl_payslips')).scalar_one(),0)

    def test_raw_reupload_preserves_existing_legacy_payslip_and_source(self):
        raw=workbook([['DATE','TRUCK','REF NO','COST','AMOUNT'],[date(2026,8,10),'TEST100A','LEGACY-SAFETY','Dist',1000]])
        response=self.request('POST','/dhl-reports/upload',files={'file':('synthetic-august.xlsx',raw)})
        self.assertEqual(response.status_code,200,response.text)
        response=self.request('POST','/dhl-reports/payslips',json={'vehicle_id':1,'period_start':'2026-08-01','period_end':'2026-08-31','expenses':[{'name':'Synthetic legacy expense','amount':20}]})
        self.assertEqual(response.status_code,200,response.text);identifier=response.json()['id']
        with self.engine.begin() as conn:
            before={table:conn.execute(text('SELECT row_to_json(t)::text FROM '+table+' t ORDER BY row_to_json(t)::text')).scalars().all() for table in ['dhl_orders','dhl_payslips','dhl_payslip_expenses','dhl_payslip_documents']}
        changed=workbook([['DATE','TRUCK','REF NO','COST','AMOUNT'],[date(2026,8,10),'TEST100A','LEGACY-SAFETY','Dist',2000]])
        response=self.request('POST','/dhl-reports/upload',files={'file':('synthetic-august-revised.xlsx',changed)})
        self.assertEqual(response.status_code,409,response.text);self.assertIn('preserve',response.json()['detail'])
        self.assertEqual(self.request('GET',f'/dhl-reports/payslips/{identifier}').status_code,200)
        with self.engine.begin() as conn:
            after={table:conn.execute(text('SELECT row_to_json(t)::text FROM '+table+' t ORDER BY row_to_json(t)::text')).scalars().all() for table in before}
            self.assertEqual(before,after)

    def test_upload_conflicting_manual_write_returns_bounded_conflict(self):
        raw=workbook([['DATE','TRUCK','REF NO','COST','AMOUNT'],[date(2026,9,10),'TEST100A','LOCK-SAFETY','Dist',1000]])
        with self.engine.begin() as conn:
            conn.execute(text('LOCK TABLE dhl_payslips IN ROW EXCLUSIVE MODE'))
            response=self.request('POST','/dhl-reports/upload',files={'file':('synthetic-september.xlsx',raw)})
        self.assertEqual(response.status_code,409,response.text)
        with self.engine.begin() as conn:self.assertEqual(conn.execute(text("SELECT count(*) FROM dhl_orders WHERE ref_no='LOCK-SAFETY'")).scalar_one(),0)

    def test_upload_validation_isolated_no_records_created(self):
        response=self.request('POST','/dhl-reports/upload',files={'file':('empty.xlsx',b'')})
        self.assertEqual(response.status_code,400)
        mixed=workbook([['DATE','TRUCK','REF NO','COST','AMOUNT'],[date(2026,6,10),'TEST100A','JUNE','Dist',10],[date(2025,6,10),'TEST100A','HIST','Dist',20]])
        response=self.request('POST','/dhl-reports/upload',files={'file':('mixed.xlsx',mixed)})
        self.assertEqual(response.status_code,400);self.assertIn('multiple months',response.json()['detail'])
        response=self.request('POST','/dhl-reports/expense-imports/preview',data={'month':'2026-07-01','options':'{}'},files={'file':('wrong.csv',b'not an xlsx')})
        self.assertEqual(response.status_code,415)
        response=self.request('POST','/dhl-reports/expense-imports/preview',data={'month':'2026-07-01','options':'{}'},files={'file':('empty.xlsx',b'')})
        self.assertEqual(response.status_code,422)

    def test_raw_upload_expense_replacement_confirmation_and_immutable_pdf(self):
        raw=workbook([['DATE','TRUCK','REF NO','COST','AMOUNT'],
            [date(2026,7,10),' TEST 100A ','ACCEPT-A','Dist',900],
            [date(2026,7,10),'TEST100A','ACCEPT-A','Offloading',100],
            [date(2026,7,10),'TEST100A','ACCEPT-A','Admin',-400],
            [date(2026,7,10),'TEST200A','ACCEPT-B','Dist',500],
            [date(2026,7,10),'TEST200A','ACCEPT-B','Offloading',50]])
        response=self.request('POST','/dhl-reports/upload',files={'file':('synthetic-july-trips.xlsx',raw)})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['inserted'],2)
        def net(fuel=None):
            return workbook([['JULY 2026 NET SUMMARY'],['TRUCK REG/NO','FUEL','BREAKAGES','TELEMATICS & VSS','Tyres','NET PAID I','NET PAID 2'],
                ['test 100a',fuel,20,0,25,999999,777777],['TEST300C',100,0,0,0,0,0]])
        options={'source_verification':'SYNTHETIC July full source verified','approved_mappings':{'Tyres':'Tyres'},'reason':'Synthetic acceptance only'}
        def upload(path,content,settings):
            return self.request('POST',path,data={'month':'2026-07-01','options':json.dumps(settings)},files={'file':('synthetic-july-net.xlsx',content),'raw_trips_file':('synthetic-july-trips.xlsx',raw)})
        response=upload('/dhl-reports/expense-imports/preview',net(),{})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(any(h['classification']=='unknown' and h['original_header']=='Tyres' for h in response.json()['header_mappings']))
        response=upload('/dhl-reports/expense-imports',net(),options)
        self.assertEqual(response.status_code,201,response.text);batch=response.json();a,b=batch['rows']
        self.assertEqual(a['normalized_plate'],'TEST100A');self.assertEqual(a['vehicle_id'],1)
        self.assertEqual((a['gross'],a['operating_expenses'],a['commission'],a['net_payable']),('1000.00','45.00','66.85','888.15'))
        self.assertEqual(a['deductions']['fuel']['resolution'],'blank_to_zero');self.assertEqual(a['deductions']['fuel']['amount'],'0.00')
        self.assertEqual(a['deductions']['tyres']['amount'],'25.00');self.assertEqual(b['operating_expenses'],'100.00');self.assertIsNone(b['gross'])
        self.assertTrue(a['truck_confirmation']['can_confirm']);self.assertFalse(b['truck_confirmation']['can_confirm'])
        with self.engine.begin() as conn:legacy_before={table:conn.execute(text('SELECT count(*) FROM '+table)).scalar_one() for table in ['orders','trips','expenses','commissions','dhl_payslips','dhl_payslip_documents']}
        response=self.request('POST',f"/dhl-reports/expense-rows/{a['id']}/confirm",json={'reason':'Synthetic eligible A only'})
        self.assertEqual(response.status_code,200,response.text);approval=response.json()
        response=self.request('POST',f"/dhl-reports/monthly-statement-documents/from-row/{a['id']}")
        self.assertEqual(response.status_code,200,response.text);document=response.json()
        content=self.request('GET',f"/dhl-reports/monthly-statement-documents/{document['id']}/pdf").content
        pdf=PdfReader(io.BytesIO(content));printed='\n'.join(p.extract_text() for p in pdf.pages)
        for expected in ['SMITHSONS LOGISTICS','BREAKAGES','Tyres','KES 45.00','KES 66.85','KES 888.15']:self.assertIn(expected,printed)
        self.assertNotIn('DHL',printed);self.assertNotIn('NET PAID',printed);self.assertNotIn('FUEL',printed)
        self.assertEqual(sum(Decimal(d['amount']) for d in a['deductions'].values()),Decimal(a['operating_expenses']))
        response=upload('/dhl-reports/expense-imports',net(100),dict(options,previous_version_id=batch['id'],reason='Synthetic corrected workbook'))
        self.assertEqual(response.status_code,201,response.text);replacement=response.json();new_a=replacement['rows'][0]
        self.assertEqual((new_a['operating_expenses'],new_a['commission'],new_a['net_payable']),('145.00','59.85','795.15'))
        response=self.request('POST',f"/dhl-reports/expense-rows/{new_a['id']}/confirm",json={'reason':'Synthetic corrected A only','expected_current_confirmation_id':approval['id']})
        self.assertEqual(response.status_code,200,response.text);adjustment=response.json()['validation']['financial_adjustment']
        self.assertEqual(adjustment['net_payable_difference'],'-93.00');self.assertFalse(adjustment['payment_processing'])
        self.assertEqual(self.request('GET',f"/dhl-reports/monthly-statement-documents/{document['id']}/pdf").content,content)
        response=self.request('POST',f"/dhl-reports/monthly-statement-documents/from-row/{new_a['id']}");self.assertEqual(response.status_code,200,response.text)
        amended=self.request('GET',f"/dhl-reports/monthly-statement-documents/{response.json()['id']}/pdf").content
        self.assertIn('Separate correction adjustment: KES -93.00',PdfReader(io.BytesIO(amended)).pages[0].extract_text())
        if os.environ.get('ACCEPTANCE_PDF_PATH'):Path(os.environ['ACCEPTANCE_PDF_PATH']).write_bytes(amended)
        # Raw reupload replaces live DHL records without changing approved source/PDF snapshots.
        response=self.request('POST','/dhl-reports/upload',files={'file':('synthetic-july-reupload.xlsx',raw)})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.request('GET',f"/dhl-reports/monthly-statement-documents/{document['id']}/pdf").content,content)
        response=self.request('GET','/dhl-reports/reconciliation?start_date=2026-07-01&end_date=2026-07-31&include_details=true&financial_version=2')
        self.assertEqual(response.status_code,200,response.text);detail=response.json()['details']
        self.assertEqual(detail['totals']['dhl_gross_by_reference'],'1550.00');self.assertEqual(detail['totals']['dhl_gross_by_truck'],'1550.00')
        self.assertEqual(detail['totals']['payout_roster_dhl_gross'],'1000.00');self.assertEqual(detail['totals']['outside_payout_roster_gross'],'550.00')
        self.assertEqual(detail['totals']['roster_accounting_difference'],'0.00')
        self.assertTrue(any('dhl_only' in r['status'] for r in detail['order_rows']))
        self.assertTrue(any(r['plate_number']=='TEST300C' and 'revenue_not_verified_zero' in r['status'] for r in detail['truck_rows']))
        with self.engine.begin() as conn:
            self.assertEqual(legacy_before,{table:conn.execute(text('SELECT count(*) FROM '+table)).scalar_one() for table in legacy_before})
