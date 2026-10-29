"""Admin-only monthly import API, mounted alongside the legacy DHL router.

Router factory allows isolated dependency injection without importing production
DB/auth on module import. Production uses the existing require_role('admin').
"""
from __future__ import annotations

import json
from datetime import date
from typing import Literal
from zipfile import BadZipFile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, NoResultFound, OperationalError, ProgrammingError
from openpyxl.utils.exceptions import InvalidFileException

from services.monthly_expense_models import imports
from services.monthly_expense_persistence import (
    preview_import, create_draft, get_import, confirm_import, list_versions,
    _sources, DuplicateUpload, SourceChanged, VersionConflict, ValidationBlocked,
)
from services.monthly_expense_reconciliation import review_historical_adjustments
from services.monthly_expense_parser import validate_xlsx_envelope
from services.monthly_expense_reports import report_view, export_xlsx, export_pdf, warnings

MAX_UPLOAD = 20_000_000


class DateDisposition(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    action: Literal['exclude_from_period']
    reason: StrictStr = Field(min_length=1, max_length=2000)


class ImportOptions(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    approved_mappings: dict[str, StrictStr | None] = Field(default_factory=dict)
    corrections: dict[str, StrictStr] = Field(default_factory=dict)
    verified_no_activity: dict[str, StrictStr] = Field(default_factory=dict)
    source_verification: StrictStr = ''
    reason: StrictStr = ''
    previous_version_id: int | None = Field(None, gt=0)
    sheet_name: StrictStr | None = None
    reference_columns: dict[str, StrictStr] = Field(default_factory=dict)
    reference_verification: StrictStr = ''
    date_dispositions: dict[str, DateDisposition] = Field(default_factory=dict)


def get_connection():
    # Lazy import: unit/API tests never load the production connection module.
    from database import engine
    try:
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL lock_timeout = '5s'"))
            conn.execute(text("SET LOCAL statement_timeout = '30s'"))
            yield conn
    except OperationalError as exc:
        raise HTTPException(503, 'Database unavailable or busy; retry the request') from exc


def _run(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except DuplicateUpload as exc:
        raise HTTPException(409, {'code': 'duplicate_import', 'existing_import_id': exc.existing_id}) from exc
    except (SourceChanged, VersionConflict) as exc:
        raise HTTPException(409, {'code': type(exc).__name__, 'message': str(exc)}) from exc
    except NoResultFound as exc:
        raise HTTPException(404, 'Monthly expense import not found') from exc
    except (ValidationBlocked, ValueError, BadZipFile, InvalidFileException, KeyError, SyntaxError) as exc:
        raise HTTPException(422, {'code': 'invalid_import', 'message': str(exc)}) from exc
    except IntegrityError as exc:
        raise HTTPException(409, 'Import integrity conflict; refresh and review the report') from exc
    except OperationalError as exc:
        raise HTTPException(503, 'Database unavailable or busy; retry the request') from exc
    except ProgrammingError as exc:
        if getattr(exc.orig, 'sqlstate', None) == '42P01':
            raise HTTPException(503, {'code': 'migration_required', 'message': 'Monthly expense storage is unavailable; review the approved migration prerequisite'}) from exc
        raise


def _upload(file):
    if not file.filename or not file.filename.lower().endswith('.xlsx'):
        raise HTTPException(415, 'Only XLSX workbooks are supported')
    content = file.file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise HTTPException(413, 'Workbook exceeds 20 MB')
    if not content:
        raise HTTPException(422, 'Workbook is empty')
    _run(validate_xlsx_envelope, content)
    return content


def _options(raw):
    if len(raw) > 200_000:
        raise HTTPException(413, 'Import options are too large')
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
        return ImportOptions.model_validate(value).model_dump()
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, 'Invalid import options; corrections must be decimal strings and financial totals are not accepted') from exc


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON option key')
        result[key] = value
    return result


def _view(conn, batch, **filters):
    versions = _run(list_versions, conn, batch['reporting_month'])
    view = _run(report_view, batch, versions, **filters)
    from services.truck_confirmations import presentation
    from services.monthly_expense_reports import decimal_json
    states=_run(presentation,conn,batch)
    if states is not None:
        for row in view['rows']:
            row['truck_confirmation']=decimal_json(states['rows'][row['id']])
        view['truck_confirmation_summary']=decimal_json({k:v for k,v in states.items() if k!='rows'})
        if any(s['current'] and s['current']['method']=='truck' and s['current']['expense_row_id']!=row_id
               for row_id,s in states['rows'].items()):
            view['can_confirm']=False
        view['issues']=list(view['issues'])+[{'code':'truck_confirmation_scope','blocking':False,'cell':None,
            'message':'Truck confirmations are version-specific. Review earlier truck approvals before whole-month corrections. Monthly totals describe this selected snapshot, not a payment ledger or a total of current truck approvals across versions.'}]
    view['review_warnings'] = [{'scope': scope, 'code': code, 'message': message}
                               for scope, code, message in warnings(view)]
    return view


def create_router(connection_dependency, admin_dependency):
    def no_cache(response: Response):
        response.headers['Cache-Control'] = 'no-store'

    router = APIRouter(prefix='/dhl-reports', tags=['Monthly Expense Reports'],
                       dependencies=[Depends(no_cache)])

    @router.post('/expense-imports/preview')
    def preview(file: UploadFile = File(...), month: date = Form(...), options: str = Form('{}'),
                raw_trips_file: UploadFile | None = File(None),
                actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        content = _upload(file)
        config = _options(options)
        if raw_trips_file is not None:
            config['historical_review'] = _run(review_historical_adjustments, _upload(raw_trips_file), month)
        return _view(conn, _run(preview_import, conn, content, month, actor.id, **config))

    @router.post('/expense-imports', status_code=201)
    def save(file: UploadFile = File(...), month: date = Form(...), options: str = Form('{}'),
             raw_trips_file: UploadFile | None = File(None),
             actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        content = _upload(file)
        config = _options(options)
        if raw_trips_file is not None:
            config['historical_review'] = _run(review_historical_adjustments, _upload(raw_trips_file), month)
        batch = _run(create_draft, conn, content, month, file.filename, actor.id, **config)
        return _view(conn, batch)

    @router.post('/expense-imports/{import_id}/revise')
    def revise(import_id: int, mode: Literal['preview', 'save'] = Form('preview'),
               options: str = Form('{}'), expected_file_sha256: str = Form(...),
               raw_trips_file: UploadFile | None = File(None),
               actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        original = _run(get_import, conn, import_id)
        if expected_file_sha256 != original['file_sha256']:
            raise HTTPException(409, {'code': 'VersionConflict', 'message': 'Original workbook changed; reload the saved version'})
        config = _options(options)
        if config['previous_version_id'] not in (None, import_id):
            raise HTTPException(422, 'A revision must refer to the selected saved version')
        config['previous_version_id'] = import_id
        config['historical_review'] = original['decisions'].get('historical_review')
        if raw_trips_file is not None:
            config['historical_review'] = _run(review_historical_adjustments, _upload(raw_trips_file), original['reporting_month'])
            if config['historical_review']['sha256'] != (original['decisions'].get('historical_review') or {}).get('sha256'):
                if config['date_dispositions']:
                    raise HTTPException(422, 'Review the new raw workbook before applying date decisions')
        _, live_fingerprint = _run(_sources, conn, original['reporting_month'])
        if live_fingerprint != original['dhl_source_fingerprint']:
            # Old attestations are not new evidence after a DHL replacement.
            if config['source_verification'] == original['decisions'].get('source_verification'):
                config['source_verification'] = ''
            if config['verified_no_activity'] == original['decisions'].get('verified_no_activity'):
                config['verified_no_activity'] = {}
        operation = preview_import if mode == 'preview' else create_draft
        args = (conn, bytes(original['source_content']), original['reporting_month'])
        if mode == 'save':
            args += (original['original_filename'], actor.id)
        else:
            args += (actor.id,)
        return _view(conn, _run(operation, *args, **config))

    @router.get('/expense-imports/{import_id}')
    def retrieve(import_id: int, actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        return _view(conn, _run(get_import, conn, import_id))

    @router.post('/expense-imports/{import_id}/confirm')
    def confirm(import_id: int, actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        return _view(conn, _run(confirm_import, conn, import_id, actor.id))

    @router.get('/monthly-net-summary')
    def summary(month: date, version: int | None = Query(None, gt=0),
                owner_id: int | None = Query(None, gt=0), vehicle_id: int | None = Query(None, gt=0),
                actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        if month.day != 1:
            raise HTTPException(422, 'Reporting month must be its first day')
        query = select(imports.c.id).where(imports.c.reporting_month == month)
        query = query.where(imports.c.status == 'confirmed') if version is None else query.where(imports.c.version == version)
        identifier = _run(lambda: conn.execute(query).scalar_one())
        return _view(conn, _run(get_import, conn, identifier), owner_id=owner_id, vehicle_id=vehicle_id)

    @router.get('/expense-imports/{import_id}/export')
    def export(import_id: int, format: Literal['xlsx', 'pdf'] = 'xlsx',
               actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        view = _view(conn, _run(get_import, conn, import_id))
        content = _run(export_xlsx if format == 'xlsx' else export_pdf, view)
        filename = f"smithsons_monthly_transport_{view['reporting_month'][:7]}_v{view['version']}.{format}"
        media = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if format == 'xlsx' else 'application/pdf'
        return Response(content, media_type=media,
                        headers={'Content-Disposition': f'attachment; filename="{filename}"', 'Cache-Control': 'no-store'})

    return router
