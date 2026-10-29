"""Real PostgreSQL integration tests; refuse any nonlocal/non-test target.

Set MONTHLY_EXPENSE_TEST_URL explicitly. Every test uses a temporary schema;
application database.py/main.py are never imported and production is never queried.
"""
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from datetime import date
from decimal import Decimal
import io
import os
from pathlib import Path
import threading
import unittest
import uuid

from openpyxl import Workbook
from sqlalchemy import create_engine, text, update, delete, insert, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from services.monthly_expense_models import imports, rows
from services.monthly_expense_persistence import (create_draft, get_import, confirm_import,
    list_versions, DuplicateUpload, ValidationBlocked, SourceChanged, VersionConflict)

MONTH = date(2026, 2, 1)
ROOT = Path(__file__).resolve().parents[1]
URL = os.environ.get('MONTHLY_EXPENSE_TEST_URL')


@lru_cache(maxsize=128)
def book(fuel=100, extra=False, blank=False, plate='KAA 123B'):
    wb = Workbook()
    ws = wb.active
    ws.append([None, 'FEBRUARY 2026 NET SUMMARY'])
    ws.append(['TRUCK REG/NO', 'FUEL', 'BREAKAGES', 'TELEMATICS & VSS', 'GPRS', 'SHUNTING', 'NET PAID'] + (['Tyres'] if extra else []))
    ws.append([plate, None if blank else fuel, 20, 30, 0, 50, 999999] + ([75] if extra else []))
    stream = io.BytesIO()
    wb.save(stream)
    wb.close()
    return stream.getvalue()


def raw_book(conn):
    """Identical fixture records reuse bytes, including ZIP/creation timestamps."""
    records = tuple(tuple(row) for row in conn.execute(text('SELECT date,truck_plate,ref_no,distribution_cost,offloading_cost FROM dhl_orders ORDER BY id')))
    return _raw_book(records)


@lru_cache(maxsize=128)
def _raw_book(records):
    """Explicit synthetic source manifest matching this test's disposable records."""
    wb = Workbook(); ws = wb.active
    ws.append(['DATE','TRUCK','REF NO','COST','AMOUNT'])
    for r in records:
        ws.append([r[0],r[1],r[2],'Dist',r[3]])
        ws.append([r[0],r[1],r[2],'Offloading',r[4]])
    stream=io.BytesIO(); wb.save(stream); wb.close()
    return stream.getvalue()


