"""Lightweight snapshot reads. Financial decisions still revalidate on review/confirm.

No cross-request financial cache, no source writes and no alternate formulas.
"""
from decimal import Decimal
from sqlalchemy import select,text,func
from services.monthly_expense_models import imports,rows
from services.monthly_expense_persistence import _sources,get_import
from services.monthly_expense_reports import decimal_json,totals
from services.monthly_expense_parser import normalize_registration
from services import monthly_files as files
from services.truck_confirmations import confirmations,validate_truck
from services.monthly_statement_documents import documents,transport_components,validate_snapshot
from services.monthly_reporting_scope import reporting_read_scope
from services.dhl_performance import timed

FIELDS=('id','import_id','normalized_plate','vehicle_id','vehicle_owner_snapshot','gross','operating_expenses',
 'commission_base','commission','net_payable','revenue_status','issues','financial_status','provisional_financial',
 'truck_confirmation','statement_document_id')

def compact(payload):
    """Never transfer workbook bytes, audit transactions or every expense cell."""
    p=dict(payload);f=dict(p['files'])
    f['raw_files']=f.get('raw_files',[])[:1];f['expense_files']=f.get('expense_files',[])[:1]
    for entry in f['raw_files']:entry.pop('date_review',None)
    if f.get('source_rounding_review'):f['source_rounding_review']={k:v for k,v in f['source_rounding_review'].items() if k!='rows'}
    if f.get('cent_difference_review'):f['cent_difference_review']={k:v for k,v in f['cent_difference_review'].items() if k!='rows'}
    p['files']=f
    if p.get('report'):
        r=dict(p['report']);r['rows']=[{k:v for k,v in row.items() if k in FIELDS} for row in r['rows']]
        r['decisions']={'approved_mappings':r.get('decisions',{}).get('approved_mappings',{})}
        for k in ['comparisons','versions','assumptions','full_report_totals']:r.pop(k,None)
        p['report']=r
    return p

@reporting_read_scope()
@timed('overview')
def overview(conn,month,full_view):
    if month.day!=1:raise ValueError('Choose the first day of the reporting month')
    available=files.available(conn)
    raw=conn.execute(select(*[c for c in files.workbooks.c if c.name not in {'content','date_review'}]).where(
        files.workbooks.c.reporting_month==month).order_by(files.workbooks.c.version.desc()).limit(1)).mappings().first() if available else None
    columns=[imports.c.id,imports.c.reporting_month,imports.c.version,imports.c.status,imports.c.original_filename,
        imports.c.file_sha256,imports.c.created_at,imports.c.uploader_id,imports.c.header_mappings,imports.c.issues,
        imports.c.calculation_policy,imports.c.dhl_source_fingerprint,imports.c.source_verification,
        imports.c.decisions['approved_mappings'].label('approved_mappings'),
        imports.c.decisions['historical_review']['sha256'].astext.label('raw_sha'),
        imports.c.decisions['expense_parser_revision'].astext.label('parser_revision'),
        imports.c.decisions['corrections'].label('corrections')]
    batch=conn.execute(select(*columns).where(imports.c.reporting_month==month).order_by(imports.c.version.desc()).limit(1)).mappings().first()
    source,fingerprint=_sources(conn,month)
    meta=dict(reporting_month=month,archive_available=available,raw_files=[],expense_files=[],latest_report_id=batch['id'] if batch else None,
        unmatched_trucks=[],parsed_dhl={'records':len(source),'fingerprint':fingerprint})
    if raw:meta['raw_files']=[dict(raw,source_kind='archive',download=f"/dhl-reports/monthly-files/raw/{raw['id']}")]
    if batch is None:
        if source:return compact(full_view(conn,month))
        return decimal_json(dict(files=meta,report=None,approvals=[]))
    selected=[rows.c.id,rows.c.import_id,rows.c.normalized_plate,rows.c.vehicle_id,rows.c.vehicle_owner_snapshot,
        rows.c.gross,rows.c.operating_expenses,rows.c.commission_base,rows.c.commission,rows.c.net_payable,
        rows.c.revenue_status,rows.c.issues,func.jsonb_array_length(rows.c.dhl_source_snapshot).label('source_count'),
        rows.c.cell_audit['_provisional_financial'].label('provisional_financial')]
    roster=[dict(r) for r in conn.execute(select(*selected).where(rows.c.import_id==batch['id']).order_by(rows.c.source_row)).mappings()]
    from services.monthly_expense_parser import ALIASES,normalize_header
    stale=(batch['dhl_source_fingerprint']!=fingerprint or (raw and batch['raw_sha']!=raw['content_sha256']) or
        batch['parser_revision']!='structure-v4' or batch['corrections'] or not batch['source_verification'] or
        any(h['classification']=='unknown' and normalize_header(h['original_header']) in ALIASES for h in batch['header_mappings']) or
        any(r['gross'] is None and r['source_count']==0 for r in roster) or
        any(i['code'] in {'invalid_source_amount','inclusive_amount_mismatch','unsupported_source_charge'} for r in roster for i in r['issues']))
    # A changed/unverified draft takes the existing authoritative preview path;
    # never pretend that old snapshot values approve a changed source.
    if batch['status']=='draft' and stale:return compact(full_view(conn,month))
    if {normalize_registration(s['truck_plate']) for s in source}-{r['normalized_plate'] for r in roster}:return compact(full_view(conn,month))
    records=[dict(r) for r in conn.execute(select(confirmations.c.id,confirmations.c.expense_row_id,confirmations.c.normalized_plate,
        confirmations.c.status,confirmations.c.report_version).where(confirmations.c.reporting_month==month)).mappings()]
    by_row={r['expense_row_id']:r for r in records};current={r['normalized_plate']:r for r in records if r['status']=='current'}
    doc_ids=dict(conn.execute(select(documents.c.expense_row_id,documents.c.id).where(documents.c.expense_row_id.in_([r['id'] for r in roster]))).all())
    for r in roster:
        record=by_row.get(r['id']);active=current.get(r['normalized_plate']);blocking=any(i.get('blocking',True) for i in r['issues'])
        can=not record and batch['status']=='draft' and r['gross'] is not None and r['net_payable'] is not None and bool(r['vehicle_id']) and not blocking
        if active and active['report_version']>=batch['version'] and not record:can=False
        r['truck_confirmation']=dict(record=record,current=active,can_confirm=can,expected_current_confirmation_id=active['id'] if active else None)
        r['financial_status']='confirmed' if record else 'calculated_source_review' if r['provisional_financial'] else 'ready' if can else 'activity_verification_required' if r['revenue_status']=='missing' else 'blocked'
        r['statement_document_id']=doc_ids.get(r['id']);r.pop('source_count',None)
    meta['expense_files']=[dict(id=batch['id'],version=batch['version'],status=batch['status'],original_filename=batch['original_filename'],
        content_sha256=batch['file_sha256'],uploaded_at=batch['created_at'],download=f"/dhl-reports/monthly-files/report/{batch['id']}/expenses")]
    if batch['calculation_policy'].get('transport_policy')=='source-inclusive-reconciled-v1':
        meta['source_rounding_review']={'migration_ready':conn.execute(text("SELECT to_regprocedure('dhl_inclusive_rounding_admin_fee(dhl_monthly_expense_rows,jsonb)') IS NOT NULL")).scalar_one()}
    report={k:batch[k] for k in ['id','reporting_month','version','status','header_mappings','issues','calculation_policy']}
    report.update(rows=roster,totals=totals(roster),decisions={'approved_mappings':batch['approved_mappings'] or {}})
    return decimal_json(dict(files=meta,report=report,approvals=list(current.values())))

