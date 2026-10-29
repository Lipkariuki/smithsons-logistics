"""Immutable, snapshot-only statements. No live revenue or legacy payslip reads."""
from __future__ import annotations

import calendar
import hashlib
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

from fpdf import FPDF
from sqlalchemy import (MetaData, Table, Column, BigInteger, LargeBinary, String,
                        DateTime, select, insert, text)

from services.monthly_expense_models import imports, rows
from utils.payslip_branding import payslip_text

RENDERER = 'smithsons-monthly-statement-v3-revenue-breakdown'
metadata = MetaData()  # Deliberately excluded from application create_all.
documents = Table('monthly_statement_documents', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('expense_row_id', BigInteger, nullable=False),
    Column('previous_document_id', BigInteger),
    Column('pdf_content', LargeBinary, nullable=False),
    Column('pdf_sha256', String(64), nullable=False),
    Column('renderer_version', String, nullable=False),
    Column('generated_by', BigInteger, nullable=False),
    Column('generated_at', DateTime(timezone=True), nullable=False))


def _safe(value):
    return payslip_text(str(value)).replace('\x00', '')


def validate_snapshot(row):
    """Check integrity without replacing or recomputing stored payable amounts."""
    keys = ('gross', 'operating_expenses', 'commission_base', 'commission', 'net_payable')
    if any(not isinstance(row[k], Decimal) or not row[k].is_finite() for k in keys):
        raise ValueError('Statement requires complete Decimal financial snapshots')
    amounts = [Decimal(v['amount']) for v in row['deductions'].values()]
    if any(not a.is_finite() for a in amounts):
        raise ValueError('Invalid deduction snapshot')
    total = sum(amounts, Decimal('0.00'))
    base = row['gross'] - total
    commission = (max(base, Decimal('0.00')) * Decimal('.07')).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    if (total != row['operating_expenses'] or base != row['commission_base']
        or commission != row['commission'] or base - commission != row['net_payable']):
        raise ValueError('Inconsistent confirmed financial snapshot; no statement created')
    if any(i.get('blocking', True) for i in row['issues']):
        raise ValueError('Unresolved financial validation')


def transport_components(row):
    """Use frozen confirmed source rows, never live trips/manual payslips."""
    from services.monthly_expense_parser import money
    distribution = sum((money(r['distribution_cost']) for r in row['dhl_source_snapshot']), Decimal('0.00'))
    offloading = sum((money(r['offloading_cost']) for r in row['dhl_source_snapshot']), Decimal('0.00'))
    if distribution + offloading != row['gross']:
        raise ValueError('Confirmed transport breakdown does not equal gross; no statement created')
    return distribution, offloading


def render_statement(row, batch):
    validate_snapshot(row)
    distribution, offloading = transport_components(row)
    pdf = FPDF()
    fonts=Path(__file__).resolve().parents[1]/'assets/fonts'
    pdf.add_font('Statement','',str(fonts/'DejaVuSans.ttf'))
    pdf.add_font('Statement','B',str(fonts/'DejaVuSans-Bold.ttf'))
    pdf.set_title('Monthly Transport Statement')
    pdf.set_author('SMITHSONS LOGISTICS')
    pdf.set_creator('SMITHSONS LOGISTICS')
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    logo = Path(__file__).resolve().parents[1] / 'assets/smithsons-logo.svg'
    if logo.exists():
        # Preserve the legacy renderer's text-header fallback when this optional
        # SVG uses gradients unsupported by the installed PDF library.
        try:
            pdf.image(str(logo), x=14, y=12, w=12, h=12)
        except (ValueError, OSError):
            pass
    pdf.set_font('Statement', 'B', 18)
    pdf.cell(0, 8, 'SMITHSONS LOGISTICS', ln=True, align='C')
    pdf.set_font('Statement', '', 10)
    pdf.cell(0, 6, 'Powering Every Trip. Empowering Every Partner.', ln=True, align='C')
    pdf.set_font('Statement', '', 11)
    pdf.cell(0, 6, 'Monthly Transport Statement', ln=True, align='C')
    pdf.ln(6)
    month = batch['reporting_month']
    end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
    for label in (f"Owner: {row['vehicle_owner_snapshot'].get('owner_name') or 'Unassigned'}",
                  f"Vehicle: {row['normalized_plate']}", f'Period: {month} to {end}',
                  f"Confirmed source version: {batch['version']} | Report {batch['id']} | Row {row['id']}"):
        pdf.multi_cell(0, 6, _safe(label), new_x='LMARGIN', new_y='NEXT')
    approval=batch.get('truck_confirmation')
    if approval:
        stamp=approval['confirmed_at'].astimezone(ZoneInfo('Africa/Nairobi'))
        pdf.multi_cell(0,6,f"Truck confirmation: {approval['id']} | Confirmed: {stamp:%Y-%m-%d %H:%M} EAT",new_x='LMARGIN',new_y='NEXT')
        if approval['previous_confirmation_id']:
            pdf.multi_cell(0,6,f"Replaces truck confirmation {approval['previous_confirmation_id']}. Prior statement remains in history.",new_x='LMARGIN',new_y='NEXT')
        adjustment=approval['validation'].get('financial_adjustment')
        if adjustment:
            delta=Decimal(adjustment['net_payable_difference'])
            pdf.multi_cell(0,6,f"Separate correction adjustment: KES {delta:+,.2f} compared with prior confirmed statement. Payment status is not assessed; this is not a new payment instruction.",new_x='LMARGIN',new_y='NEXT')
    pdf.ln(4)

    def line(label, amount, bold=False):
        pdf.set_font('Statement', 'B' if bold else '', 11)
        if any(ord(char) not in pdf.current_font.cmap for char in label if char not in '\r\n\t'):
            raise ValueError('Expense description contains unsupported font characters; no statement was saved')
        wrapped=pdf.multi_cell(130,7,label,dry_run=True,output='LINES')
        for index,part in enumerate(wrapped):
            if pdf.get_y()+7>pdf.h-20:pdf.add_page()
            x,y=pdf.get_x(),pdf.get_y()
            border='LR'+('T' if index==0 else '')+('B' if index==len(wrapped)-1 else '')
            pdf.cell(130,7,part,border=border)
            pdf.cell(0,7,f'KES {amount:,.2f}' if index==0 else '',border=border,align='R')
            pdf.set_xy(x,y+7)

    line('Distribution Revenue', distribution)
    line('Offloading Revenue', offloading)
    line('Gross Transport Revenue', row['gross'], True)
    itemized=Decimal('0.00')
    columns={h['category']:h['column'] for h in batch.get('header_mappings',[]) if h['classification']=='expense'}
    for category,item in sorted(row['deductions'].items(),key=lambda entry:columns.get(entry[0],10000)):
        if Decimal(item['amount']) != 0:
            # Keep the original approved workbook description; no manual expenses.
            line(item.get('original_header') or item['label'], Decimal(item['amount']))
            itemized+=Decimal(item['amount'])
    if itemized!=row['operating_expenses']:raise ValueError('Itemized expenses do not equal Total Expenses')
    line('Total Expenses', row['operating_expenses'], True)
    line('Commission Base', row['commission_base'])
    line('Commission (7% of positive commission base)', row['commission'])
    line('Total Deductions', row['operating_expenses'] + row['commission'])
    line('Net Payable', row['net_payable'], True)
    pdf.ln(5)
    pdf.set_font('Statement', '', 10)
    if row['net_payable'] < 0:
        pdf.multi_cell(0, 6, 'Negative balance retained. Review required; no automatic write-off.', new_x='LMARGIN', new_y='NEXT')
    pdf.multi_cell(0, 6, 'Prepared by: ______________________\nApproved by: ______________________', new_x='LMARGIN', new_y='NEXT')
    pdf.multi_cell(0, 6, 'Confirmed snapshot statement. Corrections require a new report version.', new_x='LMARGIN', new_y='NEXT')
    pdf.multi_cell(0,6,'This statement is not a payment receipt.',new_x='LMARGIN',new_y='NEXT')
    content = pdf.output(dest='S')
    return content.encode('latin1') if isinstance(content, str) else bytes(content)


