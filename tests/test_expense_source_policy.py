"""Workbook-only zero policy, replacements and retained historical snapshots."""
from decimal import Decimal
import io
import unittest

from openpyxl import Workbook
from sqlalchemy import text

import test_monthly_expense_persistence as fixtures
from services.monthly_expense_parser import parse_expenses
from services.monthly_expense_persistence import confirm_import, get_import, ValidationBlocked
from services.monthly_expense_models import imports
from sqlalchemy import update


def minimal(headers, values):
    wb = Workbook(); ws = wb.active
    ws.append(['FEBRUARY 2026 NET SUMMARY'])
    ws.append(['TRUCK REG/NO', *headers]); ws.append(['KAA123B', *values])
    out = io.BytesIO(); wb.save(out); wb.close()
    return out.getvalue()


class ZeroParserTests(unittest.TestCase):
    def test_absent_categories_zero_and_dynamic_not_carried(self):
        row = parse_expenses(minimal(['Fuel'], [12.345]), fixtures.MONTH).rows[0]
        self.assertEqual(sum(row.expenses.values()), Decimal('12.35'))
        self.assertNotIn('tyres', row.expenses)

    def test_blank_dynamic_cell_is_audited_zero(self):
        result = parse_expenses(minimal(['Tyres'], ['   ']), fixtures.MONTH, approved_mappings={'Tyres': 'Tyres'})
        self.assertTrue(result.ready)
        self.assertEqual(result.rows[0].expenses['tyres'], Decimal('0.00'))
        self.assertEqual(result.rows[0].source_values['B3']['interpretation'], 'blank_to_zero')

    def test_nonworkbook_override_rejected(self):
        with self.assertRaisesRegex(ValueError, 'replacement workbook'):
            parse_expenses(minimal(['Fuel'], [12]), fixtures.MONTH, corrections={'B3':'13.00'})


@unittest.skipUnless(fixtures.URL, 'Explicit disposable local PostgreSQL required')
class SourcePolicyTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.PersistenceTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.PersistenceTests.tearDownClass.__func__)
    tearDown = fixtures.PersistenceTests.tearDown
    draft = fixtures.PersistenceTests.draft
    legacy = fixtures.PersistenceTests.legacy

    def setUp(self):
        fixtures.PersistenceTests.setUp(self)
        with self.engine.begin() as conn:
            conn.exec_driver_sql((fixtures.ROOT/'migrations/003_expense_zero_policy.sql').read_text())

    def test_no_expense_columns_can_confirm_zero_deductions(self):
        with self.engine.begin() as conn:
            batch = self.draft(conn, content=minimal([], []))
            confirmed = confirm_import(conn, batch['id'], 7)
            self.assertEqual(confirmed['rows'][0]['operating_expenses'], Decimal('0.00'))
            self.assertEqual(confirmed['rows'][0]['net_payable'], Decimal('930.00'))

    def test_replacement_rebuilds_all_expenses_and_keeps_confirmed_history(self):
        with self.engine.begin() as conn:
            before = self.legacy(conn)
            first = self.draft(conn, content=fixtures.book(extra=True), approved_mappings={'Tyres':'Tyres'}, reason='Synthetic mapping')
            old = confirm_import(conn, first['id'], 7)
            second = self.draft(conn, content=minimal(['Fuel'], [None]), previous_version_id=first['id'], reason='Replacement workbook')
            new = confirm_import(conn, second['id'], 7)
            row = new['rows'][0]
            self.assertEqual(row['operating_expenses'], Decimal('0.00'))
            self.assertNotIn('tyres', row['deductions'])
            self.assertEqual(row['commission'], Decimal('70.00'))
            self.assertEqual(row['net_payable'], Decimal('930.00'))
            self.assertEqual(row['cell_audit']['B3']['interpretation'], 'blank_to_zero')
            self.assertEqual(get_import(conn, first['id'])['rows'], old['rows'])
            self.assertEqual(self.legacy(conn), before)

    def test_prechange_draft_requires_new_version(self):
        with self.engine.begin() as conn:
            batch = self.draft(conn)
            conn.execute(update(imports).where(imports.c.id==batch['id']).values(calculation_policy={'version':'monthly-expenses-v1'}))
            with self.assertRaises(ValidationBlocked):
                confirm_import(conn, batch['id'], 7)
