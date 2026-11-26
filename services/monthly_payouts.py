"""Simple saved-file orchestration. Existing parser/calculator/guards own money.

No legacy expenses, manual payslip arithmetic, payments or delivery calls.
Only append financial drafts; confirmation is still an explicit separate action.
"""
from sqlalchemy import select, text
from services import monthly_files as files
from services.monthly_expense_models import imports
from services.monthly_expense_persistence import (
    _lock, _sources, create_draft, preview_import, get_import, DuplicateUpload, VersionConflict,
)

SYSTEM_REVIEW = ('System checked the retained workbook against selected-month DHL records. '
                 'Each truck must pass strict source validation and explicit administrator confirmation; '
                 'this is not a human approval or a no-activity attestation.')

ALIAS_REVIEW = 'Known COST aliases revalidated; Offload and Offloading represent the same transport charge.'
PARSER_REVIEW = ('Saved workbooks revalidated for known expense headers and blank Offloading surcharges; '
                 'prior financial snapshots preserved.')


def _parser_review_needed(batch, raw):
    """Detect rejected snapshots whose inputs now have a supported interpretation.

    This does not clear other validation issues or approve a truck. GET only
    previews; synchronize appends a new version with an explicit audit reason.
    """
    if not raw:
        return False
    from services.monthly_expense_parser import ALIASES, normalize_header
    if any(h['classification']=='unknown' and normalize_header(h['original_header']) in ALIASES
           for h in batch['header_mappings']):
        return True
    old = {(i.get('source_row'), i.get('truck')) for i in batch['issues']
           if i['code']=='invalid_source_amount'}
    if not old:
        return False
    from services.monthly_expense_dates import charge_issues
    current = {(i.get('source_row'), i.get('truck'))
               for i in charge_issues(bytes(raw['content']), batch['reporting_month'])
               if i['code']=='invalid_source_amount'}
    return bool(old - current)


def _alias_review_needed(batch, raw):
    """An old rejected draft may become calculable after exact alias support.

    Recheck, never rewrite its snapshot. Unknown charges still block; a user
    action must append an audited version before confirmation can occur.
    """
    old_count = sum(i['code'] == 'unsupported_source_charge' for i in batch['issues'])
    if not raw or not old_count:
        return False
    from services.monthly_expense_dates import charge_issues
    new_count = sum(i['code'] == 'unsupported_source_charge'
                    for i in charge_issues(bytes(raw['content']), batch['reporting_month']))
    return new_count < old_count


def latest(conn, month):
    identifier = conn.execute(select(imports.c.id).where(imports.c.reporting_month == month)
        .order_by(imports.c.version.desc()).limit(1)).scalar_one_or_none()
    return get_import(conn, identifier) if identifier else None


def raw_latest(conn, month):
    if not files.available(conn):
        return None
    identifier = conn.execute(select(files.workbooks.c.id).where(files.workbooks.c.reporting_month == month)
        .order_by(files.workbooks.c.version.desc()).limit(1)).scalar_one_or_none()
    return files.get(conn, identifier) if identifier else None


def _approved_expense_defaults(conn):
    """Reuse only unambiguous explicit expense approvals, never old ignores."""
    result=conn.execute(text("""SELECT i.id AS import_id,h AS mapping
        FROM dhl_monthly_expense_imports i,
        LATERAL jsonb_array_elements(i.header_mappings) h
        WHERE h->>'classification'='expense' AND h->>'approval_source'='administrator'
          AND h->>'approved_by' IS NOT NULL
        ORDER BY i.id DESC"""))
    from services.monthly_expense_parser import ALIASES,BUSINESS_ALIASES,IGNORED,TRUCK_HEADERS,OWNER_HEADERS,ROW_TYPE_HEADERS,INDEX_HEADERS,header_identity,category_key
    defaults={};provenance={};categories={}
    for r in result.mappings():
        h=r['mapping'];key=header_identity(h['normalized_header']);label=h['label']
        if key in IGNORED|TRUCK_HEADERS|OWNER_HEADERS|ROW_TYPE_HEADERS|INDEX_HEADERS or (key in ALIASES and key not in BUSINESS_ALIASES):continue
        try:category_key(label)
        except ValueError:continue
        categories.setdefault(key,set()).add(h['category'])
        if key not in defaults:
            defaults[key]=label;provenance[key]=dict(label=label,category=h['category'],import_id=r['import_id'],approved_by=h['approved_by'],approved_at=h['approved_at'])
    return ({k:v for k,v in defaults.items() if len(categories[k])==1},
            {k:v for k,v in provenance.items() if len(categories[k])==1})


