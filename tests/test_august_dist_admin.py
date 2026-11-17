"""Actual August workbooks and isolated policy/confirmation regression tests."""
import io
import os
from pathlib import Path
from datetime import date
from decimal import Decimal
import unittest
from unittest.mock import patch
from openpyxl import Workbook, load_workbook
from sqlalchemy import text, select, update
from sqlalchemy.exc import DBAPIError

from services.monthly_reporting_scope import reporting_read_scope
from services.dhl_revenue_policy import inspect_transport, truck_snapshot, snapshot_fee
from services.monthly_expense_dates import inspect_source, retain_source, validate_source
from services.monthly_expense_parser import parse_expenses
from services.monthly_expense_calculations import RevenueEvidence,RevenueStatus,calculate_monthly_expenses
with patch.dict(os.environ,{'APP_ENV':'test','DATABASE_URL':'postgresql+psycopg://synthetic:synthetic@127.0.0.1:1/august_no_connection'}):
    from services.dhl_import import parse_dhl_excel
import test_monthly_expense_persistence as fixture
import test_monthly_expense_api as api
import test_saved_monthly_files as saved
from services import monthly_files,monthly_payouts
from services.monthly_expense_persistence import create_draft,confirm_import,get_import,DHL_POLICY,ValidationBlocked
from services.monthly_expense_models import rows,imports
from services.truck_confirmations import confirm_truck
from services.monthly_statement_documents import create_document,get_document,render_statement
from routers.monthly_payouts import create_router

ROOT=Path(__file__).resolve().parents[1];MONTH=date(2026,8,1)
RAW=ROOT/'data/AUGUST 2026 GROSS TOTALS.xlsx';NET=ROOT/'data/AUGUST 2026 NET SUMMARY 1.xlsx'
HEADERS=['DATE','TRUCK','REF NO','COST','AMOUNT','SURCHARGE','AMOUNT INC SURCHARGE','5% ADMIN FEE','NET DIST COST']

def source(lines):
    w=Workbook();s=w.active;s.append(HEADERS)
    for r in lines:s.append([date(2026,8,1),'TEST100A',123,*r])
    out=io.BytesIO();w.save(out);w.close();return out.getvalue()

def ledger(content):
    _,groups=inspect_source(content,MONTH)
    return [dict(date=k[0],truck_plate=k[1],ref_no=k[2],distribution_cost=str(v[0]),offloading_cost=str(v[1]),total_revenue=str(sum(v))) for k,v in groups.items()]


