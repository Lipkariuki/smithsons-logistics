"""Simple facade tests; only disposable local PostgreSQL, never production."""
import io
import unittest
from unittest.mock import patch
from contextlib import nullcontext
from datetime import date
from pathlib import Path
from time import perf_counter
import json
from decimal import Decimal
from openpyxl import load_workbook
from sqlalchemy import text
import test_monthly_expense_api as api
import test_monthly_expense_persistence as fixture
import test_saved_monthly_files as saved
from services import monthly_payouts as payout
from services.monthly_expense_persistence import create_draft, get_import, VersionConflict, ValidationBlocked
from services.truck_confirmations import confirm_truck
from services.monthly_statement_documents import create_document, get_document
from routers.monthly_payouts import create_router


@unittest.skipUnless(fixture.URL, 'Explicit disposable PostgreSQL required')
class SimplePayoutTests(unittest.TestCase):
    setUpClass=classmethod(api.ApiTests.setUpClass.__func__)
    tearDownClass=classmethod(api.ApiTests.tearDownClass.__func__)
    tearDown=api.ApiTests.tearDown
    request=api.ApiTests.request
    legacy=api.ApiTests.legacy
    archive=saved.SavedFileTests.archive

    def setUp(self):
        saved.SavedFileTests.setUp(self)
        def connection():
            with self.engine.begin() as conn: yield conn
        self.app.include_router(create_router(connection,api.auth_functions(self.engine)))

    def sync(self,conn,**options):
        latest=payout.latest(conn,fixture.MONTH);raw=payout.raw_latest(conn,fixture.MONTH)
        return payout.synchronize(conn,fixture.MONTH,7,expected_report_id=latest['id'] if latest else None,
            expected_raw_id=raw['id'] if raw else None,**options)

    def test_two_originals_autosave_calculate_and_refresh_idempotently(self):
        with self.engine.begin() as conn:
            before=self.legacy(conn);self.archive(conn)
            first=self.sync(conn,content=fixture.book(),filename='original-net.xlsx')
            row=first['rows'][0]
            self.assertEqual([row[k] for k in ['gross','operating_expenses','commission','net_payable']],list(map(Decimal,['1000','200','56','744'])))
            self.assertEqual(self.sync(conn)['id'],first['id'])
            self.assertEqual(self.legacy(conn),before)
            self.assertEqual(conn.execute(text('SELECT count(*) FROM dhl_monthly_truck_confirmations')).scalar_one(),0)

    def test_get_old_draft_previews_saved_sources_without_writes(self):
        with self.engine.begin() as conn:
            old=create_draft(conn,fixture.book(),fixture.MONTH,'net.xlsx',7);self.archive(conn)
        status,body,_=self.request('GET','/dhl-reports/monthly-payouts/2026-02-01')
        self.assertEqual(status,200,body);self.assertEqual(body['report']['status'],'preview')
        self.assertEqual(body['report']['rows'][0]['gross'],'1000.00')
        with self.engine.begin() as conn:
            self.assertIsNone(get_import(conn,old['id'])['rows'][0]['gross'])
            self.assertEqual(conn.execute(text('SELECT count(*) FROM dhl_monthly_expense_imports')).scalar_one(),1)

    def test_old_alias_rejection_reopens_readonly_and_explicit_review_creates_new_version(self):
        wb=load_workbook(io.BytesIO(self.raw));wb.active['D3']='Offload';out=io.BytesIO();wb.save(out);wb.close()
        legacy_issue=dict(code='unsupported_source_charge',message='Old strict validator rejected Offload',cell=None,blocking=True)
        with self.engine.begin() as conn:
            before=self.legacy(conn);self.archive(conn,out.getvalue())
            with patch('services.monthly_expense_dates.charge_issues',return_value=[legacy_issue]):
                old=self.sync(conn,content=fixture.book(),filename='net.xlsx')
            self.assertIsNone(old['rows'][0]['gross'])
        status,body,_=self.request('GET','/dhl-reports/monthly-payouts/2026-02-01')
        self.assertEqual(status,200,body);self.assertEqual(body['report']['status'],'preview')
        self.assertEqual(body['report']['rows'][0]['gross'],'1000.00')
        with self.engine.begin() as conn:
            self.assertEqual(get_import(conn,old['id']),old)
            self.assertEqual(conn.execute(text('SELECT count(*) FROM dhl_monthly_expense_imports')).scalar_one(),1)
            self.assertEqual(conn.execute(text('SELECT count(*) FROM dhl_monthly_truck_confirmations')).scalar_one(),0)
            revised=self.sync(conn)
            self.assertEqual(revised['version'],2)
            self.assertIn('Known COST aliases revalidated',revised['decisions']['reason'])
            self.assertEqual(revised['rows'][0]['net_payable'],Decimal('744.00'))
            self.assertEqual(self.sync(conn)['id'],revised['id'])
            confirm_truck(conn,revised['rows'][0]['id'],7,'Synthetic alias review only')
            doc=create_document(conn,revised['rows'][0]['id'],7)
            self.assertEqual(bytes(get_document(conn,doc['id'])['pdf_content']),bytes(doc['pdf_content']))
            self.assertEqual(self.legacy(conn),before)

    def test_unknown_cost_stays_blocked_without_a_spurious_alias_revision(self):
        wb=load_workbook(io.BytesIO(self.raw));wb.active['D3']='Dist / Offload';out=io.BytesIO();wb.save(out);wb.close()
        with self.engine.begin() as conn:
            self.archive(conn,out.getvalue());old=self.sync(conn,content=fixture.book(),filename='net.xlsx')
            _,current=payout.state(conn,fixture.MONTH)
            self.assertEqual(current['id'],old['id'])
            self.assertIsNone(current['rows'][0]['gross'])
            with self.assertRaises(ValidationBlocked):confirm_truck(conn,current['rows'][0]['id'],7,'Cannot guess COST')

    def test_saved_blank_surcharge_rejection_refreshes_without_reupload_or_mutation(self):
        from services.dhl_revenue_policy import inspect_transport
        from openpyxl import Workbook
        book=Workbook();sheet=book.active
        sheet.append(['DATE','TRUCK','REF NO','COST','AMOUNT','SURCHARGE','AMOUNT INC SURCHARGE','5% ADMIN FEE','NET DIST COST'])
        sheet.append([date(2026,2,10),'KAA123B','REF1','DIST',900,0,900,45,855])
        sheet.append([date(2026,2,10),'KAA123B','REF1','Offloading',100,None,100,0,100])
        out=io.BytesIO();book.save(out);book.close()
        # Reproduce exactly what the previously deployed parser stored.
        def old_inspect(content,month):
            scan=inspect_transport(content,month)
            scan['transactions']=[t for t in scan['transactions'] if t['cost']!='offloading']
            scan['issues'].append(dict(code='invalid_source_amount',message='Excel row 3: DIST, surcharge and inclusive amount must be numeric; correct the source.',
                cell='P3',blocking=True,truck='KAA123B',source_row=3))
            return scan
        with self.engine.begin() as conn:
            conn.exec_driver_sql((fixture.ROOT/'migrations/006_dist_surcharge_admin_policy.sql').read_text())
            before=self.legacy(conn)
            self.archive(conn,out.getvalue())
            with patch('services.dhl_revenue_policy.inspect_transport',side_effect=old_inspect):
                old=self.sync(conn,content=fixture.book(),filename='net.xlsx')
            self.assertIsNone(old['rows'][0]['gross'])
        status,body,_=self.request('GET','/dhl-reports/monthly-payouts/2026-02-01')
        self.assertEqual(status,200,body)
        self.assertEqual(body['report']['status'],'preview')
        self.assertEqual(body['report']['rows'][0]['gross'],'1000.00')
        with self.engine.begin() as conn:
            self.assertEqual(get_import(conn,old['id']),old)
            self.assertEqual(conn.execute(text('SELECT count(*) FROM dhl_monthly_expense_imports')).scalar_one(),1)
            revised=self.sync(conn)
            self.assertEqual(revised['version'],2)
            self.assertEqual(revised['rows'][0]['net_payable'],Decimal('702.15'))
            self.assertEqual(self.sync(conn)['id'],revised['id'])
            confirm_truck(conn,revised['rows'][0]['id'],7,'Synthetic source review')
            doc=create_document(conn,revised['rows'][0]['id'],7)
            self.assertEqual(bytes(get_document(conn,doc['id'])['pdf_content']),bytes(doc['pdf_content']))
            self.assertEqual(self.legacy(conn),before)

    def test_saved_shell_fuel_classification_refreshes_without_approving_unknown_expenses(self):
        from services import monthly_expense_parser as parser
        book=load_workbook(io.BytesIO(fixture.book(extra=True)));book.active['B2']='SHELL FUEL'
        out=io.BytesIO();book.save(out);book.close()
        old_aliases={k:v for k,v in parser.ALIASES.items() if k!='shell fuel'}
        with self.engine.begin() as conn:
            self.archive(conn)
            with patch.dict(parser.ALIASES,old_aliases,clear=True):
                old=self.sync(conn,content=out.getvalue(),filename='shell-net.xlsx')
            self.assertNotIn('fuel',old['rows'][0]['deductions'])
            _,preview=payout.state(conn,fixture.MONTH)
            self.assertEqual(preview['status'],'preview')
            self.assertEqual(preview['rows'][0]['deductions']['fuel']['amount'],'100.00')
            self.assertEqual([h['original_header'] for h in preview['header_mappings'] if h['classification']=='unknown'],['Tyres'])
            revised=self.sync(conn)
            self.assertEqual(revised['version'],2)
            self.assertIsNone(revised['rows'][0]['net_payable'])
            with self.assertRaises(ValidationBlocked):confirm_truck(conn,revised['rows'][0]['id'],7,'Cannot auto-approve Tyres')
            self.assertEqual(get_import(conn,old['id']),old)
            self.assertEqual(self.sync(conn)['id'],revised['id'])

    @unittest.skipUnless(any((fixture.ROOT/'data'/n).exists() for n in ['SEPTEMBER 2026 GROSS TOTALS.xlsx','SEPTEMBER 2026 GROSS TOTALS (1).xlsx']) and
                         (fixture.ROOT/'data/SEPTEMBER 2026 NET SUMMARY.xlsx').exists(), 'Local September workbooks required')
    def test_actual_september_refresh_preserves_trailer_blocks_and_issues_only_eligible_pdf(self):
        from services import monthly_expense_parser as parser
        from services.dhl_revenue_policy import inspect_transport
        from services.monthly_expense_dates import inspect_source, charge_issues
        from services.monthly_reporting_scope import reporting_read_scope
        month=date(2026,9,1)
        raw_path=next(fixture.ROOT/'data'/n for n in ['SEPTEMBER 2026 GROSS TOTALS.xlsx','SEPTEMBER 2026 GROSS TOTALS (1).xlsx'] if (fixture.ROOT/'data'/n).exists())
        raw=raw_path.read_bytes()
        net=(fixture.ROOT/'data/SEPTEMBER 2026 NET SUMMARY.xlsx').read_bytes()
        _,manifest=inspect_source(raw,month)
        preview=parser.parse_expenses(net,month)
        plates=sorted({k[1] for k in manifest}|{r.plate for r in preview.rows})
        has_trailer=any(i['code']=='unsupported_source_charge' and 'Trailer' in i['message'] for i in charge_issues(raw,month))
        def old_inspect(content,selected_month):
            result=inspect_transport(content,selected_month)
            rejected=[t for t in result['transactions'] if t.get('interpretations')]
            result['transactions']=[t for t in result['transactions'] if not t.get('interpretations')]
            result['issues'] += [dict(code='invalid_source_amount',message='DIST, surcharge and inclusive amount must be numeric; correct the source.',
                cell=f"P{t['source_row']}",blocking=True,truck=t['plate'],source_row=t['source_row']) for t in rejected]
            return result
        with self.engine.begin() as conn:
            conn.exec_driver_sql((fixture.ROOT/'migrations/006_dist_surcharge_admin_policy.sql').read_text())
            for i,plate in enumerate(plates,100):
                conn.execute(text("INSERT INTO vehicles VALUES(:id,:plate,7,'30T')"),dict(id=i,plate=plate))
            for i,(key,amount) in enumerate(manifest.items(),1000):
                conn.execute(text('INSERT INTO dhl_orders VALUES(:id,:ref,:date,:plate,:vehicle,:dist,:off,:gross)'),
                    dict(id=i,ref=key[2],date=key[0],plate=key[1],vehicle=100+plates.index(key[1]),dist=amount[0],off=amount[1],gross=sum(amount)))
            before=self.legacy(conn)
            archive=payout.files.register(conn,raw,month,'september.xlsx',7)
            with patch.dict(parser.ALIASES,{k:v for k,v in parser.ALIASES.items() if k not in {'shell fuel','fidelity charges','reflective vests'}},clear=True), \
                 patch('services.dhl_revenue_policy.inspect_transport',side_effect=old_inspect), reporting_read_scope():
                old=payout.synchronize(conn,month,7,expected_report_id=None,expected_raw_id=archive['id'],content=net,filename='net.xlsx')
            self.assertIsNone(next(r for r in old['rows'] if r['normalized_plate']=='KAV086M')['gross'])
            with reporting_read_scope():
                _,current=payout.state(conn,month)
            self.assertEqual(current['status'],'preview')
            kav=next(r for r in current['rows'] if r['normalized_plate']=='KAV086M')
            if has_trailer:self.assertIsNone(kav['gross'])
            else:self.assertEqual(kav['gross'],Decimal('281630.35'))
            self.assertNotIn('invalid_source_amount',{i['code'] for i in kav['issues']})
            if has_trailer:self.assertTrue(any(i['code']=='unsupported_source_charge' and 'row 9:' in i['message'] for i in current['issues']))
            self.assertEqual(kav['deductions']['fuel']['amount'],'169884.00')
            self.assertEqual(get_import(conn,old['id']),old)
            with reporting_read_scope():
                revised=payout.synchronize(conn,month,7,expected_report_id=old['id'],expected_raw_id=archive['id'],
                    mappings={'FIDELITY CHARGES':'FIDELITY CHARGES','REFLECTIVE VESTS':'REFLECTIVE VESTS'})
            kav=next(r for r in revised['rows'] if r['normalized_plate']=='KAV086M')
            self.assertEqual(kav['operating_expenses'],Decimal('183544.95'))
            if has_trailer:
                with reporting_read_scope(), self.assertRaises(ValidationBlocked):
                    confirm_truck(conn,kav['id'],7,'Must not bypass Trailer review')
            eligible=next(r for r in revised['rows'] if r['net_payable'] is not None and not any(i['blocking'] for i in r['issues']))
            with reporting_read_scope():
                confirm_truck(conn,eligible['id'],7,'Isolated synthetic approval of local September workbook; not production')
                document=create_document(conn,eligible['id'],7)
            self.assertTrue(bytes(document['pdf_content']).startswith(b'%PDF'))
            self.assertEqual(bytes(get_document(conn,document['id'])['pdf_content']),bytes(document['pdf_content']))
            self.assertTrue(any(r['gross'] is None for r in revised['rows']))
            self.assertEqual(conn.execute(text('SELECT count(*) FROM dhl_monthly_truck_confirmations')).scalar_one(),1)
            self.assertEqual(get_import(conn,old['id']),old)
            self.assertEqual(self.legacy(conn),before)

    def test_replacement_preserves_pdf_and_never_accumulates_expenses(self):
        with self.engine.begin() as conn:
            self.archive(conn);first=self.sync(conn,content=fixture.book(),filename='net.xlsx')
            approval=confirm_truck(conn,first['rows'][0]['id'],7,'Synthetic independent review')
            old=create_document(conn,first['rows'][0]['id'],7)
            second=self.sync(conn,content=fixture.book(200),filename='corrected.xlsx')
            self.assertEqual(second['version'],2);self.assertEqual(second['rows'][0]['operating_expenses'],Decimal('300.00'))
            self.assertEqual(second['rows'][0]['net_payable'],Decimal('651.00'))
            self.assertEqual(bytes(get_document(conn,old['id'])['pdf_content']),bytes(old['pdf_content']))
            self.assertEqual(conn.execute(text('SELECT status FROM dhl_monthly_truck_confirmations WHERE id=:id'),{'id':approval['id']}).scalar_one(),'current')

    def test_unknown_categories_need_explicit_classification(self):
        with self.engine.begin() as conn:
            self.archive(conn);first=self.sync(conn,content=fixture.book(extra=True),filename='tyres.xlsx')
            self.assertIsNone(first['rows'][0]['net_payable'])
            with self.assertRaises(ValidationBlocked):confirm_truck(conn,first['rows'][0]['id'],7,'Must not guess category')
            revised=self.sync(conn,mappings={'Tyres':'Tyres'})
            self.assertEqual(revised['rows'][0]['operating_expenses'],Decimal('275.00'))

    def test_no_revenue_needs_explicit_no_activity_proof(self):
        with self.engine.begin() as conn:
            conn.execute(text('DELETE FROM dhl_orders'));self.raw=fixture.raw_book(conn);self.archive(conn)
            first=self.sync(conn,content=fixture.book(),filename='net.xlsx')
            self.assertIsNone(first['rows'][0]['gross'])
            second=self.sync(conn,no_activity={'KAA123B':'Synthetic dispatch log: no trips'})
            self.assertEqual(second['rows'][0]['commission'],Decimal('0.00'))
            self.assertEqual(second['rows'][0]['net_payable'],Decimal('-200.00'))

    def test_stale_upload_is_rejected_without_partial_save(self):
        with self.engine.begin() as conn:
            raw=self.archive(conn);first=self.sync(conn,content=fixture.book(),filename='net.xlsx')
            with self.assertRaises(VersionConflict):payout.synchronize(conn,fixture.MONTH,7,expected_report_id=None,expected_raw_id=raw['id'],content=fixture.book(200),filename='wrong.xlsx')
            self.assertEqual(payout.latest(conn,fixture.MONTH)['id'],first['id'])

    def test_reupload_of_older_version_warns_instead_of_claiming_replacement(self):
        with self.engine.begin() as conn:
            self.archive(conn);original=fixture.book()
            self.sync(conn,content=original,filename='net.xlsx')
            current=self.sync(conn,content=fixture.book(200),filename='corrected.xlsx')
            with self.assertRaisesRegex(VersionConflict,'earlier financial version'):
                self.sync(conn,content=original,filename='original-again.xlsx')
            self.assertEqual(payout.latest(conn,fixture.MONTH)['id'],current['id'])

    def test_source_dates_block_only_affected_truck(self):
        wb=load_workbook(io.BytesIO(self.raw));wb.active.append(['2025-02-10','OTHER999','OLD','Dist',50]);out=io.BytesIO();wb.save(out);wb.close()
        with self.engine.begin() as conn:
            self.archive(conn,out.getvalue());first=self.sync(conn,content=fixture.book(),filename='net.xlsx')
            self.assertIn('out_of_period_date',{i['code'] for i in first['issues']})
            confirm_truck(conn,first['rows'][0]['id'],7,'Synthetic this truck only')

    def test_revenue_without_expense_row_is_visible_not_fabricated_zero(self):
        with self.engine.begin() as conn:
            self.archive(conn)
            metadata,batch=payout.state(conn,fixture.MONTH)
            self.assertIsNone(batch);self.assertEqual(metadata['unmatched_trucks'][0]['gross'],Decimal('1000.00'))
            self.assertIsNone(metadata['unmatched_trucks'][0]['operating_expenses'])

    def test_month_totals_include_revenue_only_truck_without_fabricating_payout(self):
        with self.engine.begin() as conn:
            conn.execute(text("INSERT INTO dhl_orders(id,ref_no,date,truck_plate,distribution_cost,offloading_cost,total_revenue) VALUES(99,'RAWONLY','2026-02-10','RAWONLY999',200,0,200)"))
            self.raw=fixture.raw_book(conn);self.archive(conn)
            self.sync(conn,content=fixture.book(),filename='net.xlsx')
        status,body,_=self.request('GET','/dhl-reports/monthly-payouts/2026-02-01')
        self.assertEqual(status,200,body)
        self.assertEqual(body['report']['totals']['gross']['amount'],'1200.00')
        self.assertEqual(body['report']['totals']['net_payable']['missing_rows'],1)
        self.assertIsNone(body['report']['totals']['net_payable']['amount'])
        self.assertEqual(body['files']['unmatched_trucks'][0]['normalized_plate'],'RAWONLY999')

    def test_workbook_only_truck_is_visible_with_unverified_revenue(self):
        wb=load_workbook(io.BytesIO(self.raw));wb.active.append(['2026-02-10','WORKBOOK999','NOLEDGER','Dist',200]);out=io.BytesIO();wb.save(out);wb.close()
        with self.engine.begin() as conn:
            self.archive(conn,out.getvalue());self.sync(conn,content=fixture.book(),filename='net.xlsx')
            metadata,_=payout.state(conn,fixture.MONTH)
            row=next(r for r in metadata['unmatched_trucks'] if r['normalized_plate']=='WORKBOOK999')
            self.assertIsNone(row['gross']);self.assertIsNone(row['operating_expenses'])

    def test_facade_roles_and_sync_contract(self):
        with self.engine.begin() as conn:raw=self.archive(conn)
        for user,expected in [(None,401),(8,403),(9,403),(7,200)]:
            code,_,_=self.request('GET','/dhl-reports/monthly-payouts/2026-02-01',user=user)
            self.assertEqual(code,expected)
        code,body,_=self.request('POST','/dhl-reports/monthly-payouts/2026-02-01/expenses',content=fixture.book(),form_fields={'expected_raw_id':str(raw['id'])})
        self.assertEqual(code,200,body)
        code,again,_=self.request('POST','/dhl-reports/monthly-payouts/2026-02-01/sync',json_body={'expected_report_id':body['files']['latest_report_id'],'expected_raw_id':raw['id']})
        self.assertEqual(code,200,again);self.assertEqual(again['files']['latest_report_id'],body['files']['latest_report_id'])

    @unittest.skipUnless((Path(__file__).resolve().parents[1]/'data/JANUARY NET SUMMARY.xlsx').exists(), 'Actual January fixtures required')
    def test_january_month_view_reuses_reads_without_changing_any_results(self):
        from services.monthly_expense_dates import inspect_source, load_workbook
        from services.monthly_files import register
        from services.monthly_expense_parser import parse_expenses
        month=date(2026,1,1);root=Path(__file__).resolve().parents[1]/'data'
        raw=(root/'JANUARY 2026 TRIPS SUMMARY (1).xlsx').read_bytes();net=(root/'JANUARY NET SUMMARY.xlsx').read_bytes()
        _,manifest=inspect_source(raw,month)
        plates=sorted({k[1] for k in manifest}|{r.plate for r in parse_expenses(net,month).rows})
        with self.engine.begin() as conn:
            conn.execute(text('DELETE FROM dhl_orders'))
            for i,plate in enumerate(plates,100):
                conn.execute(text("INSERT INTO vehicles VALUES(:id,:plate,7,'30T')"),dict(id=i,plate=plate))
            for i,(key,amount) in enumerate(manifest.items(),1000):
                conn.execute(text('INSERT INTO dhl_orders VALUES(:id,:ref,:date,:plate,:vehicle,:dist,:off,:gross)'),
                    dict(id=i,ref=key[2],date=key[0],plate=key[1],vehicle=100+plates.index(key[1]),dist=amount[0],off=amount[1],gross=sum(amount)))
            saved=register(conn,raw,month,'january.xlsx',7)
            payout.synchronize(conn,month,7,expected_report_id=None,expected_raw_id=saved['id'],content=net,filename='net.xlsx')
            before=self.legacy(conn)
        url='/dhl-reports/monthly-payouts/2026-01-01'
        with patch('routers.monthly_payouts.reporting_read_scope',return_value=nullcontext()),patch('services.monthly_expense_dates.load_workbook',wraps=load_workbook) as opens:
            start=perf_counter();status,baseline,_=self.request('GET',url);old_seconds=perf_counter()-start;old_opens=opens.call_count
        self.assertEqual(status,200,baseline)
        with patch('services.monthly_expense_dates.load_workbook',wraps=load_workbook) as opens:
            start=perf_counter();status,optimized,_=self.request('GET',url);new_seconds=perf_counter()-start;new_opens=opens.call_count
        self.assertEqual(status,200,optimized);self.assertEqual(optimized,baseline)
        self.assertEqual(new_opens,2);self.assertGreater(old_opens,new_opens*10)
        with self.engine.begin() as conn:self.assertEqual(self.legacy(conn),before)
        # Local evidence only; never writes financial fixtures or production data.
        Path('/tmp/smithsons-month-loading-benchmark.json').write_text(json.dumps(dict(
            trucks=len(plates),source_rows=747,unoptimized_seconds=old_seconds,optimized_seconds=new_seconds,
            unoptimized_workbook_opens=old_opens,optimized_workbook_opens=new_opens,identical_response=True)))
