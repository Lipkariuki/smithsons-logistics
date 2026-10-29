"""Strict workbook evidence tests; no production connections or approvals."""
from datetime import date
from decimal import Decimal
import io
import unittest
from openpyxl import Workbook
from services.monthly_expense_dates import retain_source, validate_source, charge_issues, inspect_source

MONTH = date(2026, 2, 1)


def workbook(extra=()):
    wb = Workbook()
    for row in [['DATE', 'TRUCK', 'REF NO', 'COST', 'AMOUNT'],
                [MONTH, 'KAA 123B', 'REF1', 'DIST', 900],
                [MONTH, 'KAA123B', 'REF1', 'Offloading', 100], *extra]:
        wb.active.append(row)
    out = io.BytesIO(); wb.save(out); wb.close()
    return out.getvalue()


def source(distribution='900.00', offloading='100.00'):
    return [dict(date=MONTH.isoformat(), truck_plate='KAA123B', ref_no='REF1',
                 distribution_cost=distribution, offloading_cost=offloading,
                 total_revenue=str(Decimal(distribution) + Decimal(offloading)))]


class RevenueIntegrityTests(unittest.TestCase):
    def test_duplicate_charges_block_even_if_ledger_also_double_counted(self):
        raw = workbook([[MONTH, 'kaa123b', 'REF1', 'dist', 900]])
        review = retain_source(raw, MONTH)
        issues = validate_source(review, {}, source('1800.00'), MONTH)
        self.assertIn('duplicate_source_row', {i['code'] for i in issues})
        self.assertNotIn('source_manifest_mismatch', {i['code'] for i in issues})
        self.assertIn('2 and 4', next(i['message'] for i in issues if i['code'] == 'duplicate_source_row'))

    def test_distinct_charge_lines_are_summed_not_silently_discarded(self):
        raw = workbook([[MONTH, 'KAA123B', 'REF1', 'DIST', 50]])
        self.assertEqual(charge_issues(raw, MONTH), [])
        self.assertEqual(validate_source(retain_source(raw, MONTH), {}, source('950.00'), MONTH), [])

    def test_substring_charge_type_cannot_be_approved_as_dist(self):
        raw = workbook([[MONTH, 'KAA123B', 'REF1', 'DIST adjustment unclear', 50]])
        self.assertIn('unsupported_source_charge', {i['code'] for i in validate_source(retain_source(raw, MONTH), {}, source('950.00'), MONTH)})

    def test_unrelated_duplicate_does_not_block_target_truck(self):
        raw = workbook([[MONTH, 'OTHER999', 'OTHER', 'DIST', 30],
                        [MONTH, 'OTHER999', 'OTHER', 'DIST', 30]])
        review = retain_source(raw, MONTH)
        self.assertIn('duplicate_source_row', {i['code'] for i in validate_source(review, {}, source(), MONTH)})
        self.assertEqual(validate_source(review, {}, source(), MONTH, target_plate='KAA123B'), [])

    def test_admin_remains_audit_only_and_review_metadata_stays_compatible(self):
        raw = workbook([[MONTH, 'KAA123B', 'REF1', 'Admin', -250]])
        review, groups = inspect_source(raw, MONTH)
        self.assertEqual(sum(groups[(MONTH.isoformat(), 'KAA123B', 'REF1')]), Decimal('1000.00'))
        self.assertEqual(set(review), {'sha256', 'sheet', 'reporting_month', 'date_issues',
                                      'out_of_month_records', 'unparsed_date_rows', 'action'})
        self.assertEqual(validate_source(retain_source(raw, MONTH), {}, source(), MONTH), [])
