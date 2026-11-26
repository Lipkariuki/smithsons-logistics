"""Structure fixtures plus read-only actual monthly source regressions."""
import io
from datetime import date
from decimal import Decimal
from pathlib import Path
import unittest
from openpyxl import Workbook
from services.monthly_expense_parser import parse_expenses,money
from services.dhl_rounding_reconciliation import reconciled_transport,POLICY
from services.dhl_revenue_policy import truck_snapshot,inspect_transport

ROOT=Path(__file__).resolve().parents[1];MONTH=date(2026,9,1)


def net(headers,rows,*,cover=False,title='SEPTEMBER 2026 NET SUMMARY',sheet='Payout details',padding=0):
    book=Workbook();ws=book.active;ws.title=sheet
    if cover:book.create_sheet('Instructions').append(['Notes: how to use this file'])
    ws.append([title])
    for _ in range(padding):ws.append(['Notes: explanatory row'])
    ws.append(headers)
    for row in rows:ws.append(row)
    out=io.BytesIO();book.save(out);book.close();return out.getvalue()


def raw(count=1,*,per_truck=True,fee_ok=True,net_ok=True,difference='-0.01',duplicate=False):
    book=Workbook();ws=book.active
    ws.append(['DATE','TRUCK','REF NO','COST','AMOUNT','SURCHARGE','AMOUNT INC SURCHARGE','5% ADMIN FEE','NET DIST COST'])
    for n in range(count):
        inclusive=Decimal('110.00')+Decimal(difference);fee=inclusive*Decimal('.05')
        ws.append([MONTH,'TEST100A' if per_truck else f'TEST{n}A', 'REF1' if duplicate else f'REF{n}',
            'DIST',100,10,float(inclusive),float(fee) if fee_ok else 0,
            float(inclusive-fee) if net_ok else 0])
    out=io.BytesIO();book.save(out);book.close();return out.getvalue()


class LayoutTests(unittest.TestCase):
    def test_reordered_headers_currency_owner_and_multiple_sheets(self):
        p=parse_expenses(net(['OWNER NAME','Breakages','Truck Registration Number','Shell Fuel (KES)','S.No'],
            [['Owner exactly as supplied',None,'KAV-086M','KES 1,234.56',1]],cover=True,padding=35),MONTH)
        self.assertTrue(p.ready);self.assertEqual(p.header_row,37)
        self.assertEqual(p.rows[0].plate,'KAV086M');self.assertEqual(p.rows[0].owner_name,'Owner exactly as supplied')
        self.assertEqual(p.rows[0].expenses['fuel'],Decimal('1234.56'))
        self.assertEqual(p.rows[0].expenses['breakages'],Decimal('0'))

    def test_explicit_continuation_sums_once_but_conflicting_duplicates_block(self):
        headers=['Truck','OWNER','Fuel','Breakages','Entry Type']
        p=parse_expenses(net(headers,[['KAA123B','Owner',100,2,'primary'],[None,'Owner',30,1,'continuation']]),MONTH)
        self.assertTrue(p.ready);self.assertEqual(len(p.rows),1)
        self.assertEqual(p.rows[0].expenses['fuel'],Decimal('130'))
        self.assertEqual(p.rows[0].continuation_rows,[4])
        for row in [['KAA123B','Other owner',30,1,'continuation'],['KAA123B','Owner',100,2,'continuation'],['KAA123B','Owner',30,1,'']]:
            with self.subTest(row=row):self.assertFalse(parse_expenses(net(headers,[['KAA123B','Owner',100,2,'primary'],row]),MONTH).ready)

    def test_notes_and_repeated_headers_are_not_trucks_but_numeric_orphans_block(self):
        headers=['TRUCK REG.NO','Fuel']
        p=parse_expenses(net(headers,[['KAA123B',10],headers,['Notes: prepared on 25/09/2026'],['TOTAL EXPENSES',10]]),MONTH)
        self.assertTrue(p.ready);self.assertEqual(len(p.rows),1)
        self.assertFalse(parse_expenses(net(headers,[['KAA123B',10],[None,50]]),MONTH).ready)

    def test_unknown_financial_headers_never_deducted_without_approval(self):
        content=net(['Truck','Fuel','Parking','Notes'],[['KAA123B',1,20,'reviewed']])
        p=parse_expenses(content,MONTH)
        self.assertEqual([h.original_header for h in p.headers if h.classification=='unknown'],['Parking'])
        approved=parse_expenses(content,MONTH,approved_mappings={'Parking':'Parking'})
        self.assertTrue(approved.ready);self.assertEqual(approved.rows[0].expenses['parking'],Decimal('20'))
        self.assertFalse(parse_expenses(net(['Truck','Fuel','Notes'],[['KAA123B',1,20]]),MONTH).ready)

    def test_invalid_nonblank_and_uncached_formula_are_not_zero(self):
        for v in ['not paid','=1+2','USD 30','1,2',True]:
            with self.subTest(v=v):self.assertFalse(parse_expenses(net(['Truck','Fuel'],[['KAA123B',v]]),MONTH).ready)
        self.assertEqual(money('(1,234.56) KES'),Decimal('-1234.56'))
        self.assertEqual(money('Kshs. 1 234.56'),Decimal('1234.56'))

    def test_competing_tables_are_ambiguous(self):
        book=Workbook()
        for ws in [book.active,book.create_sheet('Second')]:
            ws.append(['SEPTEMBER 2026 NET SUMMARY']);ws.append(['Truck','Fuel']);ws.append(['KAA123B',10])
        out=io.BytesIO();book.save(out);book.close()
        with self.assertRaises(ValueError):parse_expenses(out.getvalue(),MONTH)
        self.assertTrue(parse_expenses(out.getvalue(),MONTH,sheet_name='Second').ready)

    def test_merged_registration_is_explicit_continuation_but_merged_money_blocks(self):
        from openpyxl import load_workbook
        book=load_workbook(io.BytesIO(net(['Truck','Owner','Fuel','Breakages'],[['KAA123B','Owner',100,2],[None,None,30,1]])))
        ws=book.active;ws.merge_cells('A3:A4');ws.merge_cells('B3:B4')
        out=io.BytesIO();book.save(out)
        p=parse_expenses(out.getvalue(),MONTH)
        self.assertTrue(p.ready);self.assertEqual(p.rows[0].expenses['fuel'],Decimal('130'))
        self.assertEqual(p.rows[0].continuation_sources,{4:'merged_truck_cell'})
        ws.merge_cells('C3:C4');out=io.BytesIO();book.save(out);book.close()
        self.assertFalse(parse_expenses(out.getvalue(),MONTH).ready)


