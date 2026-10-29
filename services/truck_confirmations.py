"""Explicit truck approvals over frozen monthly rows; no payment/delivery actions."""
from datetime import datetime, timezone
import base64

from sqlalchemy import (MetaData, Table, Column, BigInteger, Integer, String, Date,
                        DateTime, select, text, insert, update)
from sqlalchemy.dialects.postgresql import JSONB

from services.monthly_expense_models import imports, rows
from services.monthly_expense_persistence import (_lock, _hash, _build, _sources, get_import, POLICY,
    ValidationBlocked, VersionConflict, SourceChanged)
from services.monthly_expense_dates import validate_source, inspect_source
from services.monthly_expense_persistence import _plate
from services.monthly_statement_documents import validate_snapshot

metadata=MetaData()
confirmations=Table('dhl_monthly_truck_confirmations',metadata,
    Column('id',BigInteger,primary_key=True),Column('expense_row_id',BigInteger),
    Column('reporting_month',Date),Column('normalized_plate',String),Column('report_version',Integer),
    Column('status',String),Column('method',String),Column('previous_confirmation_id',BigInteger),
    Column('confirmer_id',BigInteger),Column('confirmed_at',DateTime(timezone=True)),
    Column('reason',String),Column('row_sha256',String),Column('parent_sha256',String),
    Column('source_sha256',String),Column('validation',JSONB))


def available(conn):
    return conn.execute(text("SELECT to_regclass('dhl_monthly_truck_confirmations') IS NOT NULL")).scalar_one()


def _context(conn,batch):
    if batch['calculation_policy'] != POLICY:
        raise ValidationBlocked('Revise this report into the current calculation policy')
    import hashlib
    if hashlib.sha256(bytes(batch['source_content'])).hexdigest()!=batch['file_sha256'] or _hash(batch['decisions'])!=batch['decisions_sha256']:
        raise ValidationBlocked('Workbook or decision checksum changed')
    if batch['source_verification']!=batch['decisions']['source_verification']:
        raise ValidationBlocked('Source verification changed')
    expected, expected_rows, _ = _build(conn,bytes(batch['source_content']),batch['reporting_month'],
        batch['decisions'],batch['uploader_id'],batch['created_at'].isoformat())
    if any(batch[k]!=v for k,v in expected.items()):
        # Validation can legitimately change for unrelated trucks when live DHL
        # records change. Mapping/assumption integrity must nevertheless match.
        if any(batch[k]!=expected[k] for k in ('header_mappings','assumptions')):
            raise ValidationBlocked('Stored workbook mapping or assumptions changed')
    from services.monthly_files import resolve_review
    review=resolve_review(conn,batch['decisions'].get('historical_review'),batch['reporting_month'])
    inspected=inspect_source(base64.b64decode(review['source_content_base64'],validate=True),batch['reporting_month']) if review and review.get('source_content_base64') else None
    source,_=_sources(conn,batch['reporting_month'])
    return expected, {r['source_row']:r for r in expected_rows}, inspected, source


def validate_truck(conn,batch,row,context=None):
    expected, rebuilt, inspected, source = context or _context(conn,batch)
    date_codes={'source_dates_unreviewed','missing_source_date','invalid_source_date','out_of_period_date',
                'invalid_source_identity','invalid_source_amount','source_gross_inconsistent','source_manifest_mismatch'}
    blockers=[i for i in expected['issues'] if i.get('blocking',True) and i['code'] not in date_codes]
    # Include all live selected-month records, including trucks outside the roster.
    from services.monthly_files import resolve_review
    blockers+=validate_source(resolve_review(conn,batch['decisions'].get('historical_review'),batch['reporting_month']),batch['decisions'].get('date_dispositions',{}),
        source,batch['reporting_month'],target_plate=row['normalized_plate'],_inspected=inspected)
    if blockers:
        raise ValidationBlocked('; '.join(i['message'] for i in blockers))
    target=rebuilt.get(row['source_row'])
    if target is None or any(row[k]!=v for k,v in target.items() if k!='revenue_evidence'):
        raise SourceChanged('This truck changed since preview; create and review a new version')
    if sum(r['normalized_plate']==row['normalized_plate'] for r in batch['rows'])!=1:
        raise ValidationBlocked('Duplicate truck rows must be resolved for this truck')
    if row['vehicle_id'] is None or row['revenue_status'] not in {'dhl_records','verified_no_activity'} or not row['revenue_evidence'].strip():
        raise ValidationBlocked('Verify this truck vehicle and revenue evidence')
    validate_snapshot(row)
    other_pending=[]
    if inspected:
        dispositions=batch['decisions'].get('date_dispositions',{})
        other_pending=[r['source_row'] for r in inspected[0]['date_issues']
                       if _plate(r['truck'])!=row['normalized_plate'] and str(r['source_row']) not in dispositions]
    return {'policy':'truck-confirmation-v1','scope_plate':row['normalized_plate'],'verified':True,
            'raw_source_sha256':(batch['decisions'].get('historical_review') or {}).get('sha256'),
            'unresolved_other_truck_date_rows':other_pending,'other_trucks_not_approved':True}


