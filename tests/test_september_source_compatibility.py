"""September source compatibility without relaxing financial validation."""
import io
from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest
from openpyxl import Workbook
from services.dhl_revenue_policy import inspect_transport, truck_snapshot, snapshot_fee
from services.monthly_expense_parser import parse_expenses
from services.monthly_expense_dates import inspect_source, retain_source, validate_source

MONTH = date(2026, 9, 1)
ROOT = Path(__file__).resolve().parents[1]


def source(cost='Offloading', amount=864, surcharge=None, inclusive=864):
    book = Workbook()
    sheet = book.active
    sheet.append(['DATE', 'TRUCK', 'REF NO', 'COST', 'AMOUNT', 'SURCHARGE',
                  'AMOUNT INC SURCHARGE', '5% ADMIN FEE', 'NET DIST COST'])
    sheet.append([MONTH, 'KAV086M', 123, cost, amount, surcharge, inclusive, None, None])
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


class SeptemberCompatibilityTests(unittest.TestCase):
    def test_blank_offloading_surcharge_is_audited_and_snapshot_valid(self):
        scan = inspect_transport(source(), MONTH)
        self.assertEqual(scan['issues'], [])
        transaction = scan['transactions'][0]
        self.assertEqual(transaction['interpretations'][0]['interpretation'], 'offloading_blank_surcharge_zero')
        self.assertEqual(transaction['interpretations'][0]['original_value'], None)
        snapshot = truck_snapshot(scan, 'KAV086M', MONTH)
        self.assertEqual(snapshot['gross'], '864.00')
        self.assertEqual(snapshot_fee(dict(normalized_plate='KAV086M', gross=Decimal('864'),
                                          cell_audit={'_dhl_transport': snapshot})), Decimal('0'))

    def test_invalid_or_uncached_values_remain_blocking(self):
        for kwargs in [dict(cost='DIST'), dict(amount=None), dict(inclusive=None),
                       dict(inclusive=865), dict(surcharge='=0'), dict(surcharge='invalid')]:
            with self.subTest(kwargs=kwargs):
                scan = inspect_transport(source(**kwargs), MONTH)
                self.assertIn('invalid_source_amount', [i['code'] for i in scan['issues']])
                self.assertEqual(scan['transactions'], [])

    def test_nonzero_offloading_surcharge_remains_blocking(self):
        scan = inspect_transport(source(surcharge=1, inclusive=865), MONTH)
        self.assertIn('offloading_surcharge_review', [i['code'] for i in scan['issues']])

    def test_saved_source_verification_accepts_blank_but_still_checks_ledger(self):
        content = source()
        _, groups = inspect_source(content, MONTH)
        ledger = [dict(date=k[0], truck_plate=k[1], ref_no=k[2], distribution_cost=str(v[0]),
                       offloading_cost=str(v[1]), total_revenue=str(sum(v))) for k, v in groups.items()]
        review = retain_source(content, MONTH)
        self.assertEqual(validate_source(review, {}, ledger, MONTH), [])
        ledger[0]['offloading_cost'] = '865.00'
        self.assertTrue(validate_source(review, {}, ledger, MONTH))

    def test_shell_fuel_does_not_allow_duplicate_fuel_deductions(self):
        book = Workbook(); sheet = book.active
        sheet.append(['TRUCK REG.NO', 'Fuel', 'SHELL FUEL'])
        sheet.append(['KAV086M', 10, 20])
        output = io.BytesIO(); book.save(output); book.close()
        preview = parse_expenses(output.getvalue(), MONTH)
        self.assertIn('duplicate_category', [i.code for i in preview.issues])

    @unittest.skipUnless((ROOT/'data/SEPTEMBER 2026 GROSS TOTALS.xlsx').exists(), 'Local September fixture unavailable')
    def test_actual_september_retains_source_discrepancies(self):
        scan = inspect_transport((ROOT/'data/SEPTEMBER 2026 GROSS TOTALS.xlsx').read_bytes(), MONTH)
        self.assertNotIn('invalid_source_amount', [i['code'] for i in scan['issues']])
        self.assertEqual(sum(bool(t.get('interpretations')) for t in scan['transactions']), 252)
        self.assertEqual([i['source_row'] for i in scan['issues'] if i['code']=='inclusive_amount_mismatch'],
                         [31, 90, 94, 100, 104, 126, 165, 294, 302, 492, 494])

    @unittest.skipUnless((ROOT/'data/SEPTEMBER 2026 NET SUMMARY.xlsx').exists(), 'Local September fixture unavailable')
    def test_actual_september_expenses_preserve_headers_and_require_approval(self):
        content = (ROOT/'data/SEPTEMBER 2026 NET SUMMARY.xlsx').read_bytes()
        preview = parse_expenses(content, MONTH)
        self.assertEqual([h.original_header for h in preview.headers if h.classification=='unknown'],
                         ['FIDELITY CHARGES', 'REFLECTIVE VESTS'])
        kav = next(r for r in preview.rows if r.plate=='KAV086M')
        self.assertEqual(kav.expenses['fuel'], Decimal('169884.00'))
        self.assertEqual(sum(kav.expenses.values()), Decimal('183544.95'))
        self.assertEqual(next(h for h in preview.headers if h.category=='fuel').original_header, 'SHELL FUEL')


if __name__ == '__main__':
    unittest.main()
