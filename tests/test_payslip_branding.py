"""Isolated PDF regression tests: load only render/download functions.

Do not import routers: their imports initialize production DB/auth/SMS services.
Run with: python3 -m unittest discover -s tests -v
"""
import ast
import copy
import io
import os
from pathlib import Path
import re
import subprocess
import unittest
from datetime import date, datetime
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

from fpdf import FPDF
import pdfplumber
from starlette.responses import Response
from utils.payslip_branding import payslip_text

ROOT = Path(__file__).resolve().parents[1]


def load_functions(path, source=None):
    tree = ast.parse(source if source is not None else (ROOT / path).read_text())
    names = {'_latin1', '_format_currency', '_generate_payslip_pdf', '_generate_pdf', 'download_payslip_pdf'}
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            node.decorator_list = []
            node.returns = None
            for arg in node.args.args:
                arg.annotation = None
            node.args.defaults = [ast.Constant(None) for _ in node.args.defaults]
            nodes.append(node)
    namespace = dict(FPDF=FPDF, os=os, datetime=datetime, payslip_text=payslip_text,
                     __file__=str(ROOT / path), Response=Response)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), path, 'exec'), namespace)
    return namespace


def text_and_metadata(content):
    with pdfplumber.open(io.BytesIO(bytes(content))) as pdf:
        return '\n'.join(page.extract_text() or '' for page in pdf.pages), str(pdf.metadata)


def fixtures():
    vehicle = NS(plate_number='KAA123B', owner=NS(name='Sample Partner'))
    payslip = NS(period_start=date(2026, 9, 1), period_end=date(2026, 9, 30),
                 total_revenue=100000.0, commission_rate=.07, commission_amount=7000.0,
                 total_expenses=21500.0, net_pay=71500.0,
                 expenses=[NS(name='Fuel', amount=20000.0), NS(name='Breakages', amount=1500.0)],
                 vehicle=vehicle, document=None)
    report = NS(owner_name='Sample Partner', plate_number='KAA123B', trip_count=4,
                gross_revenue=100000.0, fuel_cost=20000.0, other_expenses=1500.0,
                extra_expenses=0.0, commission=7000.0, net_profit=71500.0,
                actual_payment=70000.0, variance=-1500.0, fuel_litres_total=120.0,
                notes='Monthly review complete')
    return vehicle, payslip, report


class BrandingTests(unittest.TestCase):
    def test_generators_preserve_financial_figures_and_layout(self):
        vehicle, payslip, report = fixtures()
        for path, function, args in [
            ('routers/dhl_reports.py', '_generate_payslip_pdf', (payslip, vehicle)),
            ('routers/reports.py', '_generate_pdf', (report, payslip.period_start, payslip.period_end)),
        ]:
            with self.subTest(path=path):
                before = copy.deepcopy(args)
                old = subprocess.check_output(['git', 'show', f'HEAD:{path}'], cwd=ROOT, text=True)
                original = load_functions(path, old)[function](*args)
                current = load_functions(path)[function](*args)
                old_text, _ = text_and_metadata(original)
                text, metadata = text_and_metadata(current)
                self.assertIn('SMITHSONS LOGISTICS', text)
                self.assertNotRegex(text + metadata, re.compile(r'DHL|Easy Estates', re.I))
                self.assertIn('Monthly Transport Statement', metadata)
                self.assertEqual(re.findall(r'\d[\d,.]*', old_text), re.findall(r'\d[\d,.]*', text))
                self.assertEqual(before, args)
                with pdfplumber.open(io.BytesIO(bytes(original))) as a, pdfplumber.open(io.BytesIO(bytes(current))) as b:
                    self.assertEqual(len(a.pages), len(b.pages))
                    self.assertEqual([(p.width, p.height) for p in a.pages], [(p.width, p.height) for p in b.pages])
                if os.environ.get('WRITE_PAYSLIP_SAMPLES') == '1':
                    name = 'smithsons_partner_sample.pdf' if 'dhl' in path else 'smithsons_internal_sample.pdf'
                    (ROOT / 'output/pdf' / name).write_bytes(bytes(current))

    def test_free_text_is_presentation_only(self):
        vehicle, payslip, report = fixtures()
        payslip.expenses[0].name = 'dHl fuel'
        report.notes = 'DHL review by Easy Estates'
        for path, fn, args in [
            ('routers/dhl_reports.py', '_generate_payslip_pdf', (payslip, vehicle)),
            ('routers/reports.py', '_generate_pdf', (report, payslip.period_start, payslip.period_end)),
        ]:
            text, metadata = text_and_metadata(load_functions(path)[fn](*args))
            self.assertNotRegex(text + metadata, re.compile(r'DHL|Easy Estates', re.I))
        self.assertEqual(payslip.expenses[0].name, 'dHl fuel')
        self.assertEqual(report.notes, 'DHL review by Easy Estates')

    def test_download_preserves_stored_history_and_brands_new_filename(self):
        vehicle, payslip, _ = fixtures()
        ns = load_functions('routers/dhl_reports.py')
        model = MagicMock()
        ns.update(DHLPayslip=model, Vehicle=MagicMock(), joinedload=MagicMock())
        db = MagicMock()
        db.query.return_value.options.return_value.filter.return_value.first.return_value = payslip
        for stored in [False, True]:
            with self.subTest(stored=stored):
                historical_bytes = b'%PDF-historical-document-unchanged'
                payslip.document = NS(pdf_bytes=historical_bytes) if stored else None
                response = ns['download_payslip_pdf'](1, db, None)
                self.assertEqual(response.media_type, 'application/pdf')
                self.assertEqual(response.headers['content-disposition'],
                                 'attachment; filename="smithsons_payslip_KAA123B_2026-09-01.pdf"')
                if stored:
                    self.assertEqual(response.body, historical_bytes)
                    self.assertEqual(payslip.document.pdf_bytes, historical_bytes)
                else:
                    self.assertIn('SMITHSONS LOGISTICS', text_and_metadata(response.body)[0])
                db.commit.assert_not_called()
                db.add.assert_not_called()


if __name__ == '__main__':
    unittest.main()
