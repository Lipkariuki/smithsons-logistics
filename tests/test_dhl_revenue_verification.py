"""Actual workbook/function regression, isolated in a network-denying subprocess.
No production database module is imported. SQLite verifies arithmetic/query paths,
not PostgreSQL lock behavior (covered separately by existing persistence tests).
"""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from decimal import Decimal
ROOT=Path(__file__).resolve().parents[1]

class DHLRevenueVerificationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if not (ROOT/'data/FEBRUARY 2026 TRIPS SUMMARY.xlsx').is_file():
   raise unittest.SkipTest('Actual February workbook required; older fixtures are prohibited')
  process=subprocess.run([sys.executable,str(ROOT/'scripts/verify_dhl_revenue.py'),'--json'],cwd=ROOT,capture_output=True,text=True,check=True)
  cls.result=json.loads(process.stdout)
 def test_actual_february_dist_offloading_and_gross(self):
  self.assertEqual(self.result['totals']['dist'],'9560700.63')
  self.assertEqual(self.result['totals']['offloading'],'297461.00')
  self.assertEqual(self.result['totals']['gross'],'9858161.63')
  for row in self.result['rows']:
   self.assertEqual(Decimal(row['gross']),Decimal(row['dist'])+Decimal(row['offloading']))
 def test_existing_reporting_reconciliation_payslip_and_new_source_agree_per_truck(self):
  self.assertEqual(self.result['nonzero_cent_differences'],[])
  self.assertEqual(self.result['truck_count'],25)
  for key in ['importer_gross','report_gross','reconciliation_gross','payslip_gross','monthly_expense_gross']:
   self.assertEqual(self.result['totals'][key],self.result['totals']['gross'])
 def test_admin_is_separate_audit_not_gross_deduction(self):
  self.assertEqual(len(self.result['admin_rows']),26)
  self.assertEqual(self.result['totals']['admin_audit_only'],'-475891.06')
  fixture=self.result['synthetic'][0]
  self.assertEqual(fixture['distribution_cost'],150)
  self.assertEqual(fixture['offloading_cost'],25)
  self.assertEqual(fixture['total_revenue'],175)
  # AMOUNT, not deliberately contradictory RATE or QTY, supplies these charges.
 def test_admin_only_record_is_zero_gross_not_negative_and_numeric_zero_ref_is_valid(self):
  self.assertEqual(self.result['synthetic_admin_only'][0]['total_revenue'],0)
  actual=next(row for row in self.result['rows'] if row['truck']=='KDK766A')
  self.assertEqual(actual['gross'],'0.00')
  self.assertEqual(actual['monthly_expense_gross'],'0.00')
  self.assertEqual(actual['admin_rows'],1)
  actual_source=next(row for row in self.result['admin_rows'] if row['truck']=='KDK766A')
  self.assertEqual(actual_source['reference'],'0')
 def test_historical_rows_excluded_by_month_and_year(self):
  self.assertEqual([r['excel_row'] for r in self.result['historical']],[850,851,852,853,854,855])
  self.assertEqual(self.result['month_source_rows'],848)
  self.assertIn('multiple months',self.result['full_original_import_error'])
 def test_charge_headers_do_not_automatically_become_operating_expenses(self):
  for header in ['DIST','Offloading','Admin']:
   self.assertEqual(self.result['unknown_headers'][header],'unknown')
  self.assertEqual(self.result['unknown_deductions'],{'fuel':'100.00','kasarani_ksm_fuel':'0.00'})
  self.assertEqual(self.result['ignored_deductions'],self.result['unknown_deductions'])
 def test_positive_after_expense_commission_and_no_double_deduction(self):
  self.assertEqual(self.result['synthetic_calculation'],dict(gross='1000.00',operating_expenses='100.00',commission_base='900.00',commission='63.00',net_payable='837.00'))

if __name__=='__main__':unittest.main()
