"""Known DHL charge aliases across months; no database or production access."""
from collections import Counter
from datetime import date
from decimal import Decimal
import io
from pathlib import Path
import unittest

from openpyxl import Workbook
from services.monthly_expense_dates import inspect_source, retain_source, validate_source, charge_issues
from services.monthly_expense_parser import parse_expenses
from services.monthly_expense_calculations import calculate_monthly_expenses, RevenueEvidence, RevenueStatus

ROOT = Path(__file__).resolve().parents[1]
JANUARY = ROOT / 'data/JANUARY 2026 TRIPS SUMMARY (1).xlsx'
NET = ROOT / 'data/JANUARY NET SUMMARY.xlsx'


def workbook(month, label='Offload', repeated=None):
    wb=Workbook();ws=wb.active;ws.append(['DATE','TRUCK','REF NO','COST','AMOUNT'])
    day=date(month.year,month.month,10)
    ws.append([day,' KAA 123B ',123.0,'Dist',900])
    ws.append([day,'KAA123B',123.0,label,100])
    ws.append([day,'KAA123B',123.0,'Admin',-70])
    if repeated is not None:ws.append([day,'KAA123B',123.0,repeated,100])
    out=io.BytesIO();wb.save(out);wb.close();return out.getvalue()


def sources(content,month):
    _,groups=inspect_source(content,month)
    return [dict(date=key[0],truck_plate=key[1],ref_no=key[2],
                 distribution_cost=str(amount[0]),offloading_cost=str(amount[1]),
                 total_revenue=str(sum(amount))) for key,amount in groups.items()]


class ChargeAliasTests(unittest.TestCase):
    def test_both_offloading_names_case_and_whitespace_in_every_month(self):
        for month in [date(2026,m,1) for m in range(1,13)]+[date(2027,1,1)]:
            for label in ['Offload','Offloading',' OFFLOAD ','oFfLoAdInG']:
                with self.subTest(month=month,label=label):
                    content=workbook(month,label)
                    self.assertEqual(charge_issues(content,month),[])
                    self.assertEqual(validate_source(retain_source(content,month),{},sources(content,month),month),[])
                    _,groups=inspect_source(content,month)
                    self.assertEqual(sum(sum(v) for v in groups.values()),Decimal('1000.00'))

    def test_aliases_cannot_hide_duplicate_charges(self):
        month=date(2026,1,1)
        for first,second in [('Offload','Offloading'),('Offloading','offload'),('Offload',' OFFLOAD ')]:
            with self.subTest(first=first,second=second):
                content=workbook(month,first,second)
                issues=charge_issues(content,month)
                self.assertEqual([i['code'] for i in issues],['duplicate_source_row'])
                self.assertTrue(issues[0]['blocking'])

    def test_unknown_or_ambiguous_cost_remains_blocked_with_exact_label(self):
        month=date(2026,1,1)
        for label in ['Dist / Offload','Offload adjustment','off duty','OFF','Unknown',None]:
            with self.subTest(label=label):
                issues=charge_issues(workbook(month,label),month)
                self.assertEqual([i['code'] for i in issues],['unsupported_source_charge'])
                self.assertIn(repr(label or ''),issues[0]['message'])
                self.assertTrue(issues[0]['blocking'])

    def test_month_and_year_validation_are_not_relaxed(self):
        content=workbook(date(2026,1,1))
        for month in [date(2026,2,1),date(2027,1,1)]:
            with self.subTest(month=month):
                issues=validate_source(retain_source(content,month),{},[],month)
                self.assertIn('out_of_period_date',{i['code'] for i in issues})

    def test_reference_plate_and_amount_mismatches_still_block(self):
        month=date(2026,1,1);content=workbook(month)
        for key,value in [('ref_no','OTHER'),('truck_plate','OTHER999'),('distribution_cost','899.99')]:
            with self.subTest(key=key):
                observed=sources(content,month);observed[0][key]=value
                self.assertIn('source_manifest_mismatch',{i['code'] for i in validate_source(retain_source(content,month),{},observed,month)})

    @unittest.skipUnless(JANUARY.exists(),'Actual local January workbook required')
    def test_actual_january_has_valid_offload_rows_and_strict_dates(self):
        content=JANUARY.read_bytes();month=date(2026,1,1)
        review,groups=inspect_source(content,month)
        self.assertEqual(review['date_issues'],[])
        self.assertEqual(charge_issues(content,month),[])
        self.assertEqual(len(groups),386)
        self.assertEqual(sum(v[0] for v in groups.values()),Decimal('9286008.41'))
        self.assertEqual(sum(v[1] for v in groups.values()),Decimal('282052.50'))
        self.assertEqual(sum(sum(v) for v in groups.values()),Decimal('9568060.91'))
        kav=[v for k,v in groups.items() if k[1]=='KAV086M']
        self.assertEqual(sum(v[0] for v in kav),Decimal('343716.88'))
        self.assertEqual(sum(v[1] for v in kav),Decimal('11169.00'))

    @unittest.skipUnless(JANUARY.exists() and NET.exists(),'Actual local January workbooks required')
    def test_actual_january_expenses_and_kav_payout_are_workbook_only(self):
        month=date(2026,1,1);parsed=parse_expenses(NET.read_bytes(),month)
        self.assertEqual(len(parsed.rows),31)
        total=sum((sum(r.expenses.values()) for r in parsed.rows),Decimal('0.00'))
        self.assertEqual(total,Decimal('4604877.05'))
        kav=next(r for r in parsed.rows if r.plate=='KAV086M')
        _,groups=inspect_source(JANUARY.read_bytes(),month)
        gross=sum((sum(v) for k,v in groups.items() if k[1]=='KAV086M'),Decimal('0.00'))
        result=calculate_monthly_expenses(kav,month,RevenueEvidence('KAV086M',month,RevenueStatus.DHL_RECORDS,gross,'Isolated January source test, not a real approval'))
        self.assertEqual(result.operating_expenses,Decimal('173500.53'))
        self.assertEqual(result.commission_base,Decimal('181385.35'))
        self.assertEqual(result.commission,Decimal('12696.97'))
        self.assertEqual(result.net_payable,Decimal('168688.38'))
        self.assertEqual({k[1] for k in groups}-{r.plate for r in parsed.rows},{'KDV188C'})
        self.assertIn('KDV118C',{r.plate for r in parsed.rows}-{k[1] for k in groups})