@reporting_read_scope()
@timed('truck_detail')
def truck_detail(conn,month,plate,full_view):
    plate=normalize_registration(plate)
    summary=overview(conn,month,full_view);report=summary['report']
    if report is None:raise ValueError('Upload the two monthly workbooks first')
    review_options={}
    if not report.get('id'):
        payload=full_view(conn,month);row=next((r for r in payload['report']['rows'] if r['normalized_plate']==plate),None)
        review_options={'verified_no_activity':payload['report']['decisions'].get('verified_no_activity',{})}
    else:
        states=next((r['truck_confirmation'] for r in report['rows'] if r['normalized_plate']==plate),None)
        if states and states['record']:
            saved=conn.execute(select(rows).where(rows.c.import_id==report['id'],rows.c.normalized_plate==plate)).mappings().all()
            batch={'rows':[dict(r) for r in saved]}
        else:
            batch=get_import(conn,report['id'],target_plate=plate)
            review_options={'verified_no_activity':batch['decisions'].get('verified_no_activity',{})}
        row=batch['rows'][0] if batch['rows'] else None
        if row:
            from services.truck_confirmations import _context
            if states['record']:validate_snapshot(row)
            else:
                try:validate_truck(conn,batch,row,_context(conn,batch,plate))
                except ValueError as e:
                    states=dict(states,can_confirm=False);row['issues']=[*row['issues'],dict(code='current_source_review',message=str(e),blocking=True)]
            row['truck_confirmation']=states
            t=row.get('cell_audit',{}).get('_dhl_transport')
            if t:
                row['dhl_admin_fee']=t['admin_fee'] if row['gross'] is not None else None
                row['revenue_breakdown']={k:t[k] for k in ['distribution','offloading','surcharge']}
                if 'rounding_difference' in t:row['revenue_breakdown']['rounding_difference']=t['rounding_difference']
            elif row['gross'] is not None:
                dist,off=transport_components(row);row['revenue_breakdown']={'distribution':str(dist),'offloading':str(off)}
            if row.get('cell_audit',{}).get('_provisional_financial'):row['provisional_financial']=row['cell_audit']['_provisional_financial']
            row['financial_status']=next(r['financial_status'] for r in report['rows'] if r['normalized_plate']==plate)
            row['statement_document_id']=next(r.get('statement_document_id') for r in report['rows'] if r['normalized_plate']==plate)
            row.pop('cell_audit',None)
    if row is None:
        payload=full_view(conn,month);row=next((r for r in payload['files'].get('unmatched_trucks',[]) if r['normalized_plate']==plate),None)
    if row is None:raise ValueError('Truck is not listed in this month')
    if 'truck_confirmation' not in row:
        active=next((r for r in summary.get('approvals',[]) if r['normalized_plate']==plate),None)
        row['truck_confirmation']=dict(record=None,current=active,
            can_confirm=row.get('gross') is not None and row.get('net_payable') is not None and bool(row.get('vehicle_id')) and not any(i.get('blocking',True) for i in row.get('issues',[])),
            expected_current_confirmation_id=active['id'] if active else None)
    return decimal_json(dict(row=row,report_id=report.get('id'),review_options=review_options,latest_report_id=summary['files']['latest_report_id'],
        raw_id=next((r['id'] for r in summary['files']['raw_files'] if r['source_kind']=='archive'),None)))
