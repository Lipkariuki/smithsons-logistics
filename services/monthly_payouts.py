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


def synchronize(conn, month, actor, *, expected_report_id, expected_raw_id,
                content=None, filename=None, mappings=None, no_activity=None):
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
    replacing = content is not None
    same_raw = bool(raw and (old.get('historical_review') or {}).get('sha256') == raw['content_sha256'])
    alias_review = bool(previous and same_raw and _alias_review_needed(previous, raw))
    options = dict(
        approved_mappings=mappings if mappings is not None else old.get('approved_mappings', {}),
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
    )
    import hashlib
    if previous and raw and old.get('source_verification') and same_raw and not old.get('corrections') and not alias_review:
        _, fingerprint = _sources(conn, month)
        incoming = content if replacing else bytes(previous['source_content'])
        if (hashlib.sha256(incoming).hexdigest() == previous['file_sha256']
            and fingerprint == previous['dhl_source_fingerprint']
            and options['approved_mappings'] == old.get('approved_mappings', {})
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
        if not old.get('source_verification') or (old.get('historical_review') or {}).get('sha256') != raw['content_sha256'] or fingerprint != batch['dhl_source_fingerprint'] or old.get('corrections') or _alias_review_needed(batch, raw):
            # GET is strictly read-only. Old drafts can display an automatic
            # preview; only a user upload/review/issue action appends a draft.
            batch = preview_import(conn, bytes(batch['source_content']), month, batch['uploader_id'],
                approved_mappings=old.get('approved_mappings', {}), corrections={},
                source_verification=SYSTEM_REVIEW, historical_review=files.reference(raw),
                verified_no_activity=old.get('verified_no_activity', {}) if (old.get('historical_review') or {}).get('sha256') == raw['content_sha256'] else {},
                date_dispositions=old.get('date_dispositions', {}) if (old.get('historical_review') or {}).get('sha256') == raw['content_sha256'] else {},
                reason='Read-only calculation preview from saved workbooks')
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
        valid = bool(review and not validate_source(review, {}, source, month, target_plate=plate))
        gross = sum((money(r['distribution_cost']) + money(r['offloading_cost']) for r in records), Decimal('0.00')) if valid else None
        matches = [dict(v) for v in vehicles if _plate(v['plate_number']) == plate]
        vehicle = matches[0] if len(matches) == 1 else {}
        missing.append(dict(normalized_plate=plate, id=None, vehicle_id=vehicle.get('id'), vehicle_owner_snapshot=vehicle,
            gross=gross, operating_expenses=None, commission=None, commission_base=None, net_payable=None,
            deductions={}, issues=[dict(code='expense_row_missing', message='This truck is missing from the expense workbook.', blocking=True)],
            dhl_source_snapshot=records))
    metadata['unmatched_trucks'] = missing
    return metadata, batch
