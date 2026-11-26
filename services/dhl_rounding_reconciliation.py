"""Evidence-gated source tolerance. Never changes a source financial amount."""
import copy
import io
from collections import Counter,defaultdict
from decimal import Decimal,InvalidOperation
from openpyxl import load_workbook
from services.dhl_revenue_policy import CENT
from services.monthly_expense_parser import normalize_header,money
from services.monthly_reporting_scope import request_read

POLICY='source-inclusive-reconciled-v1'
TRUCK_CAP=Decimal('0.05')
MONTH_CAP=Decimal('0.25')


def _decimal(value):
    if value is None or isinstance(value,bool):raise ValueError('Numeric reconciliation reference required')
    try:result=Decimal(str(value))
    except InvalidOperation as exc:raise ValueError('Invalid reconciliation reference') from exc
    if not result.is_finite():raise ValueError('Invalid reconciliation reference')
    return result


@request_read
def reconciled_transport(content,month):
    from services.dhl_revenue_policy import inspect_transport
    original=inspect_transport(content,month)
    if not original:return None
    scan=copy.deepcopy(original)
    mismatches={i['source_row']:i for i in scan['issues'] if i['code']=='inclusive_amount_mismatch'}
    if not mismatches:return scan
    counts=Counter((t['date'],t['plate'],t['reference'],t['cost']) for t in scan['transactions'])
    ref_identities=defaultdict(set)
    for t in scan['transactions']:ref_identities[t['reference']].add((t['date'],t['plate']))
    marked={i['source_row'] for i in scan['issues'] if i['code']=='source_marked_error'}
    wb=load_workbook(io.BytesIO(content),data_only=True)
    formulas=load_workbook(io.BytesIO(content),data_only=False)
    try:
        ws=wb.active
        for n in range(1,min(ws.max_row,30)+1):
            names={normalize_header(str(c.value)):c.column for c in ws[n] if c.value is not None}
            if {'date','truck','ref no','cost','amount'}.issubset(names):break
        if not {'5 admin fee','net dist cost'}.issubset(names):return scan
        candidates={};truck_total=defaultdict(lambda:Decimal('0.00'))
        for t in scan['transactions']:
            row=t['source_row'];delta=money(t['inclusive'])-money(t['amount'])-money(t['surcharge'])
            if row not in mismatches or t['cost']!='dist' or abs(delta)!=CENT:continue
            if counts[(t['date'],t['plate'],t['reference'],t['cost'])]!=1 or len(ref_identities[t['reference']])!=1 or row in marked:continue
            try:
                fee=_decimal(ws.cell(row,names['5 admin fee']).value)
                net=_decimal(ws.cell(row,names['net dist cost']).value)
            except ValueError:continue
            inclusive_cell=ws.cell(row,names['amount inc surcharge']).coordinate
            fee_cell=ws.cell(row,names['5 admin fee']).coordinate
            fee_formula=formulas.active.cell(row,names['5 admin fee'])
            net_formula=formulas.active.cell(row,names['net dist cost'])
            normalize=lambda v:str(v).replace(' ','').replace('$','').upper()
            fee_forms={f'={inclusive_cell}*0.05',f'=0.05*{inclusive_cell}',f'={inclusive_cell}*5%',f'=5%*{inclusive_cell}'}
            fee_forms|={f'=ROUND({v[1:]},2)' for v in list(fee_forms)}
            net_forms={f'={inclusive_cell}-{fee_cell}',f'=ROUND({inclusive_cell}-{fee_cell},2)'}
            if fee_formula.data_type=='f' and normalize(fee_formula.value) not in fee_forms:continue
            if net_formula.data_type=='f' and normalize(net_formula.value) not in net_forms:continue
            inclusive=money(t['inclusive']);expected=inclusive*Decimal('.05')
            # Excel cache float noise is sub-cent; it is not a money tolerance.
            fee_valid=abs(fee-expected)<=Decimal('0.00000001') or fee==money(expected)
            if not fee_valid or not (abs(net-(inclusive-fee))<=Decimal('0.00000001') or net==money(inclusive-fee)):continue
            candidates[row]=dict(difference=format(delta,'.2f'),status='accepted_source_rounding',
                evidence='inclusive_fee_and_net_references_consistent',fee_reference=str(fee),net_reference=str(net),
                fee_formula=fee_formula.value if fee_formula.data_type=='f' else None,net_formula=net_formula.value if net_formula.data_type=='f' else None,
                amount=t['amount'],surcharge=t['surcharge'],inclusive=t['inclusive'])
            truck_total[t['plate']]+=abs(delta)
        total=sum((abs(Decimal(v['difference'])) for v in candidates.values()),Decimal('0.00'))
        accepted={row:v for row,v in candidates.items() if total<=MONTH_CAP and
                  truck_total[next(t['plate'] for t in scan['transactions'] if t['source_row']==row)]<=TRUCK_CAP}
        if not accepted:return scan
        scan['policy']=POLICY
        scan['rounding_absolute_total']=format(sum(abs(Decimal(v['difference'])) for v in accepted.values()),'.2f')
        for t in scan['transactions']:
            if t['source_row'] in accepted:t['rounding_reconciliation']=accepted[t['source_row']]
        for issue in scan['issues']:
            if issue['code']=='inclusive_amount_mismatch' and issue['source_row'] in accepted:
                r=accepted[issue['source_row']]
                issue.update(code='source_rounding_reconciled',blocking=False,
                    message=f"Excel row {issue['source_row']}: source inclusive {r['inclusive']} retained once; component difference {r['difference']} corroborated by fee/net references and within approved cumulative limits.")
        return scan
    finally:
        wb.close()
        formulas.close()
