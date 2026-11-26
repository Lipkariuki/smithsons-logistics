"""Performance contracts with real PostgreSQL snapshots; no production writes."""
import io,unittest
from unittest.mock import patch
from decimal import Decimal
from sqlalchemy import text,event
import test_monthly_expense_api as api
import test_monthly_expense_persistence as fixture
import test_dhl_reliability_persistence as reliability
from routers.monthly_payouts import create_router
from services import monthly_payouts as payouts
from services.monthly_statement_documents import create_document,get_document
from services.truck_confirmations import confirm_truck
from services.dhl_performance import install

@unittest.skipUnless(fixture.URL,'Explicit disposable PostgreSQL required')
class PerformanceTests(reliability.ReliabilityPersistenceTests):
    # Inherit setup only, not the actual-source suite a second time.
    def setUp(self):
        super().setUp()
        with self.engine.begin() as c:
            self.install(c)
            archive=payouts.files.register(c,fixture.raw_book(c),fixture.MONTH,'raw.xlsx',7)
            self.batch=payouts.synchronize(c,fixture.MONTH,7,expected_report_id=None,expected_raw_id=archive['id'],content=fixture.book(),filename='net.xlsx')
        def connection():
            with self.engine.begin() as c:yield c
        self.app.include_router(create_router(connection,api.auth_functions(self.engine)))
        install(self.app,self.engine)
    request=api.ApiTests.request

    def test_overview_is_small_and_does_not_open_workbooks(self):
        with patch('services.monthly_expense_parser.load_workbook',side_effect=AssertionError('Unexpected workbook open')),patch('services.monthly_expense_dates.load_workbook',side_effect=AssertionError('Unexpected workbook open')):
            status,body,headers=self.request('GET','/dhl-reports/monthly-payouts/2026-02-01/overview')
        self.assertEqual(status,200,body);r=body['report']['rows'][0]
        self.assertEqual(r['net_payable'],'744.00');self.assertNotIn('deductions',r);self.assertNotIn('cell_audit',r)
        self.assertNotIn('source_content',body['report']);self.assertNotIn('dhl_source_snapshot',r)
        self.assertIn('x-request-id',headers)

    def test_detail_revalidates_and_has_itemized_values(self):
        status,body,_=self.request('GET','/dhl-reports/monthly-payouts/2026-02-01/trucks/KAA123B')
        self.assertEqual(status,200,body);self.assertTrue(body['row']['truck_confirmation']['can_confirm'])
        self.assertEqual(body['row']['deductions']['fuel']['amount'],'100.00')
        self.assertEqual(body['row']['net_payable'],'744.00')

    def test_changed_source_invalidates_overview_and_blocks_confirmation(self):
        with self.engine.begin() as c:c.execute(text('UPDATE dhl_orders SET distribution_cost=1900,total_revenue=2000'))
        status,body,_=self.request('GET','/dhl-reports/monthly-payouts/2026-02-01/overview')
        self.assertEqual(status,200,body);self.assertIsNone(body['report']['rows'][0]['gross'])
        status,detail,_=self.request('GET','/dhl-reports/monthly-payouts/2026-02-01/trucks/KAA123B')
        self.assertEqual(status,200,detail);self.assertFalse(detail['row']['truck_confirmation']['can_confirm'])

    def test_existing_pdf_is_one_query_without_source_reads_or_month_lock(self):
        with self.engine.begin() as c:
            r=self.batch['rows'][0];confirm_truck(c,r['id'],7,'Synthetic performance test')
            first=create_document(c,r['id'],7);calls=[]
            def observe(*args):calls.append(str(args[2]))
            event.listen(self.engine,'before_cursor_execute',observe)
            try:
                with patch('services.monthly_expense_parser.load_workbook',side_effect=AssertionError('Unexpected workbook read')):
                    again=create_document(c,r['id'],7)
            finally:event.remove(self.engine,'before_cursor_execute',observe)
            self.assertEqual(len(calls),1);self.assertNotIn('FOR UPDATE',calls[0])
            self.assertEqual(bytes(first['pdf_content']),bytes(again['pdf_content']))
        status,content,headers=self.request('GET',f"/dhl-reports/monthly-statement-documents/{first['id']}/pdf")
        self.assertEqual(status,200);h=headers
        self.assertEqual(int(h['content-length']),len(content));self.assertIn('application/pdf',h['content-type'])

    def test_overview_and_detail_remain_admin_only(self):
        for path in ['/overview','/trucks/KAA123B']:
            for user,expected in [(None,401),(8,403),(9,403),(7,200)]:
                with self.subTest(path=path,user=user):self.assertEqual(self.request('GET','/dhl-reports/monthly-payouts/2026-02-01'+path,user=user)[0],expected)

# Do not duplicate inherited tests when unittest discovers this class.
for _name in dir(reliability.ReliabilityPersistenceTests):
    if _name.startswith('test_') and _name not in PerformanceTests.__dict__:setattr(PerformanceTests,_name,None)

if __name__=='__main__':unittest.main()
