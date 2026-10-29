"""Transactional Phase 2 persistence; caller supplies an explicit SQLAlchemy Connection.

No global engine, legacy models, API or startup registration. Call inside
engine.begin(); all methods flush through that connection and never commit.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
import unicodedata

from sqlalchemy import select, insert, update, text, func

from services.monthly_expense_models import imports, rows
from services.monthly_expense_parser import parse_expenses, OPTIONAL_CATEGORY, money
from services.monthly_expense_calculations import RevenueEvidence, RevenueStatus, calculate_monthly_expenses
from services.monthly_expense_reconciliation import validate_reference_columns
from services.monthly_expense_dates import validate_source

POLICY = {'version': 'monthly-expenses-v2', 'parser_version': 'flexible-xlsx-v2',
          'blank_expenses': 'zero_with_audit', 'absent_categories': 'zero_no_carry_forward',
          'currency': 'KES', 'rounding': 'ROUND_HALF_UP', 'scale': 2,
          'commission_rate': '0.07', 'positive_base_only': True}


class ValidationBlocked(ValueError):
    pass


class SourceChanged(ValueError):
    pass


class VersionConflict(ValueError):
    pass


class DuplicateUpload(ValueError):
    def __init__(self, existing_id):
        self.existing_id = existing_id
        super().__init__(f'Duplicate workbook/decisions: existing import {existing_id}')


def _plate(value):
    return ''.join(unicodedata.normalize('NFKC', value or '').split()).upper()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _lock(conn, month):
    if not conn.in_transaction():
        raise ValueError('Use an explicit transaction: with engine.begin() as connection')
    # Fixed namespace plus a month key; held until caller commits/rolls back.
    conn.execute(text('SELECT pg_advisory_xact_lock(736281, :month)'),
                 {'month': month.year * 12 + month.month})


def _sources(conn, month):
    # Existing importer does not participate in advisory locks. A short SHARE
    # lock prevents its DELETE/INSERT from racing this source snapshot.
    conn.execute(text('LOCK TABLE dhl_orders IN SHARE MODE'))
    end = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    result = conn.execute(text('''SELECT id, ref_no, date, truck_plate, vehicle_id,
        distribution_cost, offloading_cost, total_revenue FROM dhl_orders
        WHERE date >= :start AND date < :end ORDER BY id'''), {'start': month, 'end': end})
    snapshot = []
    for record in result.mappings():
        item = dict(record)
        item['date'] = item['date'].isoformat()
        for key in ('distribution_cost', 'offloading_cost', 'total_revenue'):
            # Float boundary is explicit and preserves the legacy source representation.
            item[key] = str(item[key]) if item[key] is not None else None
        snapshot.append(item)
    return snapshot, _hash(snapshot)


def _build(conn, content, month, decisions, actor, audit_time):
    preview = parse_expenses(content, month, sheet_name=decisions['sheet_name'],
                             approved_mappings=decisions['approved_mappings'], corrections=decisions['corrections'])
    source, fingerprint = _sources(conn, month)
    # Read-only legacy identity lookup. No ORM relationships or payout services.
    vehicles = list(conn.execute(text('''SELECT v.id, v.plate_number, v.owner_id, v.size,
          u.name AS owner_name FROM vehicles v LEFT JOIN users u ON u.id = v.owner_id''')).mappings())
    proofs = decisions['verified_no_activity']
    if set(proofs) - {row.plate for row in preview.rows}:
        raise ValueError('No-activity verification must refer to an imported truck')
    header_mappings = [dict(asdict(h), approved_by=actor if h.approval_source == 'administrator' else None,
                            approved_at=audit_time if h.approval_source == 'administrator' else None)
                       for h in preview.headers]
    payloads = []
    for row in preview.rows:
        issues = [asdict(i) for i in row.issues]
        matches = [dict(v) for v in vehicles if _plate(v['plate_number']) == row.plate]
        vehicle = matches[0] if len(matches) == 1 else {}
        if len(matches) != 1:
            issues.append({'code': 'vehicle_unmatched' if not matches else 'vehicle_ambiguous',
                           'message': 'Explicit vehicle matching required', 'cell': None, 'blocking': True})
        records = [item for item in source if _plate(item['truck_plate']) == row.plate]
        reason = proofs.get(row.plate, '')
        verification = decisions['source_verification']
        if reason and records:
            issues.append({'code': 'no_activity_conflict', 'message': 'DHL records exist for a no-activity claim',
                           'cell': None, 'blocking': True})
        gross = None
        evidence = ''
        if not verification:
            status = RevenueStatus.INCOMPLETE if source else RevenueStatus.UNIMPORTED
        elif records:
            try:
                gross = sum((money(item['total_revenue']) for item in records), Decimal('0.00'))
                status = RevenueStatus.DHL_RECORDS
                evidence = verification + '; source=' + fingerprint
            except ValueError:
                status = RevenueStatus.INCOMPLETE
        elif reason:
            status = RevenueStatus.VERIFIED_NO_ACTIVITY
            gross = Decimal('0.00')
            evidence = verification + '; no_activity=' + reason
        else:
            status = RevenueStatus.MISSING if source else RevenueStatus.UNIMPORTED
        deductions = {}
        for key, amount in row.expenses.items():
            header = next((h for h in preview.headers if h.category == key), None)
            deductions[key] = {'amount': None if amount is None else format(amount, '.2f'),
                               'resolution': ('blank_to_zero' if header and row.source_values.get(f'{_column(header.column)}{row.row_number}', {}).get('interpretation') == 'blank_to_zero'
                                              else 'source') if header else 'absent_optional_category',
                               'label': header.label if header else 'Kasarani & KSM Fuel',
                               'original_header': header.original_header if header else None,
                               'source_cell': f'{_column(header.column)}{row.row_number}' if header else None}
        audit = {}
        for cell, value in row.source_values.items():
            audit[cell] = dict(value)
            if 'approved_correction' in value:
                audit[cell].update(approved_by=actor, approved_at=audit_time, reason=decisions['reason'])
        financial = {'gross': gross, 'operating_expenses': None, 'commission_base': None,
                     'commission': None, 'net_payable': None}
        if row.ready:
            result = calculate_monthly_expenses(row, month, RevenueEvidence(row.plate, month, status, gross, evidence))
            for key in financial:
                financial[key] = getattr(result, key)
            issues += [{'code': warning, 'message': warning, 'cell': None, 'blocking': False} for warning in result.warnings]
            if not result.ready:
                issues.append({'code': 'revenue_unverified', 'message': 'DHL completeness or no-activity verification required',
                               'cell': None, 'blocking': True})
        if not row.ready:
            issues.append({'code': 'preview_unresolved', 'message': 'Resolve workbook/header/cell validation',
                           'cell': None, 'blocking': True})
        payloads.append(dict(source_worksheet=preview.sheet, source_row=row.row_number,
                             original_plate=row.original_plate, normalized_plate=row.plate,
                             vehicle_id=vehicle.get('id'), vehicle_owner_snapshot=vehicle,
                             deductions=deductions, cell_audit=audit, dhl_source_snapshot=records,
                             revenue_status=status.value, revenue_evidence=evidence, issues=issues, **financial))
    batch_issues = [asdict(i) for i in preview.issues]
    batch_issues += validate_source(decisions.get('historical_review'), decisions.get('date_dispositions', {}), source, month)
    if not decisions['source_verification']:
        batch_issues.append({'code': 'source_unverified', 'message': 'Month completeness verification required',
                             'cell': None, 'blocking': True})
    assumptions = [dict(asdict(i), amount='0.00')
                   for i in preview.issues if i.code in {'optional_category_absent', 'category_absent_zero'}]
    return dict(header_mappings=header_mappings, assumptions=assumptions, issues=batch_issues), payloads, fingerprint


def _column(number):
    value = ''
    while number:
        number, remainder = divmod(number - 1, 26)
        value = chr(65 + remainder) + value
    return value


def _prepare_decisions(approved_mappings=None, corrections=None, verified_no_activity=None,
                       source_verification='', reason='', sheet_name=None,
                       reference_columns=None, reference_verification='', historical_review=None, date_dispositions=None):
    proofs = {}
    for plate, evidence in (verified_no_activity or {}).items():
        key = _plate(plate)
        if key in proofs or not evidence.strip():
            raise ValueError('Unique truck and nonempty no-activity evidence required')
        proofs[key] = evidence
    decisions = dict(approved_mappings=dict(approved_mappings or {}),
                     corrections={k: str(v) if isinstance(v, Decimal) else v for k, v in (corrections or {}).items()},
                     verified_no_activity=proofs, source_verification=source_verification.strip(),
                     reason=reason, sheet_name=sheet_name)
    validate_reference_columns(reference_columns or {}, reference_verification)
    if reference_columns:
        decisions.update(reference_columns=reference_columns, reference_verification=reference_verification,
                         reference_policy='manual-reference-v1')
    if historical_review is not None:
        decisions['historical_review'] = historical_review
    if date_dispositions:
        decisions['date_dispositions'] = date_dispositions
    return decisions


def create_draft(conn, content: bytes, month: date, filename: str, uploader_id: int, *,
                 approved_mappings=None, corrections=None, verified_no_activity=None,
                 source_verification='', reason='', previous_version_id=None, sheet_name=None,
                 reference_columns=None, reference_verification='', historical_review=None, date_dispositions=None):
    if month.day != 1 or uploader_id <= 0:
        raise ValueError('Explicit month and valid uploader required')
    if (approved_mappings or corrections or previous_version_id is not None) and not reason.strip():
        raise ValueError('Mapping/correction/new-version decisions require an audit reason')
    _lock(conn, month)
    sha = hashlib.sha256(content).hexdigest()
    if previous_version_id is None:
        duplicate = conn.execute(select(imports.c.id).where(imports.c.reporting_month == month,
                                                            imports.c.file_sha256 == sha)).scalar()
        if duplicate is not None:
            raise DuplicateUpload(duplicate)
    else:
        predecessor = conn.execute(select(imports).where(imports.c.id == previous_version_id)).mappings().first()
        if predecessor is None or predecessor['reporting_month'] != month:
            raise ValueError('Previous version must belong to this month')
    decisions = _prepare_decisions(approved_mappings, corrections, verified_no_activity,
        source_verification, reason, sheet_name, reference_columns, reference_verification, historical_review, date_dispositions)
    now = datetime.now(timezone.utc)
    batch, payloads, fingerprint = _build(conn, content, month, decisions, uploader_id, now.isoformat())
    decisions_sha = _hash(decisions)
    duplicate = conn.execute(select(imports.c.id).where(imports.c.reporting_month == month,
        imports.c.file_sha256 == sha, imports.c.decisions_sha256 == decisions_sha,
        imports.c.dhl_source_fingerprint == fingerprint)).scalar()
    if duplicate is not None:
        raise DuplicateUpload(duplicate)
    version = conn.execute(select(func.coalesce(func.max(imports.c.version), 0) + 1)
                           .where(imports.c.reporting_month == month)).scalar_one()
    import_id = conn.execute(insert(imports).values(reporting_month=month, version=version, status='draft',
        original_filename=filename, file_sha256=sha, source_content=content,
        decisions=decisions, decisions_sha256=decisions_sha, dhl_source_fingerprint=fingerprint,
        source_verification=decisions['source_verification'], calculation_policy=POLICY,
        uploader_id=uploader_id, created_at=now, previous_version_id=previous_version_id, **batch)
        .returning(imports.c.id)).scalar_one()
    if payloads:
        conn.execute(insert(rows), [dict(import_id=import_id, **row) for row in payloads])
    return get_import(conn, import_id)


def preview_import(conn, content, month, actor_id, **options):
    """Read-only preview using the exact parser/calculation snapshot build path."""
    if month.day != 1 or actor_id <= 0:
        raise ValueError('Explicit month and valid actor required')
    if (options.get('approved_mappings') or options.get('corrections')) and not options.get('reason', '').strip():
        raise ValueError('Mapping/correction decisions require an audit reason')
    options.pop('previous_version_id', None)
    decisions = _prepare_decisions(**options)
    now = datetime.now(timezone.utc)
    batch, payloads, fingerprint = _build(conn, content, month, decisions, actor_id, now.isoformat())
    return dict(reporting_month=month, version=None, status='preview', decisions=decisions,
                source_content=content, dhl_source_fingerprint=fingerprint, rows=payloads,
                calculation_policy=POLICY, uploader_id=actor_id, created_at=now, **batch)


def get_import(conn, import_id):
    batch = conn.execute(select(imports).where(imports.c.id == import_id)).mappings().one()
    detail = dict(batch)
    detail['rows'] = [dict(row) for row in conn.execute(select(rows).where(rows.c.import_id == import_id)
                                                       .order_by(rows.c.source_row)).mappings()]
    return detail


def list_versions(conn, month):
    return [dict(row) for row in conn.execute(select(imports.c.id, imports.c.version, imports.c.status,
        imports.c.previous_version_id, imports.c.created_at, imports.c.confirmed_at)
        .where(imports.c.reporting_month == month).order_by(imports.c.version)).mappings()]


def confirm_import(conn, import_id, confirmer_id):
    if confirmer_id <= 0:
        raise ValueError('Valid confirmer required')
    month = conn.execute(select(imports.c.reporting_month).where(imports.c.id == import_id)).scalar_one()
    _lock(conn, month)
    conn.execute(select(imports.c.id).where(imports.c.id == import_id).with_for_update()).scalar_one()
    batch = get_import(conn, import_id)
    if batch['reporting_month'] != month:
        raise VersionConflict('Draft month changed during confirmation')
    if batch['status'] != 'draft':
        raise VersionConflict('Only drafts can be confirmed')
    if batch['calculation_policy'] != POLICY:
        raise ValidationBlocked('Unsupported calculation policy; create a new version')
    if hashlib.sha256(bytes(batch['source_content'])).hexdigest() != batch['file_sha256'] or _hash(batch['decisions']) != batch['decisions_sha256']:
        raise ValidationBlocked('Workbook or decision checksum changed')
    expected, expected_rows, fingerprint = _build(conn, bytes(batch['source_content']), month,
        batch['decisions'], batch['uploader_id'], batch['created_at'].isoformat())
    if fingerprint != batch['dhl_source_fingerprint']:
        raise SourceChanged('DHL data changed since preview; create and review a new version')
    if batch['source_verification'] != batch['decisions']['source_verification']:
        raise ValidationBlocked('Source verification changed')
    if any(batch[key] != value for key, value in expected.items()):
        raise ValidationBlocked('Stored header mapping, assumptions or validation changed')
    if len(expected_rows) != len(batch['rows']) or any(
        any(stored[key] != value for key, value in expected_row.items())
        for stored, expected_row in zip(batch['rows'], expected_rows)):
        raise ValidationBlocked('Stored row differs from parsed/calculated source; create a new version')
    if not expected_rows or any(i['blocking'] for i in expected['issues']) or any(
        i['blocking'] for row in expected_rows for i in row['issues']):
        raise ValidationBlocked('Required validation or revenue issues remain unresolved')
    from services.truck_confirmations import available, confirmations
    if available(conn):
        current_trucks=conn.execute(select(confirmations).where(confirmations.c.reporting_month==month,
            confirmations.c.status=='current',confirmations.c.method=='truck')).mappings()
        selected={r['normalized_plate']:r['id'] for r in batch['rows']}
        if any(selected.get(c['normalized_plate']) not in (None,c['expense_row_id']) for c in current_trucks):
            raise VersionConflict('Explicitly confirm truck corrections before confirming this whole-month version')
    current = conn.execute(select(imports.c.id).where(imports.c.reporting_month == month,
                                                     imports.c.status == 'confirmed')).scalar()
    if current is not None:
        ancestor = batch['previous_version_id']
        while ancestor is not None and ancestor != current:
            ancestor = conn.execute(select(imports.c.previous_version_id).where(imports.c.id == ancestor)).scalar_one()
        if ancestor != current:
            raise VersionConflict('Current confirmed version changed; review a successor version')
        conn.execute(update(imports).where(imports.c.id == current).values(status='superseded'))
    conn.execute(update(imports).where(imports.c.id == import_id, imports.c.status == 'draft')
                 .values(status='confirmed', confirmer_id=confirmer_id, confirmed_at=datetime.now(timezone.utc)))
    return get_import(conn, import_id)
