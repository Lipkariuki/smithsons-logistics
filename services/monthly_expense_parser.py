"""Read-only monthly expense preview. No database, API or legacy payslip imports.

Persist HeaderMapping records at confirmation in a future phase; pass those records
back as approved_mappings on later imports. Unknown columns are never expenses
until explicitly mapped. None in approved_mappings explicitly ignores a column.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import io
import re
import unicodedata
from typing import Mapping
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook

CENT = Decimal('0.01')
OPTIONAL_CATEGORY = 'kasarani_ksm_fuel'


def normalize_header(value: str) -> str:
    value = unicodedata.normalize('NFKC', value).casefold()
    return ' '.join(re.sub(r'[^\w]+', ' ', value).split())


KNOWN = {
    'fuel': ('Fuel', ('fuel', 'fuel cost', 'shell fuel')),
    'kasarani_ksm_fuel': ('Kasarani & KSM Fuel', ('kasarani & ksm fuel', 'kasarani and ksm fuel', 'kasarani ksm fuel')),
    'breakages': ('Breakages', ('breakages', 'breakage')),
    'telematics_vss': ('Telematics & VSS', ('telematics & vss', 'telematics and vss', 'telematics vss')),
    'gprs': ('GPRS', ('gprs',)),
    'shunting': ('Shunting', ('shunting',)),
}
# Business-approved additional categories do not change the historical six
# absent-category assumptions. Preserve any earlier explicit mapping/ignore.
BUSINESS_APPROVED = {
    'fidelity_charges': ('Fidelity Charges', ('fidelity charges',)),
    'reflective_vests': ('Reflective Vests', ('reflective vests',)),
}
CATEGORIES = {**KNOWN, **BUSINESS_APPROVED}
ALIASES = {normalize_header(alias): key for key, (_, aliases) in CATEGORIES.items() for alias in aliases}
BUSINESS_ALIASES = {normalize_header(alias) for _, aliases in BUSINESS_APPROVED.values() for alias in aliases}
TRUCK_HEADERS = {normalize_header(s) for s in ('TRUCK REG/NO', 'TRUCK REG.NO', 'TRUCK REGISTRATION', 'TRUCK REG NO')}
TRUCK_HEADERS.update(normalize_header(s) for s in ('TRUCK','TRUCK REGISTRATION NUMBER','VEHICLE REGISTRATION','REGISTRATION NUMBER','REG NO','REG. NO.'))
OWNER_HEADERS = {normalize_header(s) for s in ('OWNER','OWNER NAME','TRUCK OWNER','PARTNER','PARTNER NAME')}
NOTE_HEADERS = {'notes','remarks','description'}
ROW_TYPE_HEADERS = {'row type','entry type'}
INDEX_HEADERS = {'no','s no','sno','serial no','row number','index'}
TOTAL_LABELS={'total','grand total','totals','total expenses','total net payable','sub total','subtotal'}
CONTINUATIONS = {'continuation','continued'}
IGNORED = {normalize_header(s) for s in ('OPERATING EXPENSES', 'TOTAL OPERATING EXPENSES', 'TOTAL EXPENSES', 'GROSS AMOUNT', 'NET PAID I', 'NET PAID 1', 'NET PAID 2', 'NET PAID', 'NET PAY', '7% COMMISSION', '7 COMMISSION')}
IGNORED.update(normalize_header(s) for s in ('NET PAID II','NET PAYABLE','DIST','OFFLOADING','SURCHARGE','NET DIST COST','5% ADMIN FEE'))


def header_identity(value):
    return re.sub(r'\s+(?:kes|ksh|kshs)$','',normalize_header(value))


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    cell: str | None = None
    blocking: bool = True


@dataclass(frozen=True)
class HeaderMapping:
    column: int
    original_header: str
    normalized_header: str
    classification: str  # truck / expense / ignored / unknown
    category: str | None = None
    label: str | None = None
    approval_source: str = 'built_in'


@dataclass
class ExpenseRow:
    row_number: int
    original_plate: str
    plate: str
    expenses: dict[str, Decimal | None] = field(default_factory=dict)
    source_values: dict[str, dict] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    classifications_complete: bool = True
    owner_name: str | None = None
    continuation_rows: list[int] = field(default_factory=list)
    continuation_sources: dict[int,str] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.classifications_complete and not any(i.blocking for i in self.issues)


@dataclass
class ExpensePreview:
    month: date
    sheet: str
    header_row: int
    headers: list[HeaderMapping]
    rows: list[ExpenseRow]
    issues: list[Issue]

    @property
    def ready(self) -> bool:
        return bool(self.rows) and not any(i.blocking for i in self.issues) and all(r.ready for r in self.rows)


def money(value: object) -> Decimal:
    """Validate and round an Excel amount; zero is distinct from missing."""
    if value is None or isinstance(value, bool) or isinstance(value, (date, datetime)):
        raise ValueError('Expected a numeric amount; blank is not zero')
    text = str(value).strip()
    if isinstance(value,str):
        text=unicodedata.normalize('NFKC',text).replace('\u00a0',' ')
        text=re.sub(r'^(?:KES|KSHS?\.?|KSh)\s*','',text,flags=re.I).strip()
        text=re.sub(r'\s*(?:KES|KSHS?\.?)$','',text,flags=re.I).strip().replace('\u2212','-')
        if text.startswith('(') and text.endswith(')'):text='-'+text[1:-1].strip()
        if re.fullmatch(r'[+-]?\d{1,3}(?: \d{3})+(?:\.\d+)?',text):text=text.replace(' ','')
    if not isinstance(value, (int, float, Decimal)) and not re.fullmatch(r'[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?', text):
        raise ValueError('Invalid monetary amount')
    try:
        amount = Decimal(text.replace(',', ''))
        if not amount.is_finite() or abs(amount) >= Decimal('10000000000000000'):
            raise ValueError('Amount outside supported range')
        return amount.quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError('Invalid monetary amount') from exc


def category_key(label: str) -> str:
    normalized = normalize_header(label)
    if header_identity(label) in IGNORED|TRUCK_HEADERS|OWNER_HEADERS|NOTE_HEADERS|ROW_TYPE_HEADERS|INDEX_HEADERS:
        raise ValueError('Financial summary and truck headers cannot be expense categories')
    key = ALIASES.get(normalized) or normalized.replace(' ', '_')
    if not key:
        raise ValueError('Expense category must have a name')
    return key


def normalize_registration(value):
    return re.sub(r'[\s\-‐‑–—]+','',unicodedata.normalize('NFKC',str(value or ''))).upper()


def _table_headers(ws):
    """Find actual tables without depending on a sheet name or title row."""
    found=[]
    if ws.max_row>10000 or ws.max_column>200:return found
    for r in range(1,min(ws.max_row,100)+1):
        truck_cols=[c.column for c in ws[r] if c.value is not None and normalize_header(str(c.value)) in TRUCK_HEADERS]
        if len(truck_cols)!=1:continue
        following=next((ws.cell(n,truck_cols[0]).value for n in range(r+1,min(ws.max_row,r+30)+1)
                        if ws.cell(n,truck_cols[0]).value is not None),None)
        if following is not None and normalize_header(str(following)) in TRUCK_HEADERS:continue
        if following is None and not any(header_identity(str(c.value or '')) in set(ALIASES)|IGNORED for c in ws[r]):continue
        found.append(r)
    if not found:return found
    first=tuple(normalize_header(str(c.value)) if c.value is not None else '' for c in ws[found[0]])
    # Identical printed-page headers are the same table, not a second dataset.
    return [found[0]]+[r for r in found[1:] if tuple(normalize_header(str(c.value)) if c.value is not None else '' for c in ws[r])!=first]


def validate_xlsx_envelope(content: bytes) -> None:
    """Shared read-only size/container guard for expense and raw-review uploads."""
    if len(content) > 20_000_000:
        raise ValueError('Workbook exceeds 20 MB')
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 100_000_000:
                raise ValueError('Expanded workbook exceeds 100 MB')
            if not {'[Content_Types].xml', 'xl/workbook.xml', '_rels/.rels'}.issubset(archive.namelist()):
                raise ValueError('Expected an XLSX workbook structure')
            if any(name.lower().endswith('vbaproject.bin') for name in archive.namelist()):
                raise ValueError('Macro-enabled workbooks are not supported')
    except BadZipFile as exc:
        raise ValueError('Expected an XLSX workbook') from exc


def parse_expenses(
    content: bytes, month: date, *, sheet_name: str | None = None,
    approved_mappings: Mapping[str, str | None] | None = None,
    corrections: Mapping[str, object] | None = None,
) -> ExpensePreview:
    """Preview XLSX; mappings/corrections represent explicit administrator decisions."""
    if month.day != 1:
        raise ValueError('Reporting month must be its first day')
    validate_xlsx_envelope(content)
    wb = load_workbook(io.BytesIO(content), data_only=False)
    cached = load_workbook(io.BytesIO(content), data_only=True)
    try:
        if sheet_name is None:
            tables=[(ws.title,r) for ws in wb for r in _table_headers(ws)]
            if len(tables)!=1:raise ValueError('Expected one unambiguous expense table; select a worksheet if several tables exist')
            sheet_name=tables[0][0]
        if sheet_name not in wb.sheetnames:
            raise ValueError('Worksheet not found')
        ws, values = wb[sheet_name], cached[sheet_name]
        if ws.max_row > 10000 or ws.max_column > 200:
            raise ValueError('Worksheet exceeds preview limits')
        header_rows = _table_headers(ws)
        if len(header_rows) != 1:
            raise ValueError('Expected one unambiguous truck header within first 30 rows')
        header_row = header_rows[0]
        issues: list[Issue] = []
        supplied = approved_mappings or {}
        mappings: dict[str, str | None] = {}
        for original, label in supplied.items():
            norm = normalize_header(original)
            if norm in mappings:
                raise ValueError('Duplicate normalized mapping header')
            if header_identity(norm) in IGNORED and label is None:
                mappings[norm]=None
                continue  # Compatible explicit ignore; never makes a deduction.
            if header_identity(norm) in IGNORED|TRUCK_HEADERS|OWNER_HEADERS|ROW_TYPE_HEADERS|INDEX_HEADERS or (norm in ALIASES and norm not in BUSINESS_ALIASES):
                raise ValueError('Built-in header classifications cannot be overridden')
            mappings[norm] = label
        headers: list[HeaderMapping] = []
        used_headers: set[str] = set()
        used_categories: set[str] = set()
        for cell in ws[header_row]:
            if cell.value is None:
                # Only an unlabeled first-column 1..N index beside a known
                # truck column is nonfinancial. Other unknown columns still block.
                truck_columns=[c.column for c in ws[header_row] if normalize_header(str(c.value or '')) in TRUCK_HEADERS]
                if cell.column == 1 and len(truck_columns)==1:
                    type_cols=[c.column for c in ws[header_row] if normalize_header(str(c.value or '')) in ROW_TYPE_HEADERS]
                    ordinal=[ws.cell(r,1) for r in range(header_row+1,ws.max_row+1)
                             if (ws.cell(r,truck_columns[0]).value is not None and normalize_header(str(ws.cell(r,truck_columns[0]).value)) not in TOTAL_LABELS)
                             or any(normalize_header(str(ws.cell(r,c).value or '')) in CONTINUATIONS for c in type_cols)]
                    if ordinal and all(c.data_type!='f' and not isinstance(c.value,bool) and c.value==i for i,c in enumerate(ordinal,1)):
                        headers.append(HeaderMapping(1,'[row number]','row number','ignored',None,None,'verified_ordinal'))
                        continue
                if any(ws.cell(r, cell.column).value is not None for r in range(header_row + 1, ws.max_row + 1)):
                    issues.append(Issue('missing_header', 'Populated column has no header', cell.coordinate))
                continue
            original = str(cell.value)
            norm = normalize_header(original)
            identity=header_identity(original)
            mapping_key=norm if norm in mappings else identity
            if norm in used_headers:
                issues.append(Issue('duplicate_header', 'Duplicate normalized header', cell.coordinate))
            used_headers.add(norm)
            category = label = None
            source = 'built_in'
            if norm in TRUCK_HEADERS:
                classification = 'truck'
            elif norm in OWNER_HEADERS:
                classification = 'owner'
            elif norm in ROW_TYPE_HEADERS:
                classification = 'row_type'
            elif norm in INDEX_HEADERS:
                classification='index'
            elif identity in IGNORED:
                classification = 'ignored'
            elif identity in ALIASES and not (mapping_key in mappings and (norm in BUSINESS_ALIASES or identity!=norm)):
                classification = 'expense'
                category = ALIASES[identity]
                label = CATEGORIES[category][0]
            elif mapping_key in mappings:
                source = 'administrator'
                label = mappings[mapping_key]
                classification = 'ignored' if label is None else 'expense'
                category = None if label is None else category_key(label)
            elif norm in NOTE_HEADERS and all(ws.cell(r,cell.column).value is None or
                    (isinstance(ws.cell(r,cell.column).value,str) and not re.search(r'\d',ws.cell(r,cell.column).value))
                    for r in range(header_row+1,ws.max_row+1)):
                classification='ignored'
            else:
                classification = 'unknown'
                issues.append(Issue('unknown_column', 'Classify this column as expense or ignored', cell.coordinate))
            if category is not None:
                if category in used_categories:
                    issues.append(Issue('duplicate_category', f'Multiple columns map to {category}', cell.coordinate))
                used_categories.add(category)
            headers.append(HeaderMapping(cell.column, original, norm, classification, category, label, source))
        trucks = [h for h in headers if h.classification == 'truck']
        if len(trucks) != 1:
            raise ValueError('Expected exactly one truck registration column')
        # Absent categories contribute zero; they never inherit previous values.
        # Omitted known categories are disclosed without inventing source columns.
        for key, (label, _) in KNOWN.items():
            if key not in used_categories and key != OPTIONAL_CATEGORY:
                issues.append(Issue('category_absent_zero', f'{label} column absent; assuming 0.00', blocking=False))
        optional_absent = OPTIONAL_CATEGORY not in used_categories
        if optional_absent:
            issues.append(Issue('optional_category_absent', 'Kasarani & KSM Fuel column absent; assuming 0.00', blocking=False))
        # Explicitly compare recognizable workbook month evidence with selection.
        months = {name.casefold(): i for i, name in enumerate(
            ('January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'), 1)}
        months.update({name[:3]:number for name,number in list(months.items())});months['sept']=9
        evidence = []
        titles=[ws.title]
        for row in ws.iter_rows(min_row=1, max_row=max(1, header_row - 1)):
            for cell in row:
                value=str(cell.value or '')
                if not re.match(r'^(?:notes?|remarks|prepared)\b',value,re.I) and (
                    re.search(r'\b(?:summary|expenses?|report|month)\b',value,re.I) or
                    re.fullmatch(r'[A-Za-z]+[ ._/\-]*(?:20\d{2})',value.strip())):
                    titles.append(value)
        for value in titles:
            for name,year in re.findall(r'\b('+'|'.join(sorted(months,key=len,reverse=True))+r')[ ._/\-]*(20\d{2})\b',value,re.I):
                evidence.append(date(int(year),months[name.casefold()],1))
            for year,number in re.findall(r'\b(20\d{2})-(0[1-9]|1[0-2])\b',value):evidence.append(date(int(year),int(number),1))
        if any(value != month for value in evidence):
            issues.append(Issue('month_mismatch', 'Workbook title disagrees with selected month'))
        if not evidence:
            issues.append(Issue('month_unverified', 'No month evidence; explicit administrator month confirmation required'))
        truck_merges={r:merged.min_row for merged in ws.merged_cells.ranges
            if merged.min_col==merged.max_col==trucks[0].column and merged.min_row>header_row
            for r in range(merged.min_row+1,merged.max_row+1)}
        owner_columns={h.column for h in headers if h.classification=='owner'}
        for merged in ws.merged_cells.ranges:
            is_truck_merge=merged.min_col==merged.max_col==trucks[0].column and merged.min_row>header_row
            is_owner_merge=merged.min_col==merged.max_col and merged.min_col in owner_columns and all(truck_merges.get(r)==merged.min_row for r in range(merged.min_row+1,merged.max_row+1)) and merged.max_row>merged.min_row>header_row
            data_merge=any(re.search(r'\d',str(ws.cell(r,trucks[0].column).value or ''))
                or any(ws.cell(r,c).data_type=='f' or isinstance(ws.cell(r,c).value,(int,float,Decimal))
                       for c in range(merged.min_col,merged.max_col+1))
                for r in range(max(merged.min_row,header_row+1),merged.max_row+1))
            if merged.min_row<=header_row<=merged.max_row or (merged.max_row>header_row and data_merge and not (is_truck_merge or is_owner_merge)):
                issues.append(Issue('merged_data_cells', 'Merged cells intersect headers/data', str(merged)))
        rows: list[ExpenseRow] = []
        seen: set[str] = set()
        corrections = corrections or {}
        consumed: set[str] = set()
        for number in range(header_row + 1, ws.max_row + 1):
            cells = list(ws[number])
            if all(c.value is None or (isinstance(c.value, str) and not c.value.strip()) for c in cells):
                continue
            truck_cell = ws.cell(number, trucks[0].column)
            original_plate = '' if truck_cell.value is None else str(truck_cell.value)
            if normalize_header(original_plate) in TOTAL_LABELS:
                continue
            if normalize_header(original_plate) in TRUCK_HEADERS and all(
                    normalize_header(str(ws.cell(number,h.column).value or ''))==h.normalized_header
                    for h in headers if h.original_header!='[row number]'):
                continue
            row_type=next((normalize_header(str(ws.cell(number,h.column).value or '')) for h in headers if h.classification=='row_type'),'')
            merged_parent=truck_merges.get(number)
            continuation=row_type in CONTINUATIONS or merged_parent is not None
            if not original_plate.strip() and not continuation and any(normalize_header(str(c.value or '')) in TOTAL_LABELS for c in cells):continue
            # Nonfinancial explanatory/footer rows are not invented truck rows.
            meaningful=[c for c in cells if c.value is not None and str(c.value).strip()]
            note_text=bool(meaningful) and all(c.data_type!='f' and isinstance(c.value,str) and not re.search(r'\d',c.value) for c in meaningful)
            if len(meaningful)==1 and isinstance(meaningful[0].value,str) and re.match(r'^(?:notes?|remarks|prepared by)\s*:',meaningful[0].value,re.I):note_text=True
            if not continuation and note_text and (not original_plate.strip() or re.search(r'\s',original_plate.strip())):
                issues.append(Issue('explanatory_row_skipped','Nonfinancial explanatory row retained in original workbook',str(number),False));continue
            plate = normalize_registration(original_plate)
            if continuation and not plate and rows:plate=rows[-1].plate
            row = ExpenseRow(number, original_plate, plate, classifications_complete=not any(i.blocking for i in issues))
            if row_type not in CONTINUATIONS|{'','normal','primary','base','main'}:
                row.issues.append(Issue('unsupported_row_type','Unrecognized entry type; review continuation intent',str(number)))
            owners=[ws.cell(number,h.column) for h in headers if h.classification=='owner']
            if owners:
                if any(c.data_type=='f' for c in owners):row.issues.append(Issue('owner_formula','Owner name must be explicit text',owners[0].coordinate))
                owner_values={str(c.value).strip() for c in owners if c.value is not None and str(c.value).strip()}
                if any(c.value is not None and not isinstance(c.value,str) for c in owners):row.issues.append(Issue('invalid_owner','Owner must be a text name',owners[0].coordinate))
                if len(owner_values)>1:row.issues.append(Issue('owner_conflict','Owner columns disagree',owners[0].coordinate))
                row.owner_name=next(iter(owner_values),None)
            if not re.fullmatch(r'[A-Z0-9]+', plate) or truck_cell.data_type == 'f':
                row.issues.append(Issue('invalid_truck', 'Missing or invalid truck registration', truck_cell.coordinate))
            if plate in seen and not continuation:
                row.issues.append(Issue('duplicate_truck', 'Duplicate normalized registration', truck_cell.coordinate))
            seen.add(plate)
            for header in headers:
                cell = ws.cell(number, header.column)
                if header.classification in {'truck', 'ignored','owner','row_type','index'}:
                    continue
                value = values.cell(number, header.column).value if cell.data_type == 'f' else cell.value
                source = {'cell': cell.coordinate, 'header': header.original_header,
                          'original_value': str(cell.value) if cell.value is not None else None,
                          'cached_value': str(value) if cell.data_type == 'f' and value is not None else None}
                row.source_values[cell.coordinate] = source
                if header.classification != 'expense':
                    continue
                if cell.coordinate in corrections:
                    original_amount = Decimal('0.00') if cell.data_type != 'f' and (value is None or str(value).strip() == '') else money(value)
                    if money(corrections[cell.coordinate]) != original_amount:
                        raise ValueError('Expenses must match the workbook; upload a corrected replacement workbook')
                    value = original_amount
                    consumed.add(cell.coordinate)
                    source['approved_correction'] = str(value)
                    if cell.data_type != 'f' and (cell.value is None or str(cell.value).strip() == ''):
                        source.update(interpretation='blank_to_zero', interpreted_amount='0.00', policy='spreadsheet-expenses-v2')
                elif cell.data_type == 'f':
                    row.issues.append(Issue('formula_cache_missing' if value is None else 'formula_cached',
                                            'Formula requires cached value; cached values may be stale', cell.coordinate, value is None))
                elif value is None or (isinstance(value, str) and not value.strip()):
                    value = Decimal('0.00')
                    source['interpretation'] = 'blank_to_zero'
                    source['interpreted_amount'] = '0.00'
                    source['policy'] = 'spreadsheet-expenses-v2'
                    row.issues.append(Issue('blank_expense_zero', 'Blank expense cell interpreted as KES 0.00 from workbook policy', cell.coordinate, False))
                try:
                    amount = money(value)
                except ValueError:
                    amount = None
                    row.issues.append(Issue('blank_expense' if value is None or str(value).strip() == '' else 'invalid_expense',
                                            'Correct or explicitly confirm this cell as a numeric amount', cell.coordinate))
                if amount is not None and amount < 0:
                    row.issues.append(Issue('negative_expense', 'Negative deduction retained for review', cell.coordinate, False))
                # Do not overwrite a prior value when mappings conflict.
                if header.category not in row.expenses:
                    row.expenses[header.category] = amount
            if optional_absent:
                row.expenses[OPTIONAL_CATEGORY] = Decimal('0.00')
            if continuation:
                if not rows or rows[-1].plate!=plate or (merged_parent is not None and rows[-1].row_number!=merged_parent) or (row.owner_name and rows[-1].owner_name and normalize_header(row.owner_name)!=normalize_header(rows[-1].owner_name)):
                    row.issues.append(Issue('continuation_conflict','Continuation must immediately follow the same truck and owner',truck_cell.coordinate))
                else:
                    parent=rows[-1]
                    if any(v not in {None,Decimal('0.00')} for v in row.expenses.values()) and row.expenses==parent.expenses:
                        row.issues.append(Issue('continuation_duplicate','Identical expense continuation is ambiguous; do not double-deduct',truck_cell.coordinate))
                        rows.append(row);continue
                    for key,amount in row.expenses.items():
                        parent.expenses[key]=None if amount is None or parent.expenses.get(key) is None else parent.expenses[key]+amount
                    parent.source_values.update(row.source_values);parent.issues.extend(row.issues)
                    parent.continuation_rows.append(number)
                    parent.continuation_sources[number]='merged_truck_cell' if merged_parent is not None else 'explicit_marker'
                    continue
            rows.append(row)
        if set(corrections) != consumed:
            raise ValueError('Corrections must refer to included expense cells on truck rows')
        if not rows:
            issues.append(Issue('no_trucks', 'No truck expense rows found'))
        return ExpensePreview(month, sheet_name, header_row, headers, rows, issues)
    finally:
        wb.close()
        cached.close()