class SourcePolicyTests(unittest.TestCase):
    def test_per_dist_rounding_surcharge_once_admin_excluded_and_offloading_exempt(self):
        raw=source([['DIST',100,20,120,6,114],['OFFLOADING',10,0,10,None,10],['Admin',-6,0,-6,None,-6]])
        scan=inspect_transport(raw,MONTH);snapshot=truck_snapshot(scan,'TEST100A',MONTH)
        self.assertEqual(snapshot['gross'],'130.00');self.assertEqual(snapshot['admin_fee'],'6.00')
        self.assertEqual(snapshot['surcharge'],'20.00')
        records,_,_=parse_dhl_excel(raw)
        self.assertEqual(sum(Decimal(str(r['total_revenue'])) for r in records),Decimal('130.00'))
        self.assertEqual(validate_source(retain_source(raw,MONTH),{},ledger(raw),MONTH),[])
        small=source([['DIST',.10,0,.10,None,None],['DIST',.10,0,.10,None,None]])
        self.assertEqual(truck_snapshot(inspect_transport(small,MONTH),'TEST100A',MONTH)['admin_fee'],'0.02')

    def test_mismatch_and_offloading_surcharge_block_without_changing_values(self):
        raw=source([['DIST',100,20,119.99,6,None],['OFFLOADING',10,1,11,None,None]])
        scan=inspect_transport(raw,MONTH)
        self.assertEqual(scan['transactions'][0]['inclusive'],'119.99')
        codes={i['code'] for i in validate_source(retain_source(raw,MONTH),{},ledger(raw),MONTH)}
        self.assertIn('inclusive_amount_mismatch',codes);self.assertIn('offloading_surcharge_review',codes)

    def test_admin_fee_after_expenses_preserves_negative_net_and_zero_commission(self):
        w=Workbook();s=w.active;s.append(['AUGUST 2026 NET SUMMARY']);s.append(['TRUCK REG.NO','Fuel']);s.append(['TEST100A',200]);out=io.BytesIO();w.save(out);w.close()
        row=parse_expenses(out.getvalue(),MONTH).rows[0]
        r=calculate_monthly_expenses(row,MONTH,RevenueEvidence('TEST100A',MONTH,RevenueStatus.DHL_RECORDS,Decimal('100'),'synthetic source',Decimal('5')))
        self.assertEqual((r.operating_expenses,r.commission,r.net_payable),(Decimal('200'),Decimal('0'),Decimal('-105')))

    @unittest.skipUnless((ROOT/'data/FEBRUARY 2026 TRIPS SUMMARY.xlsx').exists(),'Actual February source required')
    def test_actual_february_policy_and_kav_payout_are_unchanged(self):
        month=date(2026,2,1);raw=(ROOT/'data/FEBRUARY 2026 TRIPS SUMMARY.xlsx').read_bytes()
        self.assertIsNone(inspect_transport(raw,month))
        _,groups=inspect_source(raw,month)
        gross=sum((sum(values) for key,values in groups.items() if key[1]=='KAV086M'),Decimal('0.00'))
        row=next(r for r in parse_expenses((ROOT/'data/FEBRUARY NET SUMMARY 1.xlsx').read_bytes(),month).rows if r.plate=='KAV086M')
        result=calculate_monthly_expenses(row,month,RevenueEvidence('KAV086M',month,RevenueStatus.DHL_RECORDS,gross,'Actual February read-only comparison'))
        self.assertEqual((result.gross,result.operating_expenses,result.commission,result.net_payable),tuple(map(Decimal,['302109.41','152534.00','10470.28','139105.13'])))

    def test_unlabeled_numeric_expense_column_is_not_generally_ignored(self):
        w=Workbook();s=w.active;s.append(['AUGUST 2026 NET SUMMARY']);s.append([None,'TRUCK REG.NO','Fuel']);s.append([90,'TEST100A',100]);out=io.BytesIO();w.save(out);w.close()
        self.assertIn('missing_header',{i.code for i in parse_expenses(out.getvalue(),MONTH).issues})

    @unittest.skipUnless(RAW.exists() and NET.exists(),'Actual August workbooks required')
    def test_actual_august_values_and_all_unresolved_source_rows(self):
        original=RAW.read_bytes();net_original=NET.read_bytes();scan=inspect_transport(original,MONTH)
        self.assertEqual(len(scan['transactions']),647)
        mismatch=[i['source_row'] for i in scan['issues'] if i['code']=='inclusive_amount_mismatch']
        self.assertEqual(mismatch,[343,408,568,698])
        self.assertEqual([i['source_row'] for i in scan['issues'] if i['code']=='source_marked_error'],[710,711])
        parsed=parse_expenses(net_original,MONTH);self.assertTrue(parsed.ready);self.assertEqual(len(parsed.rows),32)
        self.assertEqual(sum(sum(r.expenses.values()) for r in parsed.rows),Decimal('5521182.00'))
        self.assertEqual(sum(Decimal(r['inclusive']) for r in scan['transactions']),Decimal('10400947.43'))
        self.assertEqual(sum(Decimal(r['amount'])+Decimal(r['surcharge']) for r in scan['transactions']),Decimal('10400947.47'))
        self.assertEqual(sum(Decimal(r['admin_fee']) for r in scan['transactions']),Decimal('503297.34'))
        snap=truck_snapshot(scan,'KAV086M',MONTH);self.assertEqual(snap['admin_fee'],'22768.44')
        expense=next(r for r in parsed.rows if r.plate=='KAV086M')
        result=calculate_monthly_expenses(expense,MONTH,RevenueEvidence('KAV086M',MONTH,RevenueStatus.DHL_RECORDS,Decimal(snap['gross']),'actual source comparison',Decimal(snap['admin_fee'])))
        self.assertEqual((result.gross,result.operating_expenses,result.commission,result.net_payable),tuple(map(Decimal,['471907.12','244493.42','14325.17','190320.09'])))
        self.assertEqual(RAW.read_bytes(),original);self.assertEqual(NET.read_bytes(),net_original)


