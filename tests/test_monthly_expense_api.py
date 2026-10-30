"""Real ASGI/API + PostgreSQL tests, with existing auth functions and isolated users.

No production main/database/models/auth modules are imported. Existing JWT and role
functions are loaded directly from their source with only their dependencies injected.
"""
import ast
import asyncio
import contextlib
from datetime import datetime, timedelta
import io
import json
import logging
import os
from pathlib import Path
import unittest
from types import SimpleNamespace

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from openpyxl import load_workbook
from pypdf import PdfReader
from sqlalchemy import text, column

import test_monthly_expense_persistence as fixtures
from routers.monthly_expense_reports import create_router
from services.monthly_expense_reconciliation import compare_amount
from decimal import Decimal

ROOT = Path(__file__).resolve().parents[1]


def multipart(content, options=None, filename='expense.xlsx', raw=None, fields=None):
    boundary = 'smithsons-isolated-test-boundary'
    parts = []
    for name, value in [('month', '2026-02-01'), ('options', json.dumps(options or {}))] + list((fields or {}).items()):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    for name, fname, data in ([] if content is None else [('file', filename, content)]) + ([] if raw is None else [('raw_trips_file', 'raw.xlsx', raw)]):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{fname}"\r\nContent-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n'.encode() + data + b'\r\n')
    parts.append(f'--{boundary}--\r\n'.encode())
    return b''.join(parts), f'multipart/form-data; boundary={boundary}'


def auth_functions(engine):
    class AuthSession:
        def query(self, model):
            return self
        def filter(self, expression):
            self.identifier = expression.right.value
            return self
        def first(self):
            with engine.connect() as connection:
                row = connection.execute(text('SELECT id, name, role, is_active FROM users WHERE id=:id'), {'id': self.identifier}).mappings().first()
            return None if row is None else SimpleNamespace(**row)
    def auth_db():
        yield AuthSession()
    namespace = dict(logger=logging.getLogger('tests.isolated_auth'), Depends=Depends, HTTPException=HTTPException, status=status,
                     oauth2_scheme=OAuth2PasswordBearer(tokenUrl='login'), Session=object,
                     get_db=auth_db, User=type('User', (), {'id': column('id')}),
                     jwt=jwt, JWTError=JWTError, SECRET_KEY='isolated-phase3-test-only', ALGORITHM='HS256')
    tree = ast.parse((ROOT / 'routers/auth.py').read_text())
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'get_current_user', 'require_role'}]
    exec(compile(ast.Module(body=selected, type_ignores=[]), 'isolated-existing-auth', 'exec'), namespace)
    return namespace['require_role']('admin')


