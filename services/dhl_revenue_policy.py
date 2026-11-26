"""New-format transport source arithmetic, shared by import and verification.

Not a payout engine: commission remains in monthly_expense_calculations.
"""
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import io
from openpyxl import load_workbook
from services.monthly_expense_parser import money, normalize_header, validate_xlsx_envelope, normalize_registration
from services.monthly_reporting_scope import request_read

POLICY = 'dist-surcharge-admin-v1'
COMPONENT_POLICY = 'dist-components-cent-v1'
HEADERS = {'surcharge', 'amount inc surcharge', '5 admin fee', 'net dist cost'}
CENT = Decimal('.01')


def is_new_format(names):
    present = HEADERS.intersection(names)
    if present and not {'surcharge','amount inc surcharge'}.issubset(names):
        raise ValueError('Incomplete surcharge workbook headers; SURCHARGE and AMOUNT INC SURCHARGE are required')
    return bool(present)


@request_read
def inspect_transport(content, month):
    validate_xlsx_envelope(content)
    wb=load_workbook(io.BytesIO(content),data_only=True)
    formulas=load_workbook(io.BytesIO(content),data_only=False)
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
            plate=normalize_registration(v['truck'])
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
            # Offloading attracts no surcharge. Only a genuinely empty source
            # cell may mean zero; an uncached formula is not an empty cell.
            blank_offloading_surcharge=(item['cost']=='offloading' and v['surcharge'] is None
                and formulas.active.cell(number,names['surcharge']).value is None)
            try:
                amount=money(v['amount']);inclusive=money(v['amount inc surcharge'])
                surcharge=Decimal('0.00') if blank_offloading_surcharge and amount==inclusive else money(v['surcharge'])
            except ValueError:
                issue('invalid_source_amount','AMOUNT, SURCHARGE and AMOUNT INC SURCHARGE must be numeric. A blank Offloading surcharge is allowed only when AMOUNT equals AMOUNT INC SURCHARGE.');continue
            if blank_offloading_surcharge:
                item['interpretations']=[dict(cell=f"{ws.cell(number,names['surcharge']).column_letter}{number}",
                    original_value=None,interpretation='offloading_blank_surcharge_zero',amount='0.00')]
            if amount+surcharge!=inclusive:
                issue('inclusive_amount_mismatch',f'AMOUNT {amount:.2f} + SURCHARGE {surcharge:.2f} differs from inclusive amount {inclusive:.2f}; no adjustment was made.')
            if item['cost']=='offloading' and surcharge!=0:
                issue('offloading_surcharge_review','Surcharge is approved for DIST only; review this Offloading surcharge.')
            fee=(inclusive*Decimal('.05')).quantize(CENT,rounding=ROUND_HALF_UP) if item['cost']=='dist' else Decimal('0.00')
            item.update(amount=format(amount,'.2f'),surcharge=format(surcharge,'.2f'),inclusive=format(inclusive,'.2f'),admin_fee=format(fee,'.2f'))
            comparison=v.get('5 admin fee')
            if comparison is not None:
                try:reference=money(comparison)
                except ValueError:issue('admin_fee_reference_invalid','Workbook fee is not numeric; calculated fee is unchanged.',False)
                else:
                    if reference!=fee:issue('admin_fee_reference_mismatch',f'Workbook fee {reference:.2f}; calculated DIST-only fee {fee:.2f}. Comparison only.',False)
            if flagged:issue('source_marked_error','Transaction follows TRIP ADDED IN ERROR; neither excluded nor approved.')
            result['transactions'].append(item)
        return result
    finally:
        wb.close()
        formulas.close()


def truck_snapshot(inspection, plate, month):
    transactions=[dict(t) for t in inspection['transactions'] if t['plate']==plate]
    total=lambda field,kind=None:sum((Decimal(t[field]) for t in transactions if kind is None or t['cost']==kind),Decimal('0.00'))
    result=dict(policy=inspection['policy'],reporting_month=month.isoformat(),transactions=transactions,
                distribution=format(total('amount','dist'),'.2f'),offloading=format(total('amount','offloading'),'.2f'),
                surcharge=format(total('surcharge'),'.2f'),gross=format(total('inclusive'),'.2f'),admin_fee=format(total('admin_fee'),'.2f'))
    if inspection['policy']=='source-inclusive-reconciled-v1':
        result.update(rounding_difference=format(total('inclusive')-total('amount')-total('surcharge'),'.2f'),
            rounding_absolute_total=format(sum((abs(Decimal(t['rounding_reconciliation']['difference'])) for t in transactions if t.get('rounding_reconciliation')),Decimal('0.00')),'.2f'),
            month_rounding_absolute_total=inspection['rounding_absolute_total'])
    return result