@unittest.skipUnless(fixture.URL and RAW.exists() and NET.exists(),'Disposable PostgreSQL and actual August files required')
class AugustPersistenceTests(unittest.TestCase):
    setUpClass=classmethod(api.ApiTests.setUpClass.__func__)
    tearDownClass=classmethod(api.ApiTests.tearDownClass.__func__)
    tearDown=api.ApiTests.tearDown
    request=api.ApiTests.request
    legacy=api.ApiTests.legacy

    def setUp(self):
        saved.SavedFileTests.setUp(self)
        def connection():
            with self.engine.begin() as conn:yield conn
        self.app.include_router(create_router(connection,api.auth_functions(self.engine)))
        self.raw=RAW.read_bytes();self.net=NET.read_bytes()

    def prepare(self,conn):
        # Preserve a real legacy-policy PDF before extending SQL guards.
        oldraw=fixture.raw_book(conn)
        old=create_draft(conn,fixture.book(),fixture.MONTH,'legacy.xlsx',7,historical_review=retain_source(oldraw,fixture.MONTH),source_verification='Synthetic legacy source')
        old=confirm_import(conn,old['id'],7);old_doc=create_document(conn,old['rows'][0]['id'],7)
        before=self.legacy(conn)
        sql=(ROOT/'migrations/006_dist_surcharge_admin_policy.sql').read_text()
        conn.exec_driver_sql(sql);conn.exec_driver_sql(sql)  # Idempotent guard update.
        self.assertEqual(self.legacy(conn),before)
        self.assertEqual(bytes(get_document(conn,old_doc['id'])['pdf_content']),bytes(old_doc['pdf_content']))
        parsed=parse_expenses(self.net,MONTH)
        for n,row in enumerate(parsed.rows,100):
            conn.execute(text('INSERT INTO vehicles VALUES (:id,:plate,7,\'30T\')'),dict(id=n,plate=row.plate))
        records,_,_=parse_dhl_excel(self.raw)
        plates={r.plate:n for n,r in enumerate(parsed.rows,100)}
        for n,r in enumerate(records,2):
            conn.execute(text('INSERT INTO dhl_orders VALUES (:id,:ref,:date,:plate,:vehicle,:dist,:off,:gross)'),dict(id=n,ref=r['ref_no'],date=r['date'],plate=r['truck_plate'],vehicle=plates[r['truck_plate']],dist=r['distribution_cost'],off=r['offloading_cost'],gross=r['total_revenue']))
        archive=monthly_files.register(conn,self.raw,MONTH,RAW.name,7)
        batch=monthly_payouts.synchronize(conn,MONTH,7,expected_report_id=None,expected_raw_id=archive['id'],content=self.net,filename=NET.name)
        return batch,old_doc

    def test_real_saved_workbooks_confirm_eligible_truck_pdf_and_preserve_history(self):
        from pypdf import PdfReader
        with self.engine.begin() as conn, reporting_read_scope():
            batch,old_doc=self.prepare(conn);self.assertEqual(batch['calculation_policy'],DHL_POLICY)
            kav=next(r for r in batch['rows'] if r['normalized_plate']=='KAV086M')
            self.assertEqual(kav['net_payable'],Decimal('190320.09'))
            from services.monthly_expense_reports import totals,decimal_json
            summary={'policy':batch['calculation_policy'],'totals':totals(batch['rows']),
                'rows':[{**{k:r[k] for k in ['normalized_plate','gross','operating_expenses','commission_base','commission','net_payable']},
                         'admin_fee':r['cell_audit']['_dhl_transport']['admin_fee'] if r['gross'] is not None else None,
                         'issues':r['issues']} for r in batch['rows']]}
            import json
            result_path=Path('/tmp/smithsons-august-verified-calculations.json');result_path.write_text(json.dumps(decimal_json(summary),indent=2));result_path.chmod(0o600)

            for plate in ['KBZ576E','KCE864K','KDH335W','KDM009J','KDA267N']:
                row=next(r for r in batch['rows'] if r['normalized_plate']==plate)
                self.assertIsNone(row['gross']);self.assertTrue(any(i['blocking'] for i in row['issues']))
            monthly_payouts.state(conn,MONTH)
            reopened=monthly_payouts.synchronize(conn,MONTH,7,expected_report_id=batch['id'],expected_raw_id=1)
            self.assertEqual(reopened['id'],batch['id'])
            confirm_truck(conn,kav['id'],7,'Isolated August KAV source review')
            doc=create_document(conn,kav['id'],7)
            self.assertEqual(doc['renderer_version'],'smithsons-monthly-statement-v4-dist-admin')
            content='\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(bytes(doc['pdf_content']))).pages)
            for label in ['Distribution Revenue','Offloading Revenue','DIST Surcharge','Administration Fee','Total Expenses','Net Payable']:
                self.assertIn(label,content)
            for amount in ['421,816.44','16,539.00','33,551.68','471,907.12','22,768.44','244,493.42','14,325.17','190,320.09']:
                self.assertIn('KES '+amount,content)
            self.assertNotIn('DHL',content.upper())
            Path('/tmp/smithsons-august-kav-isolated.pdf').write_bytes(bytes(doc['pdf_content']))
            self.assertEqual(create_document(conn,kav['id'],7)['pdf_sha256'],doc['pdf_sha256'])
            original=bytes(doc['pdf_content'])
            w=load_workbook(io.BytesIO(self.net));w.active['D3']=229127;out=io.BytesIO();w.save(out);w.close()
            revised=monthly_payouts.synchronize(conn,MONTH,7,expected_report_id=batch['id'],expected_raw_id=1,content=out.getvalue(),filename='isolated-revision.xlsx')
            self.assertEqual(revised['version'],2)
            self.assertEqual(next(r for r in revised['rows'] if r['normalized_plate']=='KAV086M')['net_payable'],Decimal('190319.16'))
            self.assertEqual(bytes(get_document(conn,doc['id'])['pdf_content']),original)
        code,body,_=self.request('GET','/dhl-reports/monthly-payouts/2026-08-01')
        self.assertEqual(code,200,body)
        kav=next(r for r in body['report']['rows'] if r['normalized_plate']=='KAV086M')
        self.assertEqual(kav['dhl_admin_fee'],'22768.44')
        self.assertEqual(kav['revenue_breakdown']['surcharge'],'33551.68')

    def test_admin_expense_overlap_requires_review_instead_of_double_deduction(self):
        with self.engine.begin() as conn, reporting_read_scope():
            batch,_=self.prepare(conn)
            w=load_workbook(io.BytesIO(self.net));w.active['L2']='DHL ADMIN FEE'
            for n in range(3,35):w.active.cell(n,12,1)
            out=io.BytesIO();w.save(out);w.close()
            revised=create_draft(conn,out.getvalue(),MONTH,'synthetic-overlap.xlsx',7,previous_version_id=batch['id'],
                approved_mappings={'DHL ADMIN FEE':'DHL ADMIN FEE'},reason='Synthetic overlap test',
                source_verification='Synthetic source review',historical_review=batch['decisions']['historical_review'])
            kav=next(r for r in revised['rows'] if r['normalized_plate']=='KAV086M')
            self.assertIn('possible_admin_fee_overlap',{i['code'] for i in kav['issues']})
            with self.assertRaises(ValueError):confirm_truck(conn,kav['id'],7,'Must stay review-blocked')

    def test_new_policy_whole_month_confirmation_with_clean_synthetic_source(self):
        raw=source([['DIST',1000,100,1100,55,1045],['OFFLOADING',100,0,100,None,100]])
        w=Workbook();sheet=w.active;sheet.append(['AUGUST 2026 NET SUMMARY']);sheet.append(['TRUCK REG.NO','FUEL']);sheet.append(['TEST100A',200]);out=io.BytesIO();w.save(out);w.close()
        with self.engine.begin() as conn, reporting_read_scope():
            conn.exec_driver_sql((ROOT/'migrations/006_dist_surcharge_admin_policy.sql').read_text())
            conn.execute(text("INSERT INTO vehicles VALUES (2,'TEST100A',7,'30T')"))
            conn.execute(text("INSERT INTO dhl_orders VALUES (2,'123','2026-08-01','TEST100A',2,1100,100,1200)"))
            raw_record=monthly_files.register(conn,raw,MONTH,'synthetic.xlsx',7)
            batch=create_draft(conn,out.getvalue(),MONTH,'synthetic-net.xlsx',7,source_verification='Synthetic source only',historical_review=monthly_files.reference(raw_record))
            confirmed=confirm_import(conn,batch['id'],7)
            self.assertEqual(confirmed['status'],'confirmed')
            self.assertEqual(confirmed['rows'][0]['net_payable'],Decimal('878.85'))

    def test_database_rejects_admin_snapshot_tampering_and_whole_month_unresolved(self):
        with self.engine.begin() as conn, reporting_read_scope():
            batch,_=self.prepare(conn)
            bad=next(r for r in batch['rows'] if r['normalized_plate']=='KDA267N')
            with self.assertRaises(ValidationBlocked):confirm_truck(conn,bad['id'],7,'Must stay blocked')
            with self.assertRaises(ValidationBlocked):confirm_import(conn,batch['id'],7)
            kav=next(r for r in batch['rows'] if r['normalized_plate']=='KAV086M')
            audit=dict(kav['cell_audit']);audit['_dhl_transport']=dict(audit['_dhl_transport'],admin_fee='1.00')
            conn.execute(update(rows).where(rows.c.id==kav['id']).values(cell_audit=audit))
            with self.assertRaises(DBAPIError),conn.begin_nested():
                conn.execute(text('SELECT dhl_dist_admin_fee(r,CAST(:policy AS jsonb)) FROM dhl_monthly_expense_rows r WHERE r.id=:id'),{'id':kav['id'],'policy':__import__('json').dumps(DHL_POLICY)})


if __name__=='__main__':unittest.main()
