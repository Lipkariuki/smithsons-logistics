"""Request-local parsing reuse must never reuse validation decisions."""
from contextlib import nullcontext
from datetime import date
import unittest
from unittest.mock import patch
from services import monthly_expense_dates as dates
from services.monthly_reporting_scope import reporting_read_scope
from test_dhl_source_aliases import workbook, sources


class ReportingScopeTests(unittest.TestCase):
    def test_source_opens_twice_per_request_instead_of_twice_per_truck(self):
        month=date(2026,1,1);content=workbook(month)
        original=dates.load_workbook
        with patch.object(dates,'load_workbook',wraps=original) as opens:
            for _ in range(2):
                with reporting_read_scope():
                    for i in range(32):
                        dates.inspect_source(content,month)
                        dates.charge_issues(content,month,target_plate=f'KAA{i:03}A')
            self.assertEqual(opens.call_count,4)

    def test_mutable_results_do_not_poison_a_later_validation(self):
        month=date(2026,1,1);content=workbook(month,repeated='Offloading')
        with reporting_read_scope():
            first,_=dates.inspect_source(content,month);first['date_issues'].append({'bad':'caller mutation'})
            second,_=dates.inspect_source(content,month);self.assertEqual(second['date_issues'],[])
            review=dates.retain_source(content,month)
            self.assertNotIn('source_content_base64',dates.inspect_source(content,month)[0])
            issues=dates.charge_issues(content,month);issues[0]['blocking']=False
            self.assertTrue(dates.charge_issues(content,month)[0]['blocking'])

    def test_current_source_amounts_and_reporting_month_are_always_revalidated(self):
        month=date(2026,1,1);content=workbook(month);observed=sources(content,month)
        with reporting_read_scope():
            review=dates.retain_source(content,month)
            self.assertEqual(dates.validate_source(review,{},observed,month),[])
            observed[0]['distribution_cost']='899.99'
            self.assertIn('source_manifest_mismatch',{i['code'] for i in dates.validate_source(review,{},observed,month)})
            later=date(2027,1,1)
            self.assertIn('out_of_period_date',{i['code'] for i in dates.validate_source(dates.retain_source(content,later),{},[],later)})

    def test_scope_is_cleared_after_exceptions(self):
        month=date(2026,1,1);content=workbook(month)
        with patch.object(dates,'load_workbook',wraps=dates.load_workbook) as opens:
            with self.assertRaisesRegex(ValueError,'stop'):
                with reporting_read_scope():
                    dates.inspect_source(content,month);raise ValueError('stop')
            with reporting_read_scope():dates.inspect_source(content,month)
            self.assertEqual(opens.call_count,2)
