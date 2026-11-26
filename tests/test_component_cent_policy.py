"""Explicit cent-policy versions; no production data or implicit approvals."""
import copy
import io
import json
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from openpyxl import Workbook
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError
import test_monthly_expense_api as api
import test_monthly_expense_persistence as fixture
import test_saved_monthly_files as saved
from services.dhl_revenue_policy import payout_transport, truck_snapshot, snapshot_fee, COMPONENT_POLICY as TRANSPORT_POLICY
from services.monthly_expense_dates import inspect_source, retain_source, validate_source
from services.monthly_expense_persistence import create_draft, confirm_import, get_import, COMPONENT_POLICY, ValidationBlocked, VersionConflict
from services.monthly_expense_models import rows
from services import monthly_payouts as payout
from services.monthly_reporting_scope import reporting_read_scope
from services.truck_confirmations import confirm_truck
from services.monthly_statement_documents import create_document, get_document

ROOT=Path(__file__).resolve().parents[1]


def source(inclusive=900, amount=900.01, cost='DIST'):
    w=Workbook();s=w.active
    s.append(['DATE','TRUCK','REF NO','COST','AMOUNT','SURCHARGE','AMOUNT INC SURCHARGE','5% ADMIN FEE','NET DIST COST'])
    s.append([date(2026,2,10),'KAA123B','REF1',cost,amount,0,inclusive,None,None])
    s.append([date(2026,2,10),'KAA123B','REF1','Offloading',100,0,100,0,100])
    out=io.BytesIO();w.save(out);w.close();return out.getvalue()


class CentSourceTests(unittest.TestCase):
    def test_only_explicit_one_cent_dist_adjustments_use_components(self):
        for amount,original in [(100.10,100.09),(100.10,100.11)]:
            raw=source(original,amount)
            strict=payout_transport(raw,fixture.MONTH)
            self.assertTrue(strict['issues'][0]['blocking'])
            scan=payout_transport(raw,fixture.MONTH,accept_cent_differences=True)
            self.assertEqual(scan['policy'],TRANSPORT_POLICY)
            t=scan['transactions'][0]
            self.assertEqual(t['inclusive'],'100.10');self.assertEqual(t['admin_fee'],'5.01')
            self.assertEqual(t['source_inclusive'],str(original))
            self.assertFalse(next(i for i in scan['issues'] if i['code']=='source_cent_difference_calculated')['blocking'])
        for raw in [source(899.99,900.01),source(900,900.01,'Offloading')]:
            scan=payout_transport(raw,fixture.MONTH,accept_cent_differences=True)
            self.assertTrue(any(i['blocking'] for i in scan['issues']))

    def test_admin_fee_comparison_does_not_keep_pre_adjustment_warning(self):
        from openpyxl import load_workbook
        book=load_workbook(io.BytesIO(source(100.09,100.10)))
        book.active['H2']=5.01;out=io.BytesIO();book.save(out);book.close()
        scan=payout_transport(out.getvalue(),fixture.MONTH,accept_cent_differences=True)
        self.assertNotIn('admin_fee_reference_mismatch',{i['code'] for i in scan['issues']})
        self.assertEqual(scan['transactions'][0]['previous_calculated_admin_fee'],'5.00')
        self.assertIn('administration fee 5.01',scan['issues'][0]['message'])