def get_document(conn, identifier):
    document = dict(conn.execute(select(documents).where(documents.c.id == identifier)).mappings().one())
    content = bytes(document['pdf_content'])
    if hashlib.sha256(content).hexdigest() != document['pdf_sha256']:
        raise ValueError('Stored statement integrity check failed')
    return document


def create_document(conn, row_id, actor_id):
    # Use the same month -> parent lock ordering as financial confirmation.
    row = dict(conn.execute(select(rows).where(rows.c.id == row_id)).mappings().one())
    from services.monthly_expense_persistence import _lock
    month=conn.execute(select(imports.c.reporting_month).where(imports.c.id==row['import_id'])).scalar_one()
    _lock(conn,month)
    batch = dict(conn.execute(select(imports).where(imports.c.id == row['import_id']).with_for_update()).mappings().one())
    # A draft may have been edited/confirmed while waiting for the parent lock.
    # Re-read only after that lock, rather than rendering an earlier row image.
    row = dict(conn.execute(select(rows).where(rows.c.id == row_id)).mappings().one())
    existing = conn.execute(select(documents.c.id).where(documents.c.expense_row_id == row_id)).scalar_one_or_none()
    if existing is not None:
        return get_document(conn, existing)
    from services.truck_confirmations import available,confirmations
    approval=None
    if available(conn):
        approval=conn.execute(select(confirmations).where(confirmations.c.expense_row_id==row_id)).mappings().first()
    if approval:
        hashes=conn.execute(text('SELECT dhl_truck_row_hash(:row), dhl_truck_parent_hash(:parent)'),{'row':row_id,'parent':batch['id']}).one()
        if hashes[0]!=approval['row_sha256'] or hashes[1]!=approval['parent_sha256']:
            raise ValueError('Confirmed snapshot integrity check failed')
    else:
        if batch['status'] not in {'confirmed', 'superseded'}:
            raise ValueError('An explicit truck or whole-month confirmation is required')
        if any(i.get('blocking', True) for i in batch['issues']):
            raise ValueError('Unresolved report validation')
    previous = conn.execute(select(documents.c.id).join(rows, rows.c.id == documents.c.expense_row_id)
        .join(imports, imports.c.id == rows.c.import_id)
        .where(rows.c.normalized_plate == row['normalized_plate'],
               imports.c.reporting_month == batch['reporting_month'], imports.c.version < batch['version'])
        .order_by(imports.c.version.desc()).limit(1)).scalar_one_or_none()
    content = render_statement(row, dict(batch,truck_confirmation=approval))
    identifier = conn.execute(insert(documents).values(expense_row_id=row_id, previous_document_id=previous,
        pdf_content=content, pdf_sha256=hashlib.sha256(content).hexdigest(), renderer_version=RENDERER,
        generated_by=actor_id, generated_at=text('CURRENT_TIMESTAMP')).returning(documents.c.id)).scalar_one()
    return get_document(conn, identifier)


def document_info(document):
    return {k: v for k, v in document.items() if k != 'pdf_content'}