def synchronize(conn, month, actor, *, expected_report_id, expected_raw_id,
                content=None, filename=None, mappings=None, no_activity=None,accept_cent_differences=None):
    """Idempotent autosave; never mutate a previous snapshot or issue a PDF.

    The system review describes mechanical validation, not an administrator's
    completeness approval. Existing _build/confirm_truck validate each source
    manifest and every blocking issue again before an individual confirmation.
    """
    if month.day != 1:
        raise ValueError('Choose a reporting month')
    _lock(conn, month)
    previous, raw = latest(conn, month), raw_latest(conn, month)
    if (previous['id'] if previous else None) != expected_report_id or (raw['id'] if raw else None) != expected_raw_id:
        raise VersionConflict('Saved files changed. Refresh the month and retry.')
    if content is None and previous is None:
        return None
    old = previous['decisions'] if previous else {}
    if accept_cent_differences is not None and type(accept_cent_differences) is not bool:
        raise ValueError('Explicit boolean cent-policy choice required')
    replacing = content is not None
    same_raw = bool(raw and (old.get('historical_review') or {}).get('sha256') == raw['content_sha256'])
    accept_cent=old.get('accept_cent_differences',False) if accept_cent_differences is None and same_raw else bool(accept_cent_differences)
    if accept_cent and not conn.execute(text("SELECT to_regprocedure('dhl_component_cent_admin_fee(dhl_monthly_expense_rows,jsonb)') IS NOT NULL")).scalar_one():
        raise VersionConflict('One-cent calculation policy requires migration 007 before it can be saved.')
    if accept_cent:
        from services.dhl_revenue_policy import payout_transport
        candidate=payout_transport(bytes(raw['content']),month,accept_cent_differences=True) if raw else None
        if not candidate or not any(i['code']=='source_cent_difference_calculated' for i in candidate['issues']):
            raise ValueError('No eligible one-cent DIST differences were found in the saved workbook.')
    alias_review = bool(previous and same_raw and _alias_review_needed(previous, raw))
    parser_review = bool(previous and same_raw and _parser_review_needed(previous, raw))
    from services.monthly_expense_persistence import policy_for_review
    source_policy=policy_for_review(files.resolve_review(conn,files.reference(raw),month),month,accept_cent_differences=accept_cent,
        source_reconciliation='legacy' if accept_cent_differences is True else 'auto') if raw else None
    policy_upgrade=bool(previous and raw and previous['calculation_policy']!=source_policy)
    defaults,reused=_approved_expense_defaults(conn) if not previous and mappings is None else ({},old.get('reused_category_mappings',{}))
    options = dict(
        approved_mappings=mappings if mappings is not None else old.get('approved_mappings', {}) if previous else defaults,
        reused_category_mappings=reused,
        # A replacement workbook is the whole expense source; never carry old
        # manual cell overrides or accumulate earlier deductions.
        corrections={},
        verified_no_activity=no_activity if no_activity is not None else (old.get('verified_no_activity', {}) if not replacing and same_raw else {}),
        source_verification=SYSTEM_REVIEW if raw else '',
        historical_review=files.reference(raw) if raw else None,
        date_dispositions=old.get('date_dispositions', {}) if same_raw else {},
        reason=('Saved workbook calculations; pending individual administrator confirmation'
                + ('; ' + ALIAS_REVIEW if alias_review else '')),
        previous_version_id=previous['id'] if previous else None,
        accept_cent_differences=accept_cent,
        source_reconciliation='legacy' if accept_cent_differences is True else 'auto',
    )
    if policy_upgrade:options['reason']+='; New source format calculation policy; prior snapshots preserved'
    if parser_review:options['reason']+='; '+PARSER_REVIEW
    if previous and old.get('expense_parser_revision')!='structure-v4':options['reason']+='; Workbook structure validation refreshed; historical snapshots preserved'
    if accept_cent and source_policy.get('version')=='monthly-expenses-v4-components-cent':options['reason']+='; Administrator selected calculated AMOUNT plus SURCHARGE for DIST differences of at most KES 0.01; original source retained'
    import hashlib
    if previous and raw and old.get('expense_parser_revision')=='structure-v4' and old.get('source_verification') and same_raw and not old.get('corrections') and not alias_review and not parser_review and not policy_upgrade:
        _, fingerprint = _sources(conn, month)
        incoming = content if replacing else bytes(previous['source_content'])
        if (hashlib.sha256(incoming).hexdigest() == previous['file_sha256']
            and fingerprint == previous['dhl_source_fingerprint']
            and options['approved_mappings'] == old.get('approved_mappings', {})
            and accept_cent==old.get('accept_cent_differences',False)
            and options['verified_no_activity'] == old.get('verified_no_activity', {})):
            return previous
    # Do not manufacture a new version on refresh if the same workbook,
    # decisions and source fingerprint are already saved.
    try:
        return create_draft(conn, content if replacing else bytes(previous['source_content']), month,
            filename if replacing else previous['original_filename'], actor, **options)
    except DuplicateUpload as duplicate:
        if previous and duplicate.existing_id == previous['id']:
            return previous
        # An older duplicate cannot silently become the active source, nor may
        # the UI claim that it replaced the latest workbook when nothing changed.
        raise VersionConflict('This workbook and review choices already exist in an earlier financial version. '
                              'No files or figures changed; review the saved history before correcting the source.') from None


