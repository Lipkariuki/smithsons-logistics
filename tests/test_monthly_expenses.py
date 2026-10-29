"""Phase 1 tests: no database, production APIs, or legacy service imports.

Run: venv/bin/python -m unittest discover -s tests -p 'test_monthly_expenses.py' -v
The actual local February workbook is read only and is never copied into Git.
"""
from datetime import date
from decimal import Decimal
import io
from pathlib import Path
import unittest

from openpyxl import Workbook
from services.monthly_expense_parser import parse_expenses, money
from services.monthly_expense_calculations import (
    calculate_monthly_expenses, RevenueEvidence, RevenueStatus,
)

MONTH = date(2026, 2, 1)
HEADERS = ['TRUCK REG/NO', 'FUEL', 'BREAKAGES', 'TELEMATICS & VSS', 'GPRS',
           'NET PAID I', 'SHUNTING', 'NET PAID 2', '7% COMMISSION', 'NET PAID']
VALUES = ['KAV 086M', 100, 20, 30, 0, 999999, 50, 999999, 999999, 999999]
FIXTURE = Path(__file__).resolve().parents[1] / 'data/FEBRUARY NET SUMMARY 1.xlsx'


def workbook(headers=None, rows=None, title='FEBRUARY 2026 NET SUMMARY'):
    wb = Workbook()
    ws = wb.active
    ws.append([None, title])
    ws.append(HEADERS if headers is None else headers)
    for row in ([VALUES] if rows is None else rows):
        ws.append(row)
    stream = io.BytesIO()
    wb.save(stream)
    wb.close()
    return stream.getvalue()


def evidence(gross='1000.00', status=RevenueStatus.DHL_RECORDS):
    return RevenueEvidence('KAV086M', MONTH, status,
                           None if gross is None else Decimal(gross), 'isolated test verification')


