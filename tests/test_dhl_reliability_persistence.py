"""Disposable PostgreSQL reliability, history and actual-source PDF tests."""
import io
import copy
import json
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from openpyxl import Workbook
from sqlalchemy import text,update
from sqlalchemy.exc import DBAPIError
import test_monthly_expense_api as api
import test_monthly_expense_persistence as fixture
import test_saved_monthly_files as saved
from test_dhl_reporting_reliability import net
from services import monthly_payouts as payout
from services.monthly_expense_persistence import create_draft,confirm_import,get_import,INCLUSIVE_POLICY,ValidationBlocked
from services.monthly_expense_dates import retain_source,inspect_source
from services.monthly_statement_documents import create_document,get_document
from services.monthly_expense_reports import report_view
from services.monthly_expense_parser import parse_expenses
from services.monthly_expense_models import rows
from services.monthly_reporting_scope import reporting_read_scope
from services.truck_confirmations import confirm_truck

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(fixture.URL,'Explicit disposable PostgreSQL required')
class ReliabilityPersistenceTests(unittest.TestCase):
    setUpClass=classmethod(api.ApiTests.setUpClass.__func__)
    tearDownClass=classmethod(api.ApiTests.tearDownClass.__func__)
    tearDown=api.ApiTests.tearDown
    legacy=api.ApiTests.legacy
    def setUp(self):
        saved.SavedFileTests.setUp(self)
        with self.engine.begin() as conn:
            for name in ['006_dist_surcharge_admin_policy.sql','007_component_cent_policy.sql']:
                conn.exec_driver_sql((ROOT/'migrations'/name).read_text())

    def install(self,conn):conn.exec_driver_sql((ROOT/'migrations/008_source_inclusive_reconciliation.sql').read_text())

    def test_migration_atomic_idempotent_and_legacy_pdf_bytes_unchanged(self):
        with self.engine.begin() as conn,reporting_read_scope():
            old=create_draft(conn,fixture.book(),fixture.MONTH,'legacy.xlsx',7,historical_review=retain_source(fixture.raw_book(conn),fixture.MONTH),source_verification='Synthetic verified source')
            old=confirm_import(conn,old['id'],7);pdf=create_document(conn,old['rows'][0]['id'],7)
            before=self.legacy(conn)
            definition=conn.execute(text("SELECT pg_get_functiondef('dhl_dist_admin_fee(dhl_monthly_expense_rows,jsonb)'::regprocedure)")).scalar_one()
            with self.assertRaises(DBAPIError),conn.begin_nested():
                self.install(conn);conn.exec_driver_sql('SELECT 1/0')
            self.assertEqual(conn.execute(text("SELECT pg_get_functiondef('dhl_dist_admin_fee(dhl_monthly_expense_rows,jsonb)'::regprocedure)")).scalar_one(),definition)
            self.install(conn);self.install(conn)
            self.assertEqual(self.legacy(conn),before)
            self.assertEqual(get_import(conn,old['id']),old)
            self.assertEqual(bytes(get_document(conn,pdf['id'])['pdf_content']),bytes(pdf['pdf_content']))

    def test_workbook_owner_and_continuations_persist_and_print_once(self):
        from pypdf import PdfReader
        with self.engine.begin() as conn,reporting_read_scope():
            before=self.legacy(conn)
            archive=payout.files.register(conn,fixture.raw_book(conn),fixture.MONTH,'raw.xlsx',7)
            content=net(['OWNER','Fuel','Truck Registration Number','Parking','Entry Type'],
                [['Workbook Partner Name',100,'KAA-123B',10,'primary'],['Workbook Partner Name',30,None,None,'continuation']],
                title='FEBRUARY 2026 NET SUMMARY',cover=True)
            batch=payout.synchronize(conn,fixture.MONTH,7,expected_report_id=None,expected_raw_id=archive['id'],content=content,filename='different-layout.xlsx',mappings={'Parking':'Parking'})
            row=batch['rows'][0]
            self.assertEqual(row['operating_expenses'],Decimal('140.00'))
            self.assertEqual(row['vehicle_owner_snapshot']['owner_name'],'Workbook Partner Name')
            self.assertEqual(row['vehicle_owner_snapshot']['registered_owner_name'],'Test Owner')
            self.assertEqual(row['vehicle_owner_snapshot']['owner_id'],7)
            self.assertEqual(row['cell_audit']['_expense_layout']['continuation_rows'],[4])
            confirm_truck(conn,row['id'],7,'Synthetic explicit workbook-owner and continuation review')
            pdf=create_document(conn,row['id'],7)
            content='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(bytes(pdf['pdf_content']))).pages)
            self.assertIn('Workbook Partner Name',content);self.assertIn('130.00',content)
            self.assertIn('799.80',content);self.assertEqual(self.legacy(conn),before)

    def test_provisional_source_amounts_cannot_be_confirmed_or_printed(self):
        book=Workbook();ws=book.active
        ws.append(['DATE','TRUCK','REF NO','COST','AMOUNT','SURCHARGE','AMOUNT INC SURCHARGE','5% ADMIN FEE','NET DIST COST'])
        ws.append([date(2026,2,10),'KAA123B','REF1','DIST',900.02,0,900,45,855])
        ws.append([date(2026,2,10),'KAA123B','REF1','Offloading',100,0,100,0,100])
        out=io.BytesIO();book.save(out);book.close()
        with self.engine.begin() as conn,reporting_read_scope():
            archive=payout.files.register(conn,out.getvalue(),fixture.MONTH,'material-mismatch.xlsx',7)
            batch=payout.synchronize(conn,fixture.MONTH,7,expected_report_id=None,expected_raw_id=archive['id'],content=fixture.book(),filename='net.xlsx')
            row=batch['rows'][0];view=report_view(batch)
            self.assertIsNone(row['gross']);self.assertIsNone(row['net_payable'])
            self.assertEqual(view['rows'][0]['financial_status'],'calculated_source_review')
            self.assertEqual(view['rows'][0]['provisional_financial']['gross'],'1000.00')
            self.assertEqual(view['rows'][0]['provisional_financial']['net_payable'],'702.15')
            with self.assertRaises(ValidationBlocked):confirm_truck(conn,row['id'],7,'Must not approve material error')
            with self.assertRaises(ValueError):create_document(conn,row['id'],7)

    def test_database_rejects_forged_rounding_proof_and_caps(self):
        book=Workbook();ws=book.active
        ws.append(['DATE','TRUCK','REF NO','COST','AMOUNT','SURCHARGE','AMOUNT INC SURCHARGE','5% ADMIN FEE','NET DIST COST'])
        ws.append([date(2026,2,10),'KAA123B','REF1','DIST',899.99,0,900,45,855])
        ws.append([date(2026,2,10),'KAA123B','REF1','Offloading',100,0,100,0,100])
        out=io.BytesIO();book.save(out);book.close()
        with self.engine.begin() as conn,reporting_read_scope():
            self.install(conn);archive=payout.files.register(conn,out.getvalue(),fixture.MONTH,'rounding.xlsx',7)
            batch=payout.synchronize(conn,fixture.MONTH,7,expected_report_id=None,expected_raw_id=archive['id'],content=fixture.book(),filename='net.xlsx')
            r=batch['rows'][0]
            for where,key,value in [('proof','fee_reference','0'),('proof','difference','0.02'),('snapshot','month_rounding_absolute_total','0.26')]:
                with self.assertRaises(DBAPIError),conn.begin_nested():
                    audit=copy.deepcopy(r['cell_audit']);s=audit['_dhl_transport']
                    if where=='proof':s['transactions'][0]['rounding_reconciliation'][key]=value
                    else:s[key]=value
                    conn.execute(update(rows).where(rows.c.id==r['id']).values(cell_audit=audit))
                    conn.execute(text('SELECT dhl_dist_admin_fee(r,CAST(:policy AS jsonb)) FROM dhl_monthly_expense_rows r WHERE id=:id'),{'id':r['id'],'policy':json.dumps(INCLUSIVE_POLICY)})

    def test_approved_dynamic_category_reused_next_month_without_accumulation(self):
        with self.engine.begin() as conn,reporting_read_scope():
            archive=payout.files.register(conn,fixture.raw_book(conn),fixture.MONTH,'feb.xlsx',7)
            first=payout.synchronize(conn,fixture.MONTH,7,expected_report_id=None,expected_raw_id=archive['id'],content=net(['Truck','Fuel','Parking'],[['KAA123B',10,20]],title='FEBRUARY 2026 NET SUMMARY'),filename='feb-net.xlsx',mappings={'Parking':'Parking'})
            month=date(2026,3,1)
            conn.execute(text("INSERT INTO dhl_orders VALUES(2,'MAR1','2026-03-10','KAA123B',1,500,0,500)"))
            book=Workbook();ws=book.active;ws.append(['DATE','TRUCK','REF NO','COST','AMOUNT']);ws.append([date(2026,3,10),'KAA123B','MAR1','DIST',500]);ws.append([date(2026,3,10),'KAA123B','MAR1','Offloading',0])
            out=io.BytesIO();book.save(out);book.close()
            archive=payout.files.register(conn,out.getvalue(),month,'march.xlsx',7)
            revised=payout.synchronize(conn,month,7,expected_report_id=None,expected_raw_id=archive['id'],content=net(['Parking (KES)','Truck','Fuel'],[[30,'KAA123B',20]],title='MARCH 2026 NET SUMMARY'),filename='march-net.xlsx')
            self.assertEqual(revised['rows'][0]['operating_expenses'],Decimal('50'))
            self.assertEqual(revised['rows'][0]['net_payable'],Decimal('418.50'))
            mapping=next(h for h in revised['header_mappings'] if h['original_header']=='Parking (KES)')
            self.assertEqual(mapping['approval_source'],'reused_approval')
            self.assertEqual(mapping['approved_by'],7)
            self.assertEqual(mapping['approval_import_id'],first['id'])
            self.assertEqual(get_import(conn,first['id']),first)

    @unittest.skipUnless((ROOT/'data/SEPTEMBER 2026 GROSS TOTALS (1).xlsx').exists(),'Corrected September source required')
    def test_actual_september_saved_files_source_inclusive_rounding_pdf_and_independence(self):
        from pypdf import PdfReader
        month=date(2026,9,1);raw=(ROOT/'data/SEPTEMBER 2026 GROSS TOTALS (1).xlsx').read_bytes();expenses=(ROOT/'data/SEPTEMBER 2026 NET SUMMARY.xlsx').read_bytes()
        _,manifest=inspect_source(raw,month);parsed=parse_expenses(expenses,month)
        plates=sorted({k[1] for k in manifest}|{r.plate for r in parsed.rows})
        with self.engine.begin() as conn,reporting_read_scope():
            self.install(conn)
            for i,plate in enumerate(plates,100):conn.execute(text("INSERT INTO vehicles VALUES(:id,:plate,7,'30T')"),dict(id=i,plate=plate))
            for i,(k,v) in enumerate(manifest.items(),1000):conn.execute(text('INSERT INTO dhl_orders VALUES(:id,:ref,:date,:plate,:vehicle,:dist,:off,:gross)'),dict(id=i,ref=k[2],date=k[0],plate=k[1],vehicle=100+plates.index(k[1]),dist=v[0],off=v[1],gross=sum(v)))
            before=self.legacy(conn);archive=payout.files.register(conn,raw,month,'september.xlsx',7)
            old=create_draft(conn,expenses,month,'net.xlsx',7,source_verification=payout.SYSTEM_REVIEW,historical_review=payout.files.reference(archive))
            self.assertIsNone(next(r for r in old['rows'] if r['normalized_plate']=='KAY025L')['gross'])
            _,preview=payout.state(conn,month)
            self.assertEqual(preview['status'],'preview');self.assertEqual(preview['calculation_policy'],INCLUSIVE_POLICY)
            self.assertEqual(get_import(conn,old['id']),old)
            batch=payout.synchronize(conn,month,7,expected_report_id=old['id'],expected_raw_id=archive['id'])
            self.assertEqual(sum(r['gross'] is None for r in batch['rows']),0)
            inactive=[r for r in batch['rows'] if r['revenue_status']=='verified_no_activity']
            self.assertEqual(len(inactive),12)
            self.assertEqual(sum(r['net_payable'] for r in inactive),Decimal('-26148.00'))
            self.assertEqual(batch['calculation_policy'],INCLUSIVE_POLICY)
            for plate,gross,net_value in [('KAY025L','201891.81','101630.52'),('KBM439P','352170.34','164530.81'),('KBZ339V','333727.80','126058.16'),('KCE864K','303030.02','120464.43'),('KDL090S','297953.84','91007.70')]:
                row=next(r for r in batch['rows'] if r['normalized_plate']==plate)
                self.assertEqual((row['gross'],row['net_payable']),(Decimal(gross),Decimal(net_value)))
                confirm_truck(conn,row['id'],7,'Synthetic local confirmation of evidence-backed unchanged inclusive source')
                pdf=create_document(conn,row['id'],7)
                pdf_text='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(bytes(pdf['pdf_content']))).pages)
                self.assertIn('Source rounding reconciliation',pdf_text)
                self.assertIn(f'{Decimal(gross):,.2f}',pdf_text);self.assertIn(f'{Decimal(net_value):,.2f}',pdf_text)
            self.assertEqual(self.legacy(conn),before)
            self.assertEqual(payout.files.get(conn,archive['id'])['content'],raw)
            self.assertEqual(get_import(conn,old['id']),old)
            self.assertEqual(conn.execute(text('SELECT count(*) FROM dhl_monthly_truck_confirmations')).scalar_one(),5)

    def test_source_supported_zero_activity_and_duplicate_pdf_are_safe(self):
        with self.engine.begin() as conn,reporting_read_scope():
            conn.execute(text("INSERT INTO vehicles VALUES(2,'ZERO999A',7,'30T')"))
            before=self.legacy(conn)
            archive=payout.files.register(conn,fixture.raw_book(conn),fixture.MONTH,'raw.xlsx',7)
            batch=payout.synchronize(conn,fixture.MONTH,7,expected_report_id=None,expected_raw_id=archive['id'],
                content=net(['Truck','Fuel'],[['KAA123B',20],['ZERO999A',50]],title='FEBRUARY 2026 NET SUMMARY'),filename='net.xlsx')
            zero=next(r for r in batch['rows'] if r['normalized_plate']=='ZERO999A')
            self.assertEqual((zero['gross'],zero['operating_expenses'],zero['commission'],zero['net_payable']),
                (Decimal('0'),Decimal('50'),Decimal('0'),Decimal('-50')))
            approval=confirm_truck(conn,zero['id'],7,'Synthetic zero-activity test')
            self.assertEqual(confirm_truck(conn,zero['id'],7,'Repeated click')['id'],approval['id'])
            doc=create_document(conn,zero['id'],7)
            self.assertEqual(create_document(conn,zero['id'],7)['id'],doc['id'])
            self.assertEqual(self.legacy(conn),before)

    def test_missing_source_rows_do_not_establish_zero_activity(self):
        from openpyxl import load_workbook
        with self.engine.begin() as conn,reporting_read_scope():
            conn.execute(text("INSERT INTO vehicles VALUES(2,'ZERO999A',7,'30T')"))
            raw=load_workbook(io.BytesIO(fixture.raw_book(conn)));raw.active.append([date(2026,2,10),'MISSING999','NOLEDGER','DIST',100])
            data=io.BytesIO();raw.save(data);raw.close()
            archive=payout.files.register(conn,data.getvalue(),fixture.MONTH,'incomplete.xlsx',7)
            batch=payout.synchronize(conn,fixture.MONTH,7,expected_report_id=None,expected_raw_id=archive['id'],
                content=net(['Truck','Fuel'],[['ZERO999A',50]],title='FEBRUARY 2026 NET SUMMARY'),filename='net.xlsx')
            self.assertIsNone(batch['rows'][0]['gross'])
            self.assertFalse(batch['decisions']['verified_no_activity'])


if __name__=='__main__':unittest.main()