def state(conn, month):
    if month.day != 1:
        raise ValueError('Choose a reporting month')
    metadata = files.month_files(conn, month)
    batch = latest(conn, month)
    raw = raw_latest(conn, month)
    if batch and raw and batch['status'] == 'draft':
        _, fingerprint = _sources(conn, month)
        old = batch['decisions']
        from services.monthly_expense_persistence import policy_for_review
        policy_upgrade=batch['calculation_policy']!=policy_for_review(files.resolve_review(conn,files.reference(raw),month),month,accept_cent_differences=old.get('accept_cent_differences',False))
        if policy_upgrade or old.get('expense_parser_revision')!='structure-v4' or not old.get('source_verification') or (old.get('historical_review') or {}).get('sha256') != raw['content_sha256'] or fingerprint != batch['dhl_source_fingerprint'] or old.get('corrections') or _alias_review_needed(batch, raw) or _parser_review_needed(batch, raw):
            # GET is strictly read-only. Old drafts can display an automatic
            # preview; only a user upload/review/issue action appends a draft.
            batch = preview_import(conn, bytes(batch['source_content']), month, batch['uploader_id'],
                approved_mappings=old.get('approved_mappings', {}), corrections={},
                source_verification=SYSTEM_REVIEW, historical_review=files.reference(raw),
                verified_no_activity=old.get('verified_no_activity', {}) if (old.get('historical_review') or {}).get('sha256') == raw['content_sha256'] else {},
                date_dispositions=old.get('date_dispositions', {}) if (old.get('historical_review') or {}).get('sha256') == raw['content_sha256'] else {},
                reason='Read-only calculation preview from saved workbooks',
                source_reconciliation='auto',
                reused_category_mappings=old.get('reused_category_mappings',{}),
                accept_cent_differences=old.get('accept_cent_differences',False) if (old.get('historical_review') or {}).get('sha256') == raw['content_sha256'] else False)
    if raw:
        from services.dhl_revenue_policy import payout_transport
        from services.monthly_expense_dates import validate_source
        scan=payout_transport(bytes(raw['content']),month,accept_cent_differences=True)
        adjustments=[i for i in scan['issues'] if i['code']=='source_cent_difference_calculated'] if scan else []
        accepted=bool(batch and batch['decisions'].get('accept_cent_differences') and
            (batch['decisions'].get('historical_review') or {}).get('sha256')==raw['content_sha256'])
        source,_=_sources(conn,month)
        checked=accepted and not validate_source(files.resolve_review(conn,files.reference(raw),month),
            batch['decisions'].get('date_dispositions',{}),source,month,accept_cent_differences=True)
        from decimal import Decimal
        metadata['cent_difference_review']=dict(accepted=accepted,rows=adjustments,
            migration_ready=conn.execute(text("SELECT to_regprocedure('dhl_component_cent_admin_fee(dhl_monthly_expense_rows,jsonb)') IS NOT NULL")).scalar_one(),
            calculated_gross=format(sum((Decimal(t['inclusive']) for t in scan['transactions']),Decimal('0.00')),'.2f') if checked else None)
        from services.dhl_rounding_reconciliation import reconciled_transport
        inclusive_scan=reconciled_transport(bytes(raw['content']),month)
        using_inclusive=bool(batch and batch['decisions'].get('source_reconciliation_policy'))
        inclusive_verified=using_inclusive and not validate_source(files.resolve_review(conn,files.reference(raw),month),
            batch['decisions'].get('date_dispositions',{}),source,month,reconcile_source_rounding=True)
        metadata['source_rounding_review']=dict(
            rows=[i for i in inclusive_scan['issues'] if i['code']=='source_rounding_reconciled'] if inclusive_scan else [],
            policy='source-inclusive-reconciled-v1',transaction_limit='0.01',truck_absolute_limit='0.05',month_absolute_limit='0.25',
            migration_ready=conn.execute(text("SELECT to_regprocedure('dhl_inclusive_rounding_admin_fee(dhl_monthly_expense_rows,jsonb)') IS NOT NULL")).scalar_one(),
            source_verified=bool(inclusive_verified),
            gross=format(sum((Decimal(t['inclusive']) for t in inclusive_scan['transactions']),Decimal('0.00')),'.2f') if inclusive_verified else None)
    # Revenue-only trucks must remain visible; missing expense rows are not an
    # instruction to fabricate zero expenses or drop their revenue.
    from services.monthly_expense_persistence import _plate
    from services.monthly_expense_parser import money
    from services.monthly_expense_dates import validate_source, inspect_source
    from decimal import Decimal
    source, _ = _sources(conn, month)
    roster = {r['normalized_plate'] for r in batch['rows']} if batch else set()
    source_plates = {_plate(r['truck_plate']) for r in source}
    if raw:
        _, manifest = inspect_source(bytes(raw['content']), month)
        source_plates.update(key[1] for key in manifest)
    vehicles = list(conn.execute(text('''SELECT v.id, v.plate_number, v.owner_id, v.size,
        u.name AS owner_name FROM vehicles v LEFT JOIN users u ON u.id = v.owner_id''')).mappings())
    review = files.resolve_review(conn, files.reference(raw), month) if raw else None
    missing = []
    for plate in sorted(source_plates - roster):
        records = [r for r in source if _plate(r['truck_plate']) == plate]
        accept_cent=bool(batch and batch['decisions'].get('accept_cent_differences'))
        inclusive=bool(batch and batch['decisions'].get('source_reconciliation_policy'))
        valid = bool(review and not validate_source(review, {}, source, month, target_plate=plate,accept_cent_differences=accept_cent,reconcile_source_rounding=inclusive))
        gross = sum((money(r['distribution_cost']) + money(r['offloading_cost']) for r in records), Decimal('0.00')) if valid else None
        if valid and accept_cent:
            gross=sum((Decimal(t['inclusive']) for t in scan['transactions'] if t['plate']==plate),Decimal('0.00'))
        matches = [dict(v) for v in vehicles if _plate(v['plate_number']) == plate]
        vehicle = matches[0] if len(matches) == 1 else {}
        missing.append(dict(normalized_plate=plate, id=None, vehicle_id=vehicle.get('id'), vehicle_owner_snapshot=vehicle,
            gross=gross, operating_expenses=None, commission=None, commission_base=None, net_payable=None,
            deductions={}, issues=[dict(code='expense_row_missing', message='This truck is missing from the expense workbook.', blocking=True)],
            dhl_source_snapshot=records))
    metadata['unmatched_trucks'] = missing
    return metadata, batch