class RoundingTests(unittest.TestCase):
    def test_reference_columns_are_optional_for_exact_rows_not_for_tolerance_evidence(self):
        from openpyxl import load_workbook
        for delta,accepted in [('0.00',True),('-0.01',False)]:
            book=load_workbook(io.BytesIO(raw(difference=delta)));book.active.delete_cols(8,2)
            out=io.BytesIO();book.save(out);book.close()
            scan=reconciled_transport(out.getvalue(),MONTH)
            self.assertEqual(not any(i['blocking'] for i in scan['issues']),accepted)
            self.assertEqual(scan['transactions'][0]['inclusive'],'110.00' if accepted else '109.99')

    def test_inclusive_amount_retained_only_with_corroboration(self):
        original=raw();strict=inspect_transport(original,MONTH);scan=reconciled_transport(original,MONTH)
        self.assertEqual(scan['policy'],POLICY)
        self.assertEqual(scan['transactions'][0]['inclusive'],strict['transactions'][0]['inclusive'])
        self.assertEqual(scan['transactions'][0]['surcharge'],'10.00')
        self.assertEqual(scan['issues'][0]['code'],'source_rounding_reconciled')
        for content in [raw(fee_ok=False),raw(net_ok=False),raw(difference='-0.02'),raw(2,duplicate=True)]:
            with self.subTest(content=len(content)):self.assertTrue(any(i['blocking'] for i in reconciled_transport(content,MONTH)['issues']))

    def test_absolute_caps_cannot_be_offset_or_accumulated_without_limit(self):
        self.assertEqual(reconciled_transport(raw(5),MONTH)['policy'],POLICY)
        self.assertNotEqual(reconciled_transport(raw(6),MONTH)['policy'],POLICY)
        self.assertEqual(reconciled_transport(raw(25,per_truck=False),MONTH)['policy'],POLICY)
        self.assertNotEqual(reconciled_transport(raw(26,per_truck=False),MONTH)['policy'],POLICY)

    def test_contradictory_formula_is_not_accepted_even_with_matching_cache(self):
        from openpyxl import load_workbook
        from zipfile import ZipFile,ZIP_DEFLATED
        from xml.etree import ElementTree as ET
        book=load_workbook(io.BytesIO(raw()));ws=book.active
        ws['H2']='=Z99';ws['I2']='=G2-H2';out=io.BytesIO();book.save(out);book.close()
        original=ZipFile(io.BytesIO(out.getvalue()));result=io.BytesIO()
        ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with ZipFile(result,'w',ZIP_DEFLATED) as target:
            for item in original.infolist():
                content=original.read(item.filename)
                if item.filename=='xl/worksheets/sheet1.xml':
                    tree=ET.fromstring(content)
                    for coordinate,value in [('H2','5.4995'),('I2','104.4905')]:
                        cell=tree.find(f'.//m:c[@r="{coordinate}"]',ns)
                        cell.find('m:v',ns).text=value
                    content=ET.tostring(tree)
                target.writestr(item,content)
        original.close()
        scan=reconciled_transport(result.getvalue(),MONTH)
        self.assertTrue(any(i['blocking'] for i in scan['issues']))
        self.assertNotEqual(scan['policy'],POLICY)

    def test_actual_february_august_september_workbooks(self):
        for prefix,month,raw_name,net_name,count in [
            ('February',date(2026,2,1),'FEBRUARY 2026 TRIPS SUMMARY.xlsx','FEBRUARY NET SUMMARY 1.xlsx',0),
            ('August',date(2026,8,1),'AUGUST 2026 GROSS TOTALS.xlsx','AUGUST 2026 NET SUMMARY 1.xlsx',4),
            ('September',MONTH,'SEPTEMBER 2026 GROSS TOTALS (1).xlsx','SEPTEMBER 2026 NET SUMMARY.xlsx',11)]:
            with self.subTest(month=prefix):
                source=(ROOT/'data'/raw_name).read_bytes();expenses=(ROOT/'data'/net_name).read_bytes()
                self.assertTrue(parse_expenses(expenses,month).ready)
                scan=reconciled_transport(source,month)
                if scan is None:self.assertEqual(count,0);continue
                original=inspect_transport(source,month)
                self.assertEqual(sum(i['code']=='source_rounding_reconciled' for i in scan['issues']),count)
                self.assertEqual([t['inclusive'] for t in scan['transactions']],[t['inclusive'] for t in original['transactions']])
                self.assertEqual([t['admin_fee'] for t in scan['transactions']],[t['admin_fee'] for t in original['transactions']])
                if prefix=='September':
                    kay=next(t for t in scan['transactions'] if t['source_row']==30)
                    self.assertEqual(kay['inclusive'],'15223.43');self.assertEqual(kay['rounding_reconciliation']['difference'],'-0.01')
