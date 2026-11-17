"""New-format transport source arithmetic, shared by import and verification.

Not a payout engine: commission remains in monthly_expense_calculations.
"""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import io
from openpyxl import load_workbook
from services.monthly_expense_parser import money, normalize_header, validate_xlsx_envelope
from services.monthly_reporting_scope import request_read

POLICY = 'dist-surcharge-admin-v1'
HEADERS = {'surcharge', 'amount inc surcharge', '5 admin fee', 'net dist cost'}
CENT = Decimal('.01')


def is_new_format(names):
    present = HEADERS.intersection(names)
    if present and present != HEADERS:
        raise ValueError('Incomplete surcharge/admin workbook headers; all four source columns are required')
    return bool(present)


@request_read
def inspect_transport(content, month):
    validate_xlsx_envelope(content)
    wb=load_workbook(io.BytesIO(content),data_only=True)
    try:
        ws=wb.active
        for n in range(1,min(30,ws.max_row)+1):
            names={normalize_header(str(c.value)):c.column for c in ws[n] if c.value is not None}
            if {'date','truck','ref no','cost','amount'}.issubset(names):break
        else:return None
        if not is_new_format(names):return None
        result={'policy':POLICY,'transactions':[],'issues':[],'note_rows':[]}
        marked=False;marked_key=None
        for number in range(n+1,ws.max_row+1):
            v={k:ws.cell(number,c).value for k,c in names.items()}
            label=str(v['cost'] or '').strip().casefold()
            if label=='trip added in error' and all(v.get(k) is None for k in ('date','truck','ref no','amount')):
                result['note_rows'].append(number);marked=True;marked_key=None;continue
            if all(v.get(k) is None for k in ('date','truck','ref no','cost')):continue
            day=v['date'];day=day.date() if isinstance(day,datetime) else day
            if isinstance(day,str):
                try:day=date.fromisoformat(day.strip())
                except ValueError:continue
            if not isinstance(day,date) or (day.year,day.month)!=(month.year,month.month):continue
            plate=''.join(str(v['truck'] or '').split()).upper()
            ref=str(v['ref no'] if v['ref no'] is not None else '').strip();ref=ref[:-2] if ref.endswith('.0') else ref
            key=(day.isoformat(),plate,ref)
            if marked and marked_key is None:marked_key=key
            flagged=marked and key==marked_key
            if marked_key and key!=marked_key:marked=False
            if label=='admin':continue
            if label not in {'dist','offload','offloading'}:continue  # Existing exact charge validation owns this.
            item={'source_row':number,'date':day.isoformat(),'plate':plate,'reference':ref,'cost':'dist' if label=='dist' else 'offloading'}
            def issue(code,message,blocking=True):
                result['issues'].append(dict(code=code,message=f'Excel row {number}: {message}',cell=f'P{number}',blocking=blocking,truck=plate,source_row=number))
            try:amount,surcharge,inclusive=(money(v[k]) for k in ('amount','surcharge','amount inc surcharge'))
            except ValueError:
                issue('invalid_source_amount','DIST, surcharge and inclusive amount must be numeric; correct the source.');continue
            if amount+surcharge!=inclusive:
                issue('inclusive_amount_mismatch',f'AMOUNT {amount:.2f} + SURCHARGE {surcharge:.2f} differs from inclusive amount {inclusive:.2f}; no adjustment was made.')
            if item['cost']=='offloading' and surcharge!=0:
                issue('offloading_surcharge_review','Surcharge is approved for DIST only; review this Offloading surcharge.')
            fee=(inclusive*Decimal('.05')).quantize(CENT,rounding=ROUND_HALF_UP) if item['cost']=='dist' else Decimal('0.00')
            item.update(amount=format(amount,'.2f'),surcharge=format(surcharge,'.2f'),inclusive=format(inclusive,'.2f'),admin_fee=format(fee,'.2f'))
            comparison=v['5 admin fee']
            if comparison is not None:
                try:reference=money(comparison)
                except ValueError:issue('admin_fee_reference_invalid','Workbook fee is not numeric; calculated fee is unchanged.',False)
                else:
                    if reference!=fee:issue('admin_fee_reference_mismatch',f'Workbook fee {reference:.2f}; calculated DIST-only fee {fee:.2f}. Comparison only.',False)
            if flagged:issue('source_marked_error','Transaction follows TRIP ADDED IN ERROR; neither excluded nor approved.')
            result['transactions'].append(item)
        return result
    finally:wb.close()


def truck_snapshot(inspection, plate, month):
    transactions=[dict(t) for t in inspection['transactions'] if t['plate']==plate]
    total=lambda field,kind=None:sum((Decimal(t[field]) for t in transactions if kind is None or t['cost']==kind),Decimal('0.00'))
    return dict(policy=POLICY,reporting_month=month.isoformat(),transactions=transactions,
                distribution=format(total('amount','dist'),'.2f'),offloading=format(total('amount','offloading'),'.2f'),
                surcharge=format(total('surcharge'),'.2f'),gross=format(total('inclusive'),'.2f'),admin_fee=format(total('admin_fee'),'.2f'))


def snapshot_fee(row):
    """Validate frozen source arithmetic before displaying or rendering it."""
    snapshot=row.get('cell_audit',{}).get('_dhl_transport')
    if snapshot is None:return Decimal('0.00')
    if snapshot.get('policy')!=POLICY:raise ValueError('Unsupported transport snapshot policy')
    amounts={k:money(snapshot[k]) for k in ('distribution','offloading','surcharge','gross','admin_fee')}
    if amounts['distribution']+amounts['offloading']+amounts['surcharge']!=amounts['gross']:
        raise ValueError('Transport components disagree; review source')
    dist=off=sur=fee=Decimal('0.00');seen=set()
    for t in snapshot['transactions']:
        identity=t['source_row']
        if identity in seen:raise ValueError('Duplicate frozen transport row')
        seen.add(identity)
        if t['plate']!=row['normalized_plate'] or t['date'][:7]!=snapshot['reporting_month'][:7]:raise ValueError('Frozen source identity mismatch')
        a,s,i,f=(money(t[k]) for k in ('amount','surcharge','inclusive','admin_fee'))
        if a+s!=i:raise ValueError('Frozen inclusive amount mismatch')
        if t['cost']=='dist':
            if f!=(i*Decimal('.05')).quantize(CENT,rounding=ROUND_HALF_UP):raise ValueError('Frozen DIST admin fee mismatch')
            dist+=a
        elif t['cost']=='offloading':
            if s!=0 or f!=0:raise ValueError('Offloading must not attract surcharge or admin fee')
            off+=a
        else:raise ValueError('Unsupported frozen charge')
        sur+=s;fee+=f
    if (dist,off,sur,fee)!=(amounts['distribution'],amounts['offloading'],amounts['surcharge'],amounts['admin_fee']):raise ValueError('Frozen transport totals mismatch')
    if amounts['gross']!=row['gross']:raise ValueError('Frozen gross mismatch')
    return fee