@unittest.skipUnless(URL, 'Set MONTHLY_EXPENSE_TEST_URL to a disposable local PostgreSQL database')
class PersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = make_url(URL)
        if url.host not in {'localhost', '127.0.0.1', '::1'} or not (url.database or '').endswith('_test'):
            raise RuntimeError('Tests refuse nonlocal databases or names not ending in _test')
        cls.admin = create_engine(url)

    @classmethod
    def tearDownClass(cls):
        cls.admin.dispose()

    def setUp(self):
        self.schema = 'expense_test_' + uuid.uuid4().hex
        with self.admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA {self.schema}'))
        self.engine = create_engine(make_url(URL), connect_args={'options': '-c search_path=' + self.schema})
        with self.engine.begin() as conn:
            conn.exec_driver_sql('''
                CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);
                CREATE TABLE vehicles (id INTEGER PRIMARY KEY, plate_number TEXT, owner_id INTEGER, size TEXT);
                CREATE TABLE dhl_orders (id INTEGER PRIMARY KEY, ref_no TEXT, date DATE, truck_plate TEXT,
                    vehicle_id INTEGER, distribution_cost DOUBLE PRECISION, offloading_cost DOUBLE PRECISION, total_revenue DOUBLE PRECISION);
                CREATE TABLE dhl_payslips (id INTEGER PRIMARY KEY, net_pay DOUBLE PRECISION);
                CREATE TABLE dhl_payslip_expenses (id INTEGER PRIMARY KEY, payslip_id INTEGER, amount DOUBLE PRECISION);
                CREATE TABLE expenses (id INTEGER PRIMARY KEY, amount DOUBLE PRECISION);
                CREATE TABLE commissions (id INTEGER PRIMARY KEY, amount_paid DOUBLE PRECISION);
                INSERT INTO users VALUES (7, 'Test Owner');
                INSERT INTO vehicles VALUES (1, 'KAA123B', 7, '30T');
                INSERT INTO dhl_orders VALUES (1, 'REF1', '2026-02-10', 'KAA123B', 1, 900, 100, 1000);
                INSERT INTO dhl_payslips VALUES (1, 98765);
                INSERT INTO dhl_payslip_expenses VALUES (1,1,500);
                INSERT INTO expenses VALUES (1,200);
                INSERT INTO commissions VALUES (1,300);
            ''')
            conn.exec_driver_sql((ROOT / 'migrations/001_dhl_monthly_expenses.sql').read_text())

    def tearDown(self):
        self.engine.dispose()
        with self.admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA {self.schema} CASCADE'))

    def draft(self, conn, content=None, **kwargs):
        from services.monthly_expense_reconciliation import review_historical_adjustments
        kwargs.setdefault('historical_review', review_historical_adjustments(raw_book(conn), MONTH))
        return create_draft(conn, book() if content is None else content, MONTH, 'expense.xlsx', 7,
                            source_verification='Reviewed complete February DHL source', **kwargs)

    def legacy(self, conn):
        return {name: conn.execute(text(f'SELECT * FROM {name} ORDER BY id')).all() for name in (
            'users', 'vehicles', 'dhl_orders', 'dhl_payslips', 'dhl_payslip_expenses', 'expenses', 'commissions')}

    def test_draft_jsonb_precision_retrieval_and_legacy_untouched(self):
        with self.engine.begin() as conn:
            before = self.legacy(conn)
            draft = self.draft(conn, book(Decimal('100.125'), extra=True),
                               approved_mappings={'Tyres': 'Tyres'}, reason='Approved extra category')
            detail = get_import(conn, draft['id'])
            row = detail['rows'][0]
            self.assertEqual(detail['status'], 'draft')
            self.assertEqual(row['deductions']['fuel']['amount'], '100.13')
            self.assertEqual(row['deductions']['tyres']['amount'], '75.00')
            self.assertEqual(row['operating_expenses'], Decimal('275.13'))
            self.assertEqual(row['commission'], Decimal('50.74'))
            self.assertEqual(row['net_payable'], Decimal('674.13'))
            self.assertEqual(row['vehicle_owner_snapshot']['owner_name'], 'Test Owner')
            self.assertEqual(detail['assumptions'][0]['amount'], '0.00')
            confirm_import(conn, draft['id'], 7)
            self.assertEqual(self.legacy(conn), before)

    def test_duplicate_uploads_and_explicit_correction_version(self):
        with self.engine.begin() as conn:
            first = self.draft(conn)
        with self.assertRaises(DuplicateUpload), self.engine.begin() as conn:
            self.draft(conn)
        with self.engine.begin() as conn:
            second = self.draft(conn, content=book(125), reason='Corrected replacement workbook', previous_version_id=first['id'])
            self.assertEqual(second['version'], 2)
            self.assertEqual(second['rows'][0]['deductions']['fuel']['amount'], '125.00')
            self.assertNotIn('approved_correction', second['rows'][0]['cell_audit']['B3'])
            self.assertEqual(len(list_versions(conn, MONTH)), 2)

    def test_version_history_and_immutable_confirmed_content(self):
        with self.engine.begin() as conn:
            first = self.draft(conn)
            confirmed = confirm_import(conn, first['id'], 7)
            self.assertEqual(confirmed['status'], 'confirmed')
            row_id = confirmed['rows'][0]['id']
        for statement in [update(rows).where(rows.c.id == row_id).values(net_payable=0),
                          delete(rows).where(rows.c.id == row_id),
                          update(imports).where(imports.c.id == first['id']).values(original_filename='changed'),
                          delete(imports).where(imports.c.id == first['id'])]:
            with self.subTest(statement=str(statement)), self.assertRaises(DBAPIError), self.engine.begin() as conn:
                conn.execute(statement)
        with self.engine.begin() as conn:
            second = self.draft(conn, book(150), previous_version_id=first['id'], reason='Corrected workbook')
            confirm_import(conn, second['id'], 7)
            self.assertEqual([r['status'] for r in list_versions(conn, MONTH)], ['superseded', 'confirmed'])
            self.assertEqual(get_import(conn, first['id'])['rows'][0]['net_payable'], Decimal('744.00'))
        with self.assertRaises(DBAPIError), self.engine.begin() as conn:
            conn.execute(update(rows).where(rows.c.id == row_id).values(net_payable=0))

    def test_validation_blank_unknown_and_missing_revenue_block(self):
        for content, delete_source in [(book(extra=True), False), (book(), True)]:
            with self.subTest(blank=content[:4], missing=delete_source):
                with self.engine.begin() as conn:
                    if delete_source:
                        conn.execute(text('DELETE FROM dhl_orders'))
                    previous = conn.execute(select(imports.c.id).order_by(imports.c.version.desc())).scalar()
                    draft = self.draft(conn, content, previous_version_id=previous, reason='Validation case')
                with self.assertRaises(ValidationBlocked), self.engine.begin() as conn:
                    confirm_import(conn, draft['id'], 7)

    def test_zero_activity_and_negative_net_snapshot(self):
        with self.engine.begin() as conn:
            conn.execute(text('DELETE FROM dhl_orders'))
            draft = self.draft(conn, verified_no_activity={'KAA 123B': 'Dispatch register checked: no February business'})
            confirmed = confirm_import(conn, draft['id'], 7)
            row = confirmed['rows'][0]
            self.assertEqual(row['gross'], Decimal('0.00'))
            self.assertEqual(row['commission'], Decimal('0.00'))
            self.assertEqual(row['net_payable'], Decimal('-200.00'))
            self.assertIn('negative_net_balance_review', [i['code'] for i in row['issues']])

    def test_missing_data_is_never_zero(self):
        with self.engine.begin() as conn:
            conn.execute(text('DELETE FROM dhl_orders'))
            draft = self.draft(conn)
            row = draft['rows'][0]
            self.assertEqual(row['revenue_status'], 'unimported')
            self.assertIsNone(row['gross'])
            self.assertIsNone(row['net_payable'])
            self.assertEqual(row['operating_expenses'], Decimal('200.00'))

    def test_confirmed_snapshot_survives_source_replacement(self):
        with self.engine.begin() as conn:
            first = self.draft(conn)
            original = confirm_import(conn, first['id'], 7)
        with self.engine.begin() as conn:
            conn.execute(text('DELETE FROM dhl_orders'))
            conn.execute(text("INSERT INTO dhl_orders VALUES (2,'REF2','2026-02-11','KAA123B',1,2000,0,2000)"))
        with self.engine.begin() as conn:
            saved = get_import(conn, first['id'])
            self.assertEqual(saved, original)
            successor = self.draft(conn, previous_version_id=first['id'], reason='Review replacement revenue')
            self.assertEqual(successor['rows'][0]['gross'], Decimal('2000.00'))

    def test_source_change_since_draft_blocks_confirmation(self):
        with self.engine.begin() as conn:
            draft = self.draft(conn)
        with self.engine.begin() as conn:
            conn.execute(text('UPDATE dhl_orders SET total_revenue=2000, distribution_cost=1900'))
        with self.assertRaises(SourceChanged), self.engine.begin() as conn:
            confirm_import(conn, draft['id'], 7)

    def test_stored_draft_tampering_is_recomputed_and_rejected(self):
        with self.engine.begin() as conn:
            draft = self.draft(conn)
            conn.execute(update(rows).where(rows.c.import_id == draft['id']).values(net_payable=0))
        with self.assertRaises(ValidationBlocked), self.engine.begin() as conn:
            confirm_import(conn, draft['id'], 7)
        with self.assertRaises(DBAPIError), self.engine.begin() as conn:
            conn.execute(update(imports).where(imports.c.id == draft['id']).values(status='confirmed', confirmer_id=7,
                confirmed_at=func_now()))

    def test_concurrent_confirmations_have_one_winner(self):
        with self.engine.begin() as conn:
            first = self.draft(conn)
            second = self.draft(conn, book(150))
        barrier = threading.Barrier(2)
        def confirm(identifier):
            barrier.wait(timeout=10)
            try:
                with self.engine.begin() as conn:
                    confirm_import(conn, identifier, 7)
                return 'confirmed'
            except VersionConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(confirm, [first['id'], second['id']]))
        self.assertCountEqual(outcomes, ['confirmed', 'conflict'])
        with self.engine.begin() as conn:
            self.assertEqual(sum(v['status'] == 'confirmed' for v in list_versions(conn, MONTH)), 1)

    def test_rollback_does_not_supersede_history(self):
        with self.engine.begin() as conn:
            first = self.draft(conn)
            confirm_import(conn, first['id'], 7)
            second = self.draft(conn, book(150), previous_version_id=first['id'], reason='Correction')
        with self.assertRaises(RuntimeError), self.engine.begin() as conn:
            confirm_import(conn, second['id'], 7)
            raise RuntimeError('Simulated transaction failure')
        with self.engine.begin() as conn:
            self.assertEqual([v['status'] for v in list_versions(conn, MONTH)], ['confirmed', 'draft'])

    def test_source_snapshot_blocks_concurrent_legacy_replacement(self):
        with self.engine.begin() as conn:
            self.draft(conn)  # holds a SHARE lock until this transaction ends
            def replace_source():
                try:
                    with self.engine.begin() as writer:
                        writer.execute(text("SET LOCAL lock_timeout = '150ms'"))
                        writer.execute(text('DELETE FROM dhl_orders'))
                    return 'unexpected write'
                except DBAPIError:
                    return 'blocked'
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertEqual(pool.submit(replace_source).result(timeout=5), 'blocked')
            self.assertEqual(conn.execute(text('SELECT count(*) FROM dhl_orders')).scalar_one(), 1)

    def test_correction_of_invalid_draft_and_mapping_reuse(self):
        content = book(blank=True, extra=True)
        with self.engine.begin() as conn:
            first = self.draft(conn, content)
            second = self.draft(conn, content, previous_version_id=first['id'],
                corrections={'B3': '0.00'}, approved_mappings={'Tyres': 'Tyres'},
                reason='Administrator approved Tyres and confirmed blank Fuel as zero')
            confirmed = confirm_import(conn, second['id'], 7)
            self.assertEqual(confirmed['rows'][0]['deductions']['fuel']['amount'], '0.00')
            self.assertEqual(confirmed['header_mappings'][-1]['approved_by'], 7)
            self.assertEqual(confirmed['decisions']['approved_mappings'], {'Tyres': 'Tyres'})
            self.assertEqual(get_import(conn, first['id'])['status'], 'draft')

    def test_unknown_vehicle_cannot_confirm_and_no_activity_cannot_override_records(self):
        with self.engine.begin() as conn:
            unknown = self.draft(conn, book(plate='KZZ999Z'), verified_no_activity={'KZZ999Z': 'Checked'})
            conflict = self.draft(conn, verified_no_activity={'KAA123B': 'Incorrect claim'})
        for identifier in (unknown['id'], conflict['id']):
            with self.assertRaises(ValidationBlocked), self.engine.begin() as conn:
                confirm_import(conn, identifier, 7)

    def test_database_blocks_unapproved_json_amounts_and_confirmed_row_inserts(self):
        with self.engine.begin() as conn:
            first = self.draft(conn)
            confirmed = confirm_import(conn, first['id'], 7)
        copied_row = {key: value for key, value in confirmed['rows'][0].items() if key != 'id'}
        copied_row['source_row'] = 100
        with self.assertRaises(DBAPIError), self.engine.begin() as conn:
            conn.execute(insert(rows).values(**copied_row))
        with self.engine.begin() as conn:
            other = self.draft(conn, book(150))
            bad_json = dict(other['rows'][0]['deductions'])
            bad_json['fuel'] = {'amount': 150.00}  # JSON numbers are forbidden at confirmation
            conn.execute(update(rows).where(rows.c.import_id == other['id']).values(deductions=bad_json))
        with self.assertRaises(DBAPIError), self.engine.begin() as conn:
            conn.execute(update(imports).where(imports.c.id == other['id']).values(
                status='confirmed', confirmer_id=7, confirmed_at=func_now()))
        with self.assertRaises(DBAPIError), self.engine.begin() as conn:
            conn.execute(update(rows).where(rows.c.import_id == other['id']).values(gross=Decimal('NaN')))

    def test_no_implicit_source_completeness(self):
        with self.engine.begin() as conn:
            draft = create_draft(conn, book(), MONTH, 'expense.xlsx', 7)
            self.assertIsNone(draft['rows'][0]['gross'])
            self.assertEqual(draft['rows'][0]['revenue_status'], 'incomplete')
        with self.assertRaises(ValidationBlocked), self.engine.begin() as conn:
            confirm_import(conn, draft['id'], 7)


def func_now():
    from sqlalchemy import func
    return func.now()


if __name__ == '__main__':
    unittest.main()