def _current(conn,month,plate):
    return conn.execute(select(confirmations).where(confirmations.c.reporting_month==month,
        confirmations.c.normalized_plate==plate,confirmations.c.status=='current')).mappings().first()


def confirm_truck(conn,row_id,actor_id,reason,expected_current_confirmation_id=None):
    if actor_id<=0 or not reason.strip():raise ValueError('A confirmer and audit reason are required')
    row=dict(conn.execute(select(rows).where(rows.c.id==row_id)).mappings().one())
    month=conn.execute(select(imports.c.reporting_month).where(imports.c.id==row['import_id'])).scalar_one()
    _lock(conn,month)
    conn.execute(select(imports.c.id).where(imports.c.id==row['import_id']).with_for_update()).scalar_one()
    batch=get_import(conn,row['import_id']);row=next(r for r in batch['rows'] if r['id']==row_id)
    existing=conn.execute(select(confirmations).where(confirmations.c.expense_row_id==row_id)).mappings().first()
    if existing:
        if existing['status']!='current':raise VersionConflict('This truck confirmation was superseded; use its stored history')
        return dict(existing)
    current=_current(conn,month,row['normalized_plate'])
    if (current['id'] if current else None)!=expected_current_confirmation_id:
        raise VersionConflict('Current truck approval changed; reload and explicitly review the correction')
    if current and current['report_version']>=batch['version']:
        raise VersionConflict('Corrections must use a newer report version')
    if batch['status']!='draft':raise VersionConflict('Use existing monthly confirmation for this historical version')
    receipt=validate_truck(conn,batch,row)
    if current:
        conn.execute(update(confirmations).where(confirmations.c.id==current['id']).values(status='superseded'))
    hashes=conn.execute(text('''SELECT dhl_truck_row_hash(:row) AS row_hash,
        dhl_truck_parent_hash(:parent) AS parent_hash,dhl_truck_source_hash(:row) AS source_hash'''),{'row':row_id,'parent':batch['id']}).mappings().one()
    identifier=conn.execute(insert(confirmations).values(expense_row_id=row_id,reporting_month=month,
        normalized_plate=row['normalized_plate'],report_version=batch['version'],status='current',method='truck',
        previous_confirmation_id=current['id'] if current else None,confirmer_id=actor_id,
        confirmed_at=datetime.now(timezone.utc),reason=reason.strip(),row_sha256=hashes['row_hash'],
        parent_sha256=hashes['parent_hash'],source_sha256=hashes['source_hash'],
        validation=receipt)
        .returning(confirmations.c.id)).scalar_one()
    return dict(conn.execute(select(confirmations).where(confirmations.c.id==identifier)).mappings().one())


def presentation(conn,batch):
    if not batch.get('id'):return None
    if not available(conn):return None
    all_records=[dict(r) for r in conn.execute(select(confirmations).where(confirmations.c.reporting_month==batch['reporting_month'])).mappings()]
    by_row={r['expense_row_id']:r for r in all_records};current={r['normalized_plate']:r for r in all_records if r['status']=='current'}
    context=None;context_error=None
    if batch['status']=='draft':
        try:context=_context(conn,batch)
        except (ValueError,SourceChanged) as exc:context_error=str(exc)
    states={}
    for row in batch['rows']:
        record=by_row.get(row['id']);active=current.get(row['normalized_plate'])
        error=context_error
        if not record and active and active['report_version']>=batch['version']:
            error='A newer truck version is already approved. Use a newer report version for corrections.'
        if not record and batch['status']=='draft' and error is None:
            try:validate_truck(conn,batch,row,context)
            except ValueError as exc:error=str(exc)
        states[row['id']]={'record':record,'current':active,'can_confirm':not record and batch['status']=='draft' and error is None,
            'status':('confirmed' if record['status']=='current' else 'superseded') if record else
                     ('historical_confirmed' if batch['status'] in {'confirmed','superseded'} else 'needs_review' if error else 'pending'),
            'review_issue':error,'expected_current_confirmation_id':active['id'] if active else None}
    active_ids=[r['expense_row_id'] for r in all_records if r['status']=='current']
    active_rows={r['id']:dict(r) for r in conn.execute(select(rows).where(rows.c.id.in_(active_ids))).mappings()}
    approved=[]
    for record in all_records:
        if record['status']!='current':continue
        r=active_rows[record['expense_row_id']]
        approved.append(dict(record,import_id=r['import_id'],owner_name=r['vehicle_owner_snapshot'].get('owner_name'),
            **{k:r[k] for k in ('gross','operating_expenses','commission','net_payable')}))
    from decimal import Decimal
    approved_totals={k:sum((a[k] for a in approved),Decimal('0.00')) for k in ('gross','operating_expenses','commission','net_payable')}
    return {'rows':states,'current_approvals':approved,'current_approved_totals':approved_totals,
            'confirmed_count':sum(s['status']=='confirmed' for s in states.values()),
            'pending_count':sum(s['status'] in {'pending','needs_review'} for s in states.values()),
            'frozen':bool(any(r['expense_row_id'] in {row['id'] for row in batch['rows']} for r in all_records))}