@request_read
def payout_transport(content, month, *, accept_cent_differences=False):
    """Explicit new-version policy; the original importer/inspection stays strict."""
    import copy
    scan=inspect_transport(content,month)
    if not scan or not accept_cent_differences:return scan
    scan=copy.deepcopy(scan);scan['policy']=COMPONENT_POLICY
    accepted=set();fee_changed=set()
    for t in scan['transactions']:
        original=money(t['inclusive']);calculated=money(t['amount'])+money(t['surcharge'])
        delta=calculated-original
        t['source_inclusive']=format(original,'.2f');t['source_adjustment']='0.00'
        if t['cost']=='dist' and abs(delta)==CENT:
            previous_fee=t['admin_fee']
            t['inclusive']=format(calculated,'.2f');t['source_adjustment']=format(delta,'.2f')
            t['admin_fee']=format((calculated*Decimal('.05')).quantize(CENT,rounding=ROUND_HALF_UP),'.2f')
            if t['admin_fee']!=previous_fee:
                t['previous_calculated_admin_fee']=previous_fee;fee_changed.add(t['source_row'])
            accepted.add(t['source_row'])
    # An old comparison against the pre-adjustment fee would be misleading.
    # Keep the source workbook unchanged and explicitly display the new fee.
    scan['issues']=[i for i in scan['issues'] if not (i['code']=='admin_fee_reference_mismatch' and i['source_row'] in fee_changed)]
    for issue in scan['issues']:
        if issue['code']=='inclusive_amount_mismatch' and issue['source_row'] in accepted:
            t=next(t for t in scan['transactions'] if t['source_row']==issue['source_row'])
            issue.update(code='source_cent_difference_calculated',blocking=False,
                message=f"Excel row {t['source_row']}: workbook inclusive {t['source_inclusive']}; calculated AMOUNT + SURCHARGE {t['inclusive']}; difference {t['source_adjustment']}; calculated administration fee {t['admin_fee']}. Original retained under approved one-cent policy.")
    return scan


def snapshot_fee(row):
    """Validate frozen source arithmetic before displaying or rendering it."""
    snapshot=row.get('cell_audit',{}).get('_dhl_transport')
    if snapshot is None:return Decimal('0.00')
    inclusive_policy=snapshot.get('policy')=='source-inclusive-reconciled-v1'
    if snapshot.get('policy') not in {POLICY,COMPONENT_POLICY,'source-inclusive-reconciled-v1'}:raise ValueError('Unsupported transport snapshot policy')
    amounts={k:money(snapshot[k]) for k in ('distribution','offloading','surcharge','gross','admin_fee')}
    rounding=money(snapshot['rounding_difference']) if inclusive_policy else Decimal('0.00')
    if amounts['distribution']+amounts['offloading']+amounts['surcharge']+rounding!=amounts['gross']:
        raise ValueError('Transport components disagree; review source')
    dist=off=sur=fee=original_dist=original_off=round_sum=round_abs=Decimal('0.00');seen=set()
    for t in snapshot['transactions']:
        identity=t['source_row']
        if identity in seen:raise ValueError('Duplicate frozen transport row')
        seen.add(identity)
        if t['plate']!=row['normalized_plate'] or t['date'][:7]!=snapshot['reporting_month'][:7]:raise ValueError('Frozen source identity mismatch')
        a,s,i,f=(money(t[k]) for k in ('amount','surcharge','inclusive','admin_fee'))
        if snapshot['policy']==COMPONENT_POLICY:
            original=money(t['source_inclusive']);delta=money(t['source_adjustment'])
            if i-original!=delta or abs(delta)>CENT or (t['cost']!='dist' and delta!=0):
                raise ValueError('Invalid approved source cent adjustment')
            if t['cost']=='dist':original_dist+=original
            elif t['cost']=='offloading':original_off+=original
        if a+s!=i:
            if not inclusive_policy or t['cost']!='dist' or abs(i-a-s)!=CENT:raise ValueError('Frozen inclusive amount mismatch')
            proof=t.get('rounding_reconciliation',{})
            if proof.get('evidence')!='inclusive_fee_and_net_references_consistent' or proof.get('status')!='accepted_source_rounding' or any(proof.get(k)!=t[k] for k in ('amount','surcharge','inclusive')) or money(proof['difference'])!=i-a-s:
                raise ValueError('Missing source rounding evidence')
            from services.dhl_rounding_reconciliation import _decimal
            q=_decimal(proof['fee_reference']);net=_decimal(proof['net_reference'])
            if not (abs(q-i*Decimal('.05'))<=Decimal('.00000001') or q==(i*Decimal('.05')).quantize(CENT,rounding=ROUND_HALF_UP)) or not (abs(net-(i-q))<=Decimal('.00000001') or net==(i-q).quantize(CENT,rounding=ROUND_HALF_UP)):
                raise ValueError('Contradictory source rounding references')
            round_sum+=i-a-s;round_abs+=abs(i-a-s)
        elif inclusive_policy and t.get('rounding_reconciliation'):
            raise ValueError('Unexpected source rounding evidence on an exact row')
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
    if inclusive_policy and (rounding!=round_sum or money(snapshot['rounding_absolute_total'])!=round_abs or round_abs>Decimal('.05') or not round_abs<=money(snapshot['month_rounding_absolute_total'])<=Decimal('.25')):
        raise ValueError('Source rounding cumulative limits exceeded')
    if inclusive_policy:
        for cost,field in [('dist','distribution_cost'),('offloading','offloading_cost')]:
            if sum((money(t['inclusive']) for t in snapshot['transactions'] if t['cost']==cost),Decimal('0.00'))!=sum((money(r[field]) for r in row['dhl_source_snapshot']),Decimal('0.00')):
                raise ValueError('Source-inclusive snapshot differs from retained ledger')
    if snapshot['policy']==COMPONENT_POLICY:
        ledger=row['dhl_source_snapshot']
        if original_dist!=sum((money(r['distribution_cost']) for r in ledger),Decimal('0.00')) or original_off!=sum((money(r['offloading_cost']) for r in ledger),Decimal('0.00')):
            raise ValueError('Original workbook and saved revenue snapshot disagree')
    return fee