@unittest.skipUnless(fixtures.URL, 'Set MONTHLY_EXPENSE_TEST_URL to local disposable PostgreSQL')
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.PersistenceTests.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):
        fixtures.PersistenceTests.tearDownClass.__func__(cls)
    def legacy(self, conn):
        snapshot = fixtures.PersistenceTests.legacy(self, conn)
        for name in ('orders', 'trips'):
            snapshot[name] = conn.execute(text(f'SELECT * FROM {name} ORDER BY id')).all()
        return snapshot

    def setUp(self):
        fixtures.PersistenceTests.setUp(self)
        with self.engine.begin() as connection:
            connection.exec_driver_sql("""CREATE TABLE orders (id INTEGER PRIMARY KEY, total_amount DOUBLE PRECISION);
                CREATE TABLE trips (id INTEGER PRIMARY KEY, revenue DOUBLE PRECISION);
                INSERT INTO orders VALUES (1,1234);
                INSERT INTO trips VALUES (1,1234);
                ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'admin';
                ALTER TABLE users ADD COLUMN is_active BOOLEAN DEFAULT TRUE;
                INSERT INTO users (id,name,role,is_active) VALUES (8,'Owner','owner',true),(9,'Driver','driver',true),(10,'Inactive','admin',false);""")
        def connection_dependency():
            with self.engine.begin() as connection:
                yield connection
        self.app = FastAPI()
        self.app.include_router(create_router(connection_dependency, auth_functions(self.engine)))

    def tearDown(self):
        fixtures.PersistenceTests.tearDown(self)

    def request(self, method, url, content=None, options=None, filename='expense.xlsx', raw=None, user=7, token=None, form_fields=None, json_body=None):
        path, _, query = url.partition('?')
        headers = []
        body = b''
        if json_body is not None:
            body = json.dumps(json_body).encode()
            headers += [(b'content-type', b'application/json')]
        if content is not None or form_fields is not None:
            if raw is None and form_fields is None:
                with self.engine.begin() as connection:
                    raw = fixtures.raw_book(connection)
            body, kind = multipart(content, options, filename, raw, form_fields)
            headers += [(b'content-type', kind.encode()), (b'content-length', str(len(body)).encode())]
        if user is not None:
            token = token or jwt.encode({'sub': str(user), 'exp': datetime.utcnow() + timedelta(minutes=5)},
                                        'isolated-phase3-test-only', algorithm='HS256')
            headers.append((b'authorization', f'Bearer {token}'.encode()))
        messages = []
        async def run():
            async def receive():
                return {'type': 'http.request', 'body': body, 'more_body': False}
            async def send(message):
                messages.append(message)
            await self.app({'type':'http', 'asgi':{'version':'3.0'}, 'http_version':'1.1',
                'method':method, 'scheme':'http', 'path':path, 'raw_path':path.encode(),
                'query_string':query.encode(), 'root_path':'', 'headers':headers,
                'client':('127.0.0.1', 1234), 'server':('test',80)}, receive, send)
        with contextlib.redirect_stdout(io.StringIO()):
            asyncio.run(run())
        response_headers = dict((k.decode(), v.decode()) for k,v in messages[0]['headers'])
        payload = b''.join(message.get('body', b'') for message in messages)
        data = json.loads(payload) if 'application/json' in response_headers.get('content-type', '') else payload
        return messages[0]['status'], data, response_headers

    def save(self, content=None, options=None, raw=None):
        configuration = {'source_verification': 'Reviewed full February source', **(options or {})}
        code, data, _ = self.request('POST', '/dhl-reports/expense-imports', fixtures.book() if content is None else content, configuration, raw=raw)
        self.assertEqual(code, 201, data)
        return data

    def test_admin_authentication_and_authorization_all_routes(self):
        routes = [('POST','/dhl-reports/expense-imports/preview'), ('POST','/dhl-reports/expense-imports'),
            ('GET','/dhl-reports/expense-imports/1'), ('POST','/dhl-reports/expense-imports/1/confirm'),
            ('GET','/dhl-reports/monthly-net-summary?month=2026-02-01'),
            ('GET','/dhl-reports/expense-imports/1/export?format=xlsx'), ('GET','/dhl-reports/expense-imports/1/export?format=pdf')]
        for method, url in routes:
            for user, expected in [(None,401),(8,403),(9,403),(10,401)]:
                with self.subTest(url=url,user=user):
                    content = fixtures.book() if url.endswith(('preview','expense-imports')) else None
                    self.assertEqual(self.request(method,url,content,user=user)[0], expected)
        expired = jwt.encode({'sub':'7','exp':datetime.utcnow()-timedelta(minutes=1)}, 'isolated-phase3-test-only', algorithm='HS256')
        self.assertEqual(self.request('GET','/dhl-reports/expense-imports/1', token=expired)[0],401)
        self.assertEqual(self.request('GET','/dhl-reports/expense-imports/1', token='invalid')[0],401)

    def test_preview_read_only_save_confirm_and_summary(self):
        with self.engine.begin() as conn:
            before = self.legacy(conn)
        code, data, _ = self.request('POST','/dhl-reports/expense-imports/preview',fixtures.book(), {'source_verification':'Reviewed'})
        self.assertEqual(code,200,data)
        self.assertNotIn('source_content', data)
        self.assertTrue(data['ready'])
        self.assertEqual(data['rows'][0]['net_payable'],'744.00')
        self.assertEqual(data['assumptions'][0]['code'],'optional_category_absent')
        with self.engine.begin() as conn:
            self.assertEqual(conn.execute(text('SELECT count(*) FROM dhl_monthly_expense_imports')).scalar_one(),0)
        saved = self.save()
        code, detail, _ = self.request('GET',f"/dhl-reports/expense-imports/{saved['id']}")
        self.assertEqual(code,200)
        self.assertEqual(detail['versions'][0]['status'],'draft')
        code, confirmed, _ = self.request('POST',f"/dhl-reports/expense-imports/{saved['id']}/confirm")
        self.assertEqual(code,200,confirmed)
        code, summary, _ = self.request('GET','/dhl-reports/monthly-net-summary?month=2026-02-01&owner_id=7&vehicle_id=1')
        self.assertEqual(code,200)
        self.assertEqual(summary['totals']['net_payable']['amount'],'744.00')
        with self.engine.begin() as conn:
            self.assertEqual(self.legacy(conn),before)

    def test_invalid_files_options_types_sizes_and_month(self):
        cases = [(b'not an excel','bad.xlsx',{},422), (fixtures.book(),'bad.xls',{},415),
                 (b'','empty.xlsx',{},422), (b'x'*20_000_001,'large.xlsx',{},413),
                 (fixtures.book(),'valid.xlsx',{'net_payable':'1'},422),
                 (fixtures.book(),'valid.xlsx',{'corrections':{'B3':0}},422)]
        for content, filename, options, expected in cases:
            with self.subTest(filename=filename, expected=expected):
                self.assertEqual(self.request('POST','/dhl-reports/expense-imports/preview',content,options,filename)[0],expected)
        self.assertEqual(self.request('GET','/dhl-reports/monthly-net-summary?month=2026-02-02')[0],422)
        self.assertEqual(self.request('GET','/dhl-reports/expense-imports/999')[0],404)
        self.assertEqual(self.request('GET','/dhl-reports/expense-imports/999/export?format=csv')[0],422)

    def test_blank_dynamic_mapping_and_corrected_successor(self):
        content = fixtures.book(blank=True,extra=True)
        bad = self.save(content)
        self.assertFalse(bad['ready'])
        self.assertEqual(self.request('POST',f"/dhl-reports/expense-imports/{bad['id']}/confirm")[0],422)
        fixed = self.save(content, {'previous_version_id':bad['id'], 'reason':'Approved Tyres and confirmed blank as zero',
                                   'approved_mappings':{'Tyres':'Tyres'}, 'corrections':{'B3':'0.00'}})
        self.assertEqual(fixed['rows'][0]['deductions']['tyres']['amount'],'75.00')
        self.assertEqual(self.request('POST',f"/dhl-reports/expense-imports/{fixed['id']}/confirm")[0],200)

    def test_missing_versus_verified_zero_and_negative_balance(self):
        with self.engine.begin() as conn:
            conn.execute(text('DELETE FROM dhl_orders'))
        missing = self.save()
        self.assertIsNone(missing['rows'][0]['gross'])
        self.assertIsNone(missing['totals']['net_payable']['amount'])
        self.assertEqual(self.request('POST',f"/dhl-reports/expense-imports/{missing['id']}/confirm")[0],422)
        zero = self.save(options={'previous_version_id':missing['id'],'reason':'Reviewed no business',
                                 'verified_no_activity':{'KAA123B':'Dispatch register confirms no business'}})
        row = zero['rows'][0]
        self.assertEqual((row['gross'],row['commission'],row['net_payable']),('0.00','0.00','-200.00'))
        self.assertEqual(self.request('POST',f"/dhl-reports/expense-imports/{zero['id']}/confirm")[0],200)

    def test_duplicate_version_conflicts_and_source_changes(self):
        content = fixtures.book()
        first = self.save(content)
        duplicate = self.request('POST','/dhl-reports/expense-imports',content,{'source_verification':'Reviewed'})
        self.assertEqual(duplicate[0],409)
        self.assertEqual(duplicate[1]['detail']['existing_import_id'],first['id'])
        sibling = self.save(fixtures.book(150))
        self.assertEqual(self.request('POST',f"/dhl-reports/expense-imports/{first['id']}/confirm")[0],200)
        self.assertEqual(self.request('POST',f"/dhl-reports/expense-imports/{sibling['id']}/confirm")[0],409)
        successor = self.save(fixtures.book(175),{'previous_version_id':first['id'],'reason':'Correction'})
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE dhl_orders SET total_revenue=2000, distribution_cost=1900'))
        self.assertEqual(self.request('POST',f"/dhl-reports/expense-imports/{successor['id']}/confirm")[0],409)
        refreshed = self.save(fixtures.book(175),{'previous_version_id':first['id'],'reason':'Review changed source'})
        self.assertEqual(self.request('POST',f"/dhl-reports/expense-imports/{refreshed['id']}/confirm")[0],200)
        code, historic, _ = self.request('GET','/dhl-reports/monthly-net-summary?month=2026-02-01&version=1')
        self.assertEqual(code,200)
        self.assertEqual(historic['status'],'superseded')
        self.assertEqual(historic['rows'][0]['gross'],'1000.00')

    def test_manual_reference_verification_and_intermediate_rejection(self):
        unverified = self.save()
        self.assertEqual(unverified['rows'][0]['comparisons']['net_payable']['status'],'unverified_reference')
        options = {'reference_columns':{'net_payable':'NET PAID'},'reference_verification':'Final NET PAID meaning checked'}
        compared = self.save(fixtures.book(125),options)
        comparison = compared['rows'][0]['comparisons']['net_payable']
        self.assertEqual(comparison['status'],'material_difference')
        self.assertEqual(compared['rows'][0]['net_payable'],'720.75')
        self.assertEqual(comparison['difference'],'-999278.25')
        for header in ('NET PAID I','NET PAID 2'):
            config = {**options, 'reference_columns':{'net_payable':header}}
            self.assertEqual(self.request('POST','/dhl-reports/expense-imports/preview',fixtures.book(),config)[0],422)
        self.assertEqual(self.request('POST','/dhl-reports/expense-imports/preview',fixtures.book(),{'reference_columns':{'net_payable':'NET PAID'}})[0],422)

    def test_exports_saved_snapshot_branding_and_formula_injection(self):
        content = fixtures.book(extra=True)
        saved = self.save(content,{'approved_mappings':{'Tyres':'=DHL Repairs'},'reason':'Approved category'})
        self.assertEqual(self.request('POST',f"/dhl-reports/expense-imports/{saved['id']}/confirm")[0],200)
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE dhl_orders SET total_revenue=999999'))
        for kind in ('xlsx','pdf'):
            code, body, headers = self.request('GET',f"/dhl-reports/expense-imports/{saved['id']}/export?format={kind}")
            self.assertEqual(code,200)
            self.assertNotIn('dhl',headers['content-disposition'].lower())
            if kind == 'xlsx':
                wb = load_workbook(io.BytesIO(body),data_only=False)
                text_content = ' '.join(str(c.value) for ws in wb for row in ws for c in row if c.value is not None)
                self.assertIn('SMITHSONS LOGISTICS',text_content)
                self.assertNotIn('dhl',text_content.lower())
                self.assertFalse(any(c.data_type=='f' for ws in wb for row in ws for c in row))
                self.assertIn("'=Smithsons Logistics Repairs",text_content)
                self.assertEqual(wb['Monthly Summary']['C5'].value,1000)
                self.assertNotIn('dhl',str(wb.properties).lower())
                wb.close()
            else:
                pdf = PdfReader(io.BytesIO(body))
                text_content = '\n'.join(page.extract_text() for page in pdf.pages)
                self.assertIn('SMITHSONS LOGISTICS',text_content)
                self.assertIn('KES 1,000.00',text_content)
                self.assertNotIn('dhl',(text_content+str(pdf.metadata)).lower())
                self.assertIn('confirmed',text_content.lower())

    def test_all_three_verified_references(self):
        from openpyxl import Workbook
        wb=Workbook();ws=wb.active
        ws.append([None,'FEBRUARY 2026 NET SUMMARY'])
        ws.append(['TRUCK REG/NO','FUEL','BREAKAGES','TELEMATICS & VSS','GPRS','SHUNTING',
                   'GROSS AMOUNT','7% COMMISSION','NET PAID','NET PAID I','NET PAID 2'])
        ws.append(['KAA123B',100,20,30,0,50,1000,55,744.01,123456,123456])
        stream=io.BytesIO();wb.save(stream);wb.close()
        saved=self.save(stream.getvalue(),{'reference_columns':{'gross':'GROSS AMOUNT',
            'commission':'7% COMMISSION','net_payable':'NET PAID'},
            'reference_verification':'All three final reference meanings checked'})
        comparisons=saved['rows'][0]['comparisons']
        self.assertEqual(comparisons['gross']['status'],'exact_match')
        self.assertEqual(comparisons['commission']['difference'],'+1.00')
        self.assertEqual(comparisons['commission']['status'],'material_difference')
        self.assertEqual(comparisons['net_payable']['difference'],'-0.01')
        self.assertEqual(comparisons['net_payable']['status'],'rounding_difference')
        self.assertEqual(saved['rows'][0]['net_payable'],'744.00')
        code,content,_=self.request('GET',f"/dhl-reports/expense-imports/{saved['id']}/export?format=xlsx")
        self.assertEqual(code,200)
        wb=load_workbook(io.BytesIO(content));ws=wb['Monthly Summary']
        difference_column=next(c.column for c in ws[5] if c.value=='Difference Commission (calculated minus manual)')
        self.assertEqual(ws.cell(6,difference_column).value,1)
        self.assertTrue(ws.cell(6,difference_column).number_format.startswith('+'))
        wb.close()

    def test_unapplied_migration_returns_service_unavailable(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql('DROP TABLE dhl_monthly_expense_rows CASCADE; DROP TABLE dhl_monthly_expense_imports CASCADE')
        code,data,_=self.request('GET','/dhl-reports/monthly-net-summary?month=2026-02-01')
        self.assertEqual(code,503)
        self.assertEqual(data['detail']['code'],'migration_required')

    def test_corrupt_workbook_xml_returns_validation_error(self):
        from zipfile import ZipFile, ZIP_DEFLATED
        source=io.BytesIO(fixtures.book());out=io.BytesIO()
        with ZipFile(source) as original, ZipFile(out,'w',ZIP_DEFLATED) as damaged:
            for name in original.namelist():
                damaged.writestr(name,b'<invalid' if name=='xl/workbook.xml' else original.read(name))
        self.assertEqual(self.request('POST','/dhl-reports/expense-imports/preview',out.getvalue())[0],422)

    @unittest.skipUnless((ROOT/'data/FEBRUARY NET SUMMARY 1.xlsx').exists() and (ROOT/'data/FEBRUARY 2026 TRIPS SUMMARY.xlsx').exists(), 'Exact local February files unavailable')
    def test_actual_february_preview_and_historical_flags(self):
        net=(ROOT/'data/FEBRUARY NET SUMMARY 1.xlsx').read_bytes()
        raw=(ROOT/'data/FEBRUARY 2026 TRIPS SUMMARY.xlsx').read_bytes()
        code,preview,_=self.request('POST','/dhl-reports/expense-imports/preview',net,raw=raw)
        self.assertEqual(code,200,preview)
        self.assertEqual(len(preview['rows']),32)
        self.assertFalse(preview['ready'])
        self.assertIn('optional_category_absent',[i['code'] for i in preview['issues']])
        self.assertEqual(len(preview['decisions']['historical_review']['out_of_month_records']),6)
        self.assertTrue(any(i['cell']=='D17' and i['code']=='blank_expense_zero' for row in preview['rows'] for i in row['issues']))
        self.assertTrue(all(row['comparisons']['net_payable']['status']=='unverified_reference' for row in preview['rows']))
        with self.engine.begin() as conn:
            self.assertEqual(conn.execute(text('SELECT count(*) FROM dhl_monthly_expense_imports')).scalar_one(),0)
        self.assertEqual((ROOT/'data/FEBRUARY NET SUMMARY 1.xlsx').read_bytes(),net)
        self.assertEqual((ROOT/'data/FEBRUARY 2026 TRIPS SUMMARY.xlsx').read_bytes(),raw)

    def test_historical_raw_review_does_not_change_revenue(self):
        from openpyxl import Workbook
        wb = Workbook(); ws = wb.active
        ws.append(['DATE','TRUCK','REF NO','AMOUNT','COST'])
        ws.append([datetime(2025,3,26),'KAA123B','OLD',500])
        ws.append([datetime(2026,2,10),'KAA123B','NEW',1000])
        stream=io.BytesIO();wb.save(stream);wb.close()
        saved=self.save(raw=stream.getvalue())
        self.assertEqual(len(saved['decisions']['historical_review']['out_of_month_records']),1)
        self.assertEqual(saved['rows'][0]['gross'],'1000.00')
        self.assertIn('historical_adjustment_review',[i['code'] for i in saved['review_warnings']])

    def revision(self, saved, options, mode='preview', user=7, sha=None):
        return self.request('POST', f"/dhl-reports/expense-imports/{saved['id']}/revise", options=options,
                            form_fields={'mode':mode,'expected_file_sha256':sha or saved['file_sha256']},user=user)

    def test_source_dates_cannot_be_bypassed_by_attestation_or_flags(self):
        code, draft, _ = self.request('POST','/dhl-reports/expense-imports',fixtures.book(),
            {'source_verification':'All checked'},form_fields={})
        self.assertEqual(code,201,draft)
        self.assertFalse(draft['can_confirm'])
        self.assertIn('source_dates_unreviewed',[i['code'] for i in draft['issues']])
        self.assertEqual(self.request('POST',f"/dhl-reports/expense-imports/{draft['id']}/confirm")[0],422)
        self.assertEqual(self.request('POST','/dhl-reports/expense-imports/preview',fixtures.book(),
            {'historical_review':{'ready':True},'dates_checked':True})[0],422)

    def test_wrong_year_and_wrong_month_require_explicit_audited_disposition(self):
        with self.engine.begin() as conn: raw=fixtures.raw_book(conn)
        wb=load_workbook(io.BytesIO(raw));ws=wb.active
        ws.append([datetime(2025,2,10),'KAA123B','WRONG-YEAR','Dist',10])
        ws.append([datetime(2026,1,10),'KAA123B','WRONG-MONTH','Offloading',20])
        stream=io.BytesIO();wb.save(stream);wb.close();raw=stream.getvalue()
        draft=self.save(raw=raw)
        self.assertFalse(draft['can_confirm'])
        self.assertEqual(len(draft['decisions']['historical_review']['date_issues']),2)
        self.assertNotIn('source_content_base64',draft['decisions']['historical_review'])
        self.assertEqual(self.request('POST',f"/dhl-reports/expense-imports/{draft['id']}/confirm")[0],422)
        choices={str(i['source_row']):{'action':'exclude_from_period','reason':'SYNTHETIC historical date reviewed, excluded only from this month'} for i in draft['decisions']['historical_review']['date_issues']}
        fixed=self.save(raw=raw,options={'previous_version_id':draft['id'],'reason':'Audited exclusions','date_dispositions':choices})
        self.assertTrue(fixed['can_confirm'],fixed['issues'])
        confirmed=self.request('POST',f"/dhl-reports/expense-imports/{fixed['id']}/confirm")
        self.assertEqual(confirmed[0],200,confirmed[1]);self.assertEqual(confirmed[1]['rows'][0]['gross'],'1000.00')
        with self.engine.begin() as conn:
            retained=conn.execute(text('SELECT decisions FROM dhl_monthly_expense_imports WHERE id=:id'),{'id':fixed['id']}).scalar_one()
        self.assertIn('source_content_base64',retained['historical_review'])

    def test_invalid_missing_dates_and_source_mismatch_block_confirmation(self):
        with self.engine.begin() as conn: raw=fixtures.raw_book(conn)
        wb=load_workbook(io.BytesIO(raw));ws=wb.active
        ws.append(['not a date','KAA123B','BAD','Dist',10]);ws.append([None,'KAA123B','MISSING','Dist',10])
        stream=io.BytesIO();wb.save(stream);wb.close()
        draft=self.save(raw=stream.getvalue())
        self.assertTrue({'invalid_source_date','missing_source_date'} <= {i['code'] for i in draft['issues']})
        self.assertEqual(self.request('POST',f"/dhl-reports/expense-imports/{draft['id']}/confirm")[0],422)
        self.assertEqual(self.revision(draft,{'date_dispositions':{'4':{'action':'exclude_from_period','reason':'Cannot guess'}}})[0],422)
        wb=load_workbook(io.BytesIO(raw));wb.active['E2']=999;stream=io.BytesIO();wb.save(stream);wb.close()
        mismatch=self.save(fixtures.book(110),raw=stream.getvalue())
        self.assertIn('source_manifest_mismatch',[i['code'] for i in mismatch['issues']])
        self.assertEqual(self.request('POST',f"/dhl-reports/expense-imports/{mismatch['id']}/confirm")[0],422)

    def test_revision_uses_stored_workbook_and_preserves_original_and_auth(self):
        original=self.save(fixtures.book(blank=True))
        options={'source_verification':'Reviewed','reason':'Explicit synthetic Fuel zero correction','corrections':{'B3':'0.00'}}
        for user, expected in [(None,401),(8,403),(10,401)]:
            self.assertEqual(self.revision(original,options,user=user)[0],expected)
        self.assertEqual(self.revision(original,options,sha='wrong')[0],409)
        code,preview,_=self.revision(original,options);self.assertEqual(code,200,preview)
        self.assertEqual(preview['rows'][0]['deductions']['fuel']['amount'],'0.00')
        code,saved,_=self.revision(original,options,mode='save');self.assertEqual(code,200,saved)
        self.assertEqual(saved['version'],2);self.assertEqual(saved['file_sha256'],original['file_sha256'])
        self.assertEqual(self.request('POST',f"/dhl-reports/expense-imports/{saved['id']}/confirm")[0],200)
        old=self.request('GET',f"/dhl-reports/expense-imports/{original['id']}")[1]
        self.assertEqual(old['rows'][0]['deductions']['fuel']['amount'], '0.00')
        self.assertTrue(old['can_confirm'])

    def test_verified_operating_expense_comparison_and_export(self):
        wb=load_workbook(io.BytesIO(fixtures.book()));ws=wb.active
        ws.cell(2,8,'TOTAL EXPENSES');ws.cell(3,8,200.01)
        stream=io.BytesIO();wb.save(stream);wb.close()
        saved=self.save(stream.getvalue(),{'reference_columns':{'operating_expenses':'TOTAL EXPENSES'},'reference_verification':'Synthetic final operating expense reference verified'})
        comparison=saved['rows'][0]['comparisons']['operating_expenses']
        self.assertEqual(comparison['status'],'rounding_difference');self.assertEqual(comparison['difference'],'-0.01')
        self.assertEqual(saved['rows'][0]['net_payable'],'744.00')
        for fmt in ['pdf','xlsx']:
            self.assertEqual(self.request('GET',f"/dhl-reports/expense-imports/{saved['id']}/export?format={fmt}")[0],200)


class ComparisonTests(unittest.TestCase):
    def test_exact_rounding_material_missing_and_invalid(self):
        for manual, expected in [('100.00','exact_match'),('99.995','rounding_difference'),
                                 ('99.99','rounding_difference'),('90','material_difference'),
                                 ('99.98999999999999','rounding_difference'),
                                 (None,'missing_reference'),('bad','invalid_reference')]:
            with self.subTest(manual=manual):
                self.assertEqual(compare_amount(Decimal('100.00'),manual)['status'],expected)
        self.assertEqual(compare_amount(Decimal('100.00'),'90')['difference'],'+10.00')
        self.assertEqual(compare_amount(None,'90')['status'],'calculation_unavailable')


if __name__=='__main__':
    unittest.main()