class ParserTests(unittest.TestCase):
    def test_five_categories_and_optional_zero(self):
        preview = parse_expenses(workbook(), MONTH)
        self.assertTrue(preview.ready)
        self.assertEqual(preview.header_row, 2)
        self.assertEqual(preview.rows[0].plate, 'KAV086M')
        self.assertEqual(preview.rows[0].expenses, {
            'fuel': Decimal('100.00'), 'breakages': Decimal('20.00'),
            'telematics_vss': Decimal('30.00'), 'gprs': Decimal('0.00'),
            'shunting': Decimal('50.00'), 'kasarani_ksm_fuel': Decimal('0.00')})
        self.assertEqual([i.code for i in preview.issues], ['optional_category_absent'])

    def test_unknown_numeric_columns_never_deducted_until_approved(self):
        content = workbook(HEADERS + ['TYRES', 'Repairs'], [VALUES + [100, 50]])
        pending = parse_expenses(content, MONTH)
        self.assertFalse(pending.ready)
        self.assertNotIn('tyres', pending.rows[0].expenses)
        with self.assertRaises(ValueError):
            calculate_monthly_expenses(pending.rows[0], MONTH, evidence())
        mapping = {'tyres': 'Tyres', ' repairs ': 'Repairs'}
        for _ in range(2):  # same approved mapping reused on a later import
            approved = parse_expenses(content, MONTH, approved_mappings=mapping)
            self.assertTrue(approved.ready)
            self.assertEqual(approved.rows[0].expenses['tyres'], Decimal('100.00'))
            self.assertEqual(approved.headers[-1].original_header, 'Repairs')
            self.assertEqual(approved.headers[-1].approval_source, 'administrator')
            self.assertEqual(calculate_monthly_expenses(approved.rows[0], MONTH, evidence()).net_payable, Decimal('604.50'))

    def test_explicitly_ignored_unknown_column(self):
        result = parse_expenses(workbook(HEADERS + ['Notes'], [VALUES + ['reviewed']]), MONTH,
                                approved_mappings={'Notes': None})
        self.assertTrue(result.ready)
        self.assertEqual(result.headers[-1].classification, 'ignored')

    def test_summary_values_missing_or_changed_do_not_affect_results(self):
        first = parse_expenses(workbook(), MONTH).rows[0]
        changed = VALUES.copy()
        for i in (5, 7, 8, 9):
            changed[i] = None
        second = parse_expenses(workbook(rows=[changed]), MONTH).rows[0]
        self.assertEqual(first.expenses, second.expenses)
        self.assertEqual(calculate_monthly_expenses(first, MONTH, evidence()),
                         calculate_monthly_expenses(second, MONTH, evidence()))
        keep = [0, 1, 2, 3, 4, 6]
        absent = parse_expenses(workbook([HEADERS[i] for i in keep], [[VALUES[i] for i in keep]]), MONTH)
        self.assertEqual(absent.rows[0].expenses, first.expenses)
        for label in ('GROSS AMOUNT', 'NET PAY'):
            preview = parse_expenses(workbook(HEADERS + [label], [VALUES + [9999999]]), MONTH)
            self.assertEqual(preview.rows[0].expenses, first.expenses)

    def test_blank_needs_explicit_correction_zero_is_valid(self):
        values = VALUES.copy()
        values[3] = None
        content = workbook(rows=[values])
        pending = parse_expenses(content, MONTH)
        self.assertFalse(pending.ready)
        self.assertIsNone(pending.rows[0].expenses['telematics_vss'])
        approved = parse_expenses(content, MONTH, corrections={'D3': '0'})
        self.assertTrue(approved.ready)
        self.assertIsNone(approved.rows[0].source_values['D3']['original_value'])
        self.assertEqual(approved.rows[0].source_values['D3']['approved_correction'], '0')
        with self.assertRaises(ValueError):
            parse_expenses(content, MONTH, corrections={'J3': 0})

    def test_optional_category_when_present_is_not_forced_zero(self):
        content = workbook(HEADERS + ['KASARANI AND KSM FUEL'], [VALUES + [25]])
        preview = parse_expenses(content, MONTH)
        self.assertTrue(preview.ready)
        self.assertFalse(preview.issues)
        self.assertEqual(preview.rows[0].expenses['kasarani_ksm_fuel'], Decimal('25.00'))

    def test_duplicate_categories_block_and_never_overwrite(self):
        preview = parse_expenses(workbook(HEADERS + ['Fuel Cost'], [VALUES + [999]]), MONTH)
        self.assertFalse(preview.ready)
        self.assertIn('duplicate_category', [i.code for i in preview.issues])
        self.assertEqual(preview.rows[0].expenses['fuel'], Decimal('100.00'))
        preview = parse_expenses(workbook(HEADERS + ['Tyres', 'Repairs'], [VALUES + [1, 2]]), MONTH,
                                 approved_mappings={'Tyres': 'Maintenance', 'Repairs': 'Maintenance'})
        self.assertFalse(preview.ready)
        self.assertEqual(preview.rows[0].expenses['maintenance'], Decimal('1.00'))

    def test_builtin_classifications_cannot_be_overridden(self):
        for header in ('NET PAID I', '7% COMMISSION', 'FUEL', 'TRUCK REG/NO'):
            with self.subTest(header=header), self.assertRaises(ValueError):
                parse_expenses(workbook(), MONTH, approved_mappings={header: 'Tyres'})
        with self.assertRaises(ValueError):
            parse_expenses(workbook(HEADERS + ['X'], [VALUES + [1]]), MONTH,
                           approved_mappings={'X': 'NET PAY'})

    def test_aliases_and_duplicate_normalized_headers(self):
        headers = HEADERS.copy()
        headers[0] = ' truck reg.no '
        headers[3] = 'Telematics and VSS'
        self.assertTrue(parse_expenses(workbook(headers), MONTH).ready)
        result = parse_expenses(workbook(HEADERS + [' fuel '], [VALUES + [10]]), MONTH)
        self.assertIn('duplicate_header', [i.code for i in result.issues])

    def test_duplicate_trucks_total_and_formatted_blanks(self):
        duplicate = VALUES.copy()
        duplicate[0] = 'kav086m'
        preview = parse_expenses(workbook(rows=[VALUES, duplicate, ['TOTAL'] + [200] * 9, []]), MONTH)
        self.assertEqual(len(preview.rows), 2)
        self.assertFalse(preview.ready)
        self.assertIn('duplicate_truck', [i.code for i in preview.rows[1].issues])

    def test_formula_no_cache_blocks(self):
        values = VALUES.copy()
        values[1] = '=10+20'
        result = parse_expenses(workbook(rows=[values]), MONTH)
        self.assertFalse(result.ready)
        self.assertIn('formula_cache_missing', [i.code for i in result.rows[0].issues])

    def test_month_mismatch_and_unverified_title(self):
        self.assertFalse(parse_expenses(workbook(), date(2026, 3, 1)).ready)
        self.assertFalse(parse_expenses(workbook(title='Expense summary'), MONTH).ready)
        with self.assertRaises(ValueError):
            parse_expenses(workbook(), date(2026, 2, 2))

    def test_invalid_amounts_and_half_up(self):
        self.assertEqual(money('1,234.565'), Decimal('1234.57'))
        self.assertEqual(money(6951.070000000001), Decimal('6951.07'))
        for value in (None, True, date(2026, 2, 1), 'nan', 'inf', '1,2', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                money(value)

    @unittest.skipUnless(FIXTURE.exists(), 'Exact local February workbook not available')
    def test_actual_february_fixture_read_only(self):
        content = FIXTURE.read_bytes()
        preview = parse_expenses(content, MONTH)
        self.assertEqual(preview.sheet, 'Sheet1')
        self.assertEqual(len(preview.rows), 32)
        self.assertEqual(preview.header_row, 2)
        self.assertFalse(preview.ready)
        self.assertEqual([i.code for i in preview.issues], ['optional_category_absent'])
        self.assertEqual([(r.plate, i.cell, i.code) for r in preview.rows for i in r.issues],
                         [('KCE726U', 'D17', 'blank_expense')])
        # Confirmation is simulated explicitly; the original workbook is untouched.
        confirmed = parse_expenses(content, MONTH, corrections={'D17': '0.00'})
        self.assertTrue(confirmed.ready)
        total = sum((sum(r.expenses.values(), Decimal('0.00')) for r in confirmed.rows), Decimal('0.00'))
        self.assertEqual(total, Decimal('4684756.77'))
        self.assertEqual(FIXTURE.read_bytes(), content)


class CalculationTests(unittest.TestCase):
    def setUp(self):
        self.row = parse_expenses(workbook(), MONTH).rows[0]

    def test_correct_positive_net(self):
        result = calculate_monthly_expenses(self.row, MONTH, evidence())
        self.assertEqual(result.operating_expenses, Decimal('200.00'))
        self.assertEqual(result.commission_base, Decimal('800.00'))
        self.assertEqual(result.commission, Decimal('56.00'))
        self.assertEqual(result.net_payable, Decimal('744.00'))
        self.assertTrue(result.ready)

    def test_negative_and_zero_base_commission_is_zero(self):
        for gross, net in [('0.00', '-200.00'), ('100.00', '-100.00'), ('200.00', '0.00')]:
            result = calculate_monthly_expenses(self.row, MONTH, evidence(gross))
            self.assertEqual(result.commission, Decimal('0.00'))
            self.assertEqual(result.net_payable, Decimal(net))
            self.assertEqual('negative_net_balance_review' in result.warnings, Decimal(net) < 0)

    def test_verified_no_activity_preserves_expenses(self):
        result = calculate_monthly_expenses(self.row, MONTH, evidence('0.00', RevenueStatus.VERIFIED_NO_ACTIVITY))
        self.assertEqual(result.net_payable, Decimal('-200.00'))
        self.assertIn('no_matching_transport_revenue_verified_zero', result.warnings)
        self.assertTrue(result.ready)

    def test_missing_incomplete_unimported_never_confirmed_zero(self):
        for status in (RevenueStatus.MISSING, RevenueStatus.INCOMPLETE, RevenueStatus.UNIMPORTED):
            result = calculate_monthly_expenses(self.row, MONTH, evidence(None, status))
            self.assertIsNone(result.gross)
            self.assertIsNone(result.net_payable)
            self.assertIsNone(result.commission)
            self.assertEqual(result.operating_expenses, Decimal('200.00'))
            self.assertFalse(result.ready)

    def test_month_truck_and_evidence_must_match(self):
        for revenue in (RevenueEvidence('OTHER', MONTH, RevenueStatus.DHL_RECORDS, Decimal('0'), 'source'),
                        RevenueEvidence(self.row.plate, date(2026, 3, 1), RevenueStatus.DHL_RECORDS, Decimal('0'), 'source'),
                        RevenueEvidence(self.row.plate, MONTH, RevenueStatus.VERIFIED_NO_ACTIVITY, Decimal('0')),
                        evidence('1.00', RevenueStatus.VERIFIED_NO_ACTIVITY)):
            with self.assertRaises(ValueError):
                calculate_monthly_expenses(self.row, MONTH, revenue)

    def test_commission_half_up(self):
        result = calculate_monthly_expenses(self.row, MONTH, evidence('200.50'))
        self.assertEqual(result.commission, Decimal('0.04'))
        self.assertEqual(result.net_payable, Decimal('0.46'))


if __name__ == '__main__':
    unittest.main()
