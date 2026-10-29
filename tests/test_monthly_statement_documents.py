"""Real disposable PostgreSQL tests; never imports production database/main."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import hashlib
import io
import unittest

from pypdf import PdfReader
from sqlalchemy import text, update, select
from sqlalchemy.exc import DBAPIError

import test_monthly_expense_persistence as fixtures
import test_monthly_expense_api as api_fixtures
from routers.monthly_statement_documents import create_router
from services.monthly_expense_persistence import confirm_import
from services.monthly_expense_models import rows
from services.monthly_statement_documents import create_document, get_document, documents


@unittest.skipUnless(fixtures.URL, 'Explicit local disposable PostgreSQL URL required')
class StatementTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.PersistenceTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.PersistenceTests.tearDownClass.__func__)
    tearDown = fixtures.PersistenceTests.tearDown
    draft = fixtures.PersistenceTests.draft
    legacy = fixtures.PersistenceTests.legacy

    def setUp(self):
        fixtures.PersistenceTests.setUp(self)
        with self.engine.begin() as conn:
            conn.exec_driver_sql((fixtures.ROOT / 'migrations/002_monthly_statement_documents.sql').read_text())

    def confirmed(self, conn, **kwargs):
        batch = self.draft(conn, **kwargs)
        return confirm_import(conn, batch['id'], 7)

    def test_snapshot_pdf_idempotency_branding_and_legacy_preservation(self):
        with self.engine.begin() as conn:
            before = self.legacy(conn)
            batch = self.confirmed(conn)
            row = batch['rows'][0]
            doc = create_document(conn, row['id'], 7)
            again = create_document(conn, row['id'], 7)
            self.assertEqual(doc, again)
            self.assertEqual(self.legacy(conn), before)
            self.assertEqual(hashlib.sha256(bytes(doc['pdf_content'])).hexdigest(), doc['pdf_sha256'])
            reader = PdfReader(io.BytesIO(bytes(doc['pdf_content'])))
            content = '\n'.join(p.extract_text() for p in reader.pages)
            self.assertIn('SMITHSONS LOGISTICS', content)
            self.assertIn('KES 744.00', content)
            self.assertIn('KES 56.00', content)
            self.assertNotIn('DHL', content.upper() + str(reader.metadata).upper())
            self.assertIn('Confirmed source version: 1', content)

    def test_draft_and_missing_source_blocked(self):
        with self.engine.begin() as conn:
            batch = self.draft(conn)
            with self.assertRaises(ValueError):
                create_document(conn, batch['rows'][0]['id'], 7)

    def test_database_update_delete_and_draft_insert_blocked(self):
        with self.engine.begin() as conn:
            batch = self.confirmed(conn)
            doc = create_document(conn, batch['rows'][0]['id'], 7)
        for sql in ('UPDATE monthly_statement_documents SET generated_by=8',
                    'DELETE FROM monthly_statement_documents',
                    'TRUNCATE monthly_statement_documents'):
            with self.assertRaises(DBAPIError), self.engine.begin() as conn:
                conn.execute(text(sql))
        with self.engine.begin() as conn:
            self.assertEqual(get_document(conn, doc['id'])['pdf_sha256'], doc['pdf_sha256'])

    def test_corrections_create_new_document_and_preserve_old_bytes(self):
        with self.engine.begin() as conn:
            first = self.confirmed(conn)
            old = create_document(conn, first['rows'][0]['id'], 7)
            second = self.confirmed(conn, content=fixtures.book(200), previous_version_id=first['id'], reason='Synthetic correction')
            new = create_document(conn, second['rows'][0]['id'], 7)
            self.assertNotEqual(new['id'], old['id'])
            self.assertEqual(new['previous_document_id'], old['id'])
            self.assertEqual(get_document(conn, old['id'])['pdf_content'], old['pdf_content'])
            self.assertEqual(create_document(conn, first['rows'][0]['id'], 7)['id'], old['id'])
            # Replacing live revenue cannot alter either statement.
            conn.execute(text('UPDATE dhl_orders SET total_revenue=999999'))
            self.assertEqual(get_document(conn, new['id'])['pdf_content'], new['pdf_content'])

    def test_negative_balance_has_zero_commission(self):
        with self.engine.begin() as conn:
            batch = self.confirmed(conn, content=fixtures.book(2000))
            row = batch['rows'][0]
            self.assertEqual(row['commission'], Decimal('0.00'))
            doc = create_document(conn, row['id'], 7)
            content = PdfReader(io.BytesIO(bytes(doc['pdf_content']))).pages[0].extract_text()
            self.assertIn('KES -1,100.00', content)
            self.assertIn('Negative balance retained', content)

    def test_verified_no_activity_retains_expenses_and_zero_commission(self):
        with self.engine.begin() as conn:
            conn.execute(text('DELETE FROM dhl_orders'))
            batch = self.confirmed(conn, verified_no_activity={'KAA123B': 'Synthetic dispatch confirmed no activity'})
            row = batch['rows'][0]
            self.assertEqual(row['gross'], Decimal('0.00'))
            self.assertEqual(row['net_payable'], Decimal('-200.00'))
            doc = create_document(conn, row['id'], 7)
            content = PdfReader(io.BytesIO(bytes(doc['pdf_content']))).pages[0].extract_text()
            self.assertIn('KES -200.00', content)

    def test_concurrent_generation_returns_same_document(self):
        with self.engine.begin() as conn:
            row_id = self.confirmed(conn)['rows'][0]['id']
        def generate(_):
            with self.engine.begin() as conn:
                return create_document(conn, row_id, 7)['id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(generate, range(2)))
        self.assertEqual(ids[0], ids[1])

    def test_selected_historical_confirmed_version_can_generate_without_recalculation(self):
        with self.engine.begin() as conn:
            first = self.confirmed(conn)
            self.confirmed(conn, content=fixtures.book(200), previous_version_id=first['id'], reason='Synthetic replacement')
            old = create_document(conn, first['rows'][0]['id'], 7)
            content = PdfReader(io.BytesIO(bytes(old['pdf_content']))).pages[0].extract_text()
            self.assertIn('KES 744.00', content)
            self.assertIn('Confirmed source version: 1', content)

    def test_atomic_migration_failure_rolls_back(self):
        with self.engine.begin() as conn:
            conn.execute(text('CREATE SCHEMA statement_rollback'))
        try:
            with self.assertRaises(DBAPIError), self.engine.begin() as conn:
                conn.execute(text('SET LOCAL search_path = statement_rollback, ' + self.schema))
                conn.exec_driver_sql((fixtures.ROOT / 'migrations/002_monthly_statement_documents.sql').read_text())
                conn.execute(text('SELECT 1/0'))
            with self.engine.begin() as conn:
                self.assertIsNone(conn.execute(text("SELECT to_regclass('statement_rollback.monthly_statement_documents')")).scalar())
        finally:
            with self.engine.begin() as conn:
                conn.execute(text('DROP SCHEMA statement_rollback CASCADE'))


@unittest.skipUnless(fixtures.URL, 'Explicit local disposable PostgreSQL URL required')
class StatementApiTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.PersistenceTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.PersistenceTests.tearDownClass.__func__)
    tearDown = fixtures.PersistenceTests.tearDown
    request = api_fixtures.ApiTests.request
    save = api_fixtures.ApiTests.save

    def setUp(self):
        api_fixtures.ApiTests.setUp(self)
        with self.engine.begin() as conn:
            conn.exec_driver_sql((fixtures.ROOT / 'migrations/002_monthly_statement_documents.sql').read_text())
        def connection():
            with self.engine.begin() as conn:
                yield conn
        self.app.include_router(create_router(connection, api_fixtures.auth_functions(self.engine)))

    def test_roles_generation_download_and_history(self):
        routes = [('POST', '/dhl-reports/monthly-statement-documents/from-row/1'),
                  ('GET', '/dhl-reports/monthly-statement-documents/1/pdf'),
                  ('GET', '/dhl-reports/expense-imports/1/statement-documents')]
        for method, path in routes:
            for user, expected in [(None, 401), (8, 403), (9, 403)]:
                self.assertEqual(self.request(method, path, user=user)[0], expected)
        batch = self.save()
        self.assertEqual(self.request('POST', f"/dhl-reports/expense-imports/{batch['id']}/confirm")[0], 200)
        status, doc, _ = self.request('POST', f"/dhl-reports/monthly-statement-documents/from-row/{batch['rows'][0]['id']}")
        self.assertEqual(status, 200, doc)
        self.assertNotIn('pdf_content', doc)
        status, pdf, headers = self.request('GET', f"/dhl-reports/monthly-statement-documents/{doc['id']}/pdf")
        self.assertEqual(status, 200)
        self.assertTrue(pdf.startswith(b'%PDF'))
        self.assertEqual(headers['cache-control'], 'no-store')
        self.assertNotIn('dhl', headers['content-disposition'].lower())
        self.assertEqual(self.request('GET', f"/dhl-reports/expense-imports/{batch['id']}/statement-documents")[1][0]['id'], doc['id'])