@unittest.skipUnless(fixture.URL,'Explicit disposable local PostgreSQL required')
class CentPersistenceTests(unittest.TestCase):
    setUpClass=classmethod(api.ApiTests.setUpClass.__func__)
    tearDownClass=classmethod(api.ApiTests.tearDownClass.__func__)
    tearDown=api.ApiTests.tearDown
    legacy=api.ApiTests.legacy
    def setUp(self):saved.SavedFileTests.setUp(self)

    def prepare(self,conn):
        old=create_draft(conn,fixture.book(),fixture.MONTH,'legacy.xlsx',7,
            source_verification='Synthetic source verification',historical_review=retain_source(fixture.raw_book(conn),fixture.MONTH))
        old=confirm_import(conn,old['id'],7)
        document=create_document(conn,old['rows'][0]['id'],7)
        conn.exec_driver_sql((ROOT/'migrations/006_dist_surcharge_admin_policy.sql').read_text())
        archive=payout.files.register(conn,source(),fixture.MONTH,'cent.xlsx',7)
        rejected=payout.synchronize(conn,fixture.MONTH,7,expected_report_id=old['id'],expected_raw_id=archive['id'],content=fixture.book(),filename='net.xlsx')
        return old,document,archive,rejected

    def revise(self,conn,archive,rejected):
        return payout.synchronize(conn,fixture.MONTH,7,expected_report_id=rejected['id'],expected_raw_id=archive['id'],accept_cent_differences=True)

    def test_migration_gate_preservation_new_version_pdf_and_adjustment_history(self):
        from pypdf import PdfReader
        with self.engine.begin() as conn, reporting_read_scope():
            old,document,archive,rejected=self.prepare(conn)
            self.assertIsNone(rejected['rows'][0]['gross'])
            with self.assertRaises(VersionConflict):self.revise(conn,archive,rejected)
            before=self.legacy(conn)
            sql=(ROOT/'migrations/007_component_cent_policy.sql').read_text()
            conn.exec_driver_sql(sql);conn.exec_driver_sql(sql)
            self.assertEqual(self.legacy(conn),before)
            self.assertEqual(get_import(conn,old['id']),old)
            self.assertEqual(bytes(get_document(conn,document['id'])['pdf_content']),bytes(document['pdf_content']))
            revised=self.revise(conn,archive,rejected);r=revised['rows'][0]
            self.assertEqual(revised['calculation_policy'],COMPONENT_POLICY)
            self.assertEqual((r['gross'],r['commission'],r['net_payable']),tuple(map(Decimal,['1000.01','52.85','702.16'])))
            self.assertEqual(r['dhl_source_snapshot'][0]['total_revenue'],'1000.0')
            self.assertEqual(snapshot_fee(r),Decimal('45.00'))
            self.assertEqual(get_import(conn,rejected['id']),rejected)
            prior=conn.execute(text('SELECT id FROM dhl_monthly_truck_confirmations WHERE expense_row_id=:id'),{'id':old['rows'][0]['id']}).scalar_one()
            approval=confirm_truck(conn,r['id'],7,'Synthetic explicit cent review',expected_current_confirmation_id=prior)
            self.assertEqual(approval['validation']['financial_adjustment']['payment_processing'],False)
            new=create_document(conn,r['id'],7)
            pdf='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(bytes(new['pdf_content']))).pages)
            self.assertIn('1,000.01',pdf);self.assertIn('702.16',pdf)
            self.assertEqual(bytes(get_document(conn,document['id'])['pdf_content']),bytes(document['pdf_content']))
            self.assertEqual(self.legacy(conn),before)
            self.assertEqual(payout.synchronize(conn,fixture.MONTH,7,expected_report_id=revised['id'],expected_raw_id=archive['id'])['id'],revised['id'])

    def test_sql_guard_rejects_tampered_adjustments_and_ledger(self):
        with self.engine.begin() as conn, reporting_read_scope():
            _,_,archive,rejected=self.prepare(conn)
            conn.exec_driver_sql((ROOT/'migrations/007_component_cent_policy.sql').read_text())
            revised=self.revise(conn,archive,rejected);r=revised['rows'][0]
            for field,value in [('source_adjustment','0.02'),('source_inclusive','899.99')]:
                with self.assertRaises(DBAPIError),conn.begin_nested():
                    audit=copy.deepcopy(r['cell_audit']);audit['_dhl_transport']['transactions'][0][field]=value
                    conn.execute(update(rows).where(rows.c.id==r['id']).values(cell_audit=audit))
                    conn.execute(text('SELECT dhl_dist_admin_fee(r,CAST(:policy AS jsonb)) FROM dhl_monthly_expense_rows r WHERE id=:id'),{'id':r['id'],'policy':json.dumps(COMPONENT_POLICY)})

    def test_failed_transaction_rolls_back_both_function_changes(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql((ROOT/'migrations/006_dist_surcharge_admin_policy.sql').read_text())
            signature="'dhl_dist_admin_fee(dhl_monthly_expense_rows,jsonb)'::regprocedure"
            before=conn.execute(text('SELECT pg_get_functiondef('+signature+')')).scalar_one()
            legacy=self.legacy(conn)
            with self.assertRaises(DBAPIError),conn.begin_nested():
                conn.exec_driver_sql((ROOT/'migrations/007_component_cent_policy.sql').read_text())
                conn.exec_driver_sql('SELECT 1/0')
            self.assertEqual(conn.execute(text('SELECT pg_get_functiondef('+signature+')')).scalar_one(),before)
            self.assertFalse(conn.execute(text("SELECT to_regprocedure('dhl_component_cent_admin_fee(dhl_monthly_expense_rows,jsonb)') IS NOT NULL")).scalar_one())
            self.assertEqual(self.legacy(conn),legacy)

    def test_whole_month_confirmation_keeps_legacy_financial_amounts(self):
        with self.engine.begin() as conn,reporting_read_scope():
            old,document,archive,rejected=self.prepare(conn)
            conn.exec_driver_sql((ROOT/'migrations/007_component_cent_policy.sql').read_text())
            revised=self.revise(conn,archive,rejected)
            confirmed=confirm_import(conn,revised['id'],7)
            self.assertEqual(confirmed['status'],'confirmed')
            historical=get_import(conn,old['id'])
            self.assertEqual(historical['rows'],old['rows'])
            self.assertEqual(bytes(get_document(conn,document['id'])['pdf_content']),bytes(document['pdf_content']))

    @unittest.skipUnless((ROOT/'data/SEPTEMBER 2026 GROSS TOTALS (1).xlsx').exists(),'Corrected local September source required')
    def test_actual_september_five_affected_trucks_confirm_independently(self):
        from services.monthly_expense_parser import parse_expenses
        month=date(2026,9,1);raw=(ROOT/'data/SEPTEMBER 2026 GROSS TOTALS (1).xlsx').read_bytes()
        net=(ROOT/'data/SEPTEMBER 2026 NET SUMMARY.xlsx').read_bytes()
        _,manifest=inspect_source(raw,month);parsed=parse_expenses(net,month)
        plates=sorted({k[1] for k in manifest}|{r.plate for r in parsed.rows})
        with self.engine.begin() as conn, reporting_read_scope():
            for migration in ['006_dist_surcharge_admin_policy.sql','007_component_cent_policy.sql']:
                conn.exec_driver_sql((ROOT/'migrations'/migration).read_text())
            for i,plate in enumerate(plates,100):conn.execute(text("INSERT INTO vehicles VALUES(:id,:plate,7,'30T')"),dict(id=i,plate=plate))
            for i,(k,v) in enumerate(manifest.items(),1000):conn.execute(text('INSERT INTO dhl_orders VALUES(:id,:ref,:date,:plate,:vehicle,:dist,:off,:gross)'),
                dict(id=i,ref=k[2],date=k[0],plate=k[1],vehicle=100+plates.index(k[1]),dist=v[0],off=v[1],gross=sum(v)))
            before=self.legacy(conn);archive=payout.files.register(conn,raw,month,'september.xlsx',7)
            old=create_draft(conn,net,month,'net.xlsx',7,source_verification=payout.SYSTEM_REVIEW,historical_review=payout.files.reference(archive))
            revised=payout.synchronize(conn,month,7,expected_report_id=old['id'],expected_raw_id=archive['id'],accept_cent_differences=True)
            for plate in ['KAY025L','KBM439P','KBZ339V','KCE864K','KDL090S']:
                r=next(r for r in revised['rows'] if r['normalized_plate']==plate)
                self.assertIsNotNone(r['net_payable'])
                confirm_truck(conn,r['id'],7,'Synthetic local cent-policy review only')
                doc=create_document(conn,r['id'],7)
                self.assertEqual(bytes(get_document(conn,doc['id'])['pdf_content']),bytes(doc['pdf_content']))
            self.assertEqual(sum(r['gross'] is None for r in revised['rows']),12)
            with self.assertRaises(ValidationBlocked):confirm_import(conn,revised['id'],7)
            self.assertEqual(get_import(conn,old['id']),old)
            self.assertEqual(self.legacy(conn),before)


if __name__=='__main__':unittest.main()
