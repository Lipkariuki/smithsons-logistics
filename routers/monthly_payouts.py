"""Admin-only autosave facade over the existing immutable monthly services."""
from datetime import date
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from routers.monthly_expense_reports import _run, _upload, _view
from services import monthly_payouts as payouts
from services.monthly_expense_reports import decimal_json, totals
from services.monthly_reporting_scope import reporting_read_scope


class SyncRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_report_id: int | None = Field(None, gt=0)
    expected_raw_id: int | None = Field(None, gt=0)
    mappings: dict[str, StrictStr | None] | None = None
    no_activity: dict[str, StrictStr] | None = None


def create_router(connection_dependency, admin_dependency):
    def no_cache(response: Response):
        response.headers['Cache-Control'] = 'no-store'

    router = APIRouter(prefix='/dhl-reports/monthly-payouts', tags=['Monthly Payouts'], dependencies=[Depends(no_cache)])

    def view(conn, month):
        with reporting_read_scope():
            return render_month(conn, month)

    def render_month(conn, month):
        metadata, batch = _run(payouts.state, conn, month)
        from services.truck_confirmations import presentation
        saved = _run(payouts.latest, conn, month)
        states = _run(presentation, conn, saved) if saved else None
        report = _view(conn, batch) if batch else None
        if report:
            # A revenue-only truck must not disappear from the monthly control
            # totals or make an incomplete month appear fully calculated.
            report['totals'] = decimal_json(totals([*batch['rows'], *metadata['unmatched_trucks']]))
            from services.monthly_statement_documents import transport_components
            for row in report['rows']:
                if row['gross'] is not None:
                    original = next(r for r in batch['rows'] if r['normalized_plate'] == row['normalized_plate'])
                    dist, off = _run(transport_components, original)
                    row['revenue_breakdown'] = dict(distribution=format(dist,'.2f'), offloading=format(off,'.2f'))
        return dict(files=decimal_json(metadata), report=report,
                    approvals=decimal_json(states['current_approvals']) if states else [])

    @router.get('/{month}')
    def get_month(month: date, actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        return view(conn, month)

    @router.post('/{month}/sync')
    def sync(month: date, payload: SyncRequest, actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        _run(payouts.synchronize, conn, month, actor.id, **payload.model_dump())
        return view(conn, month)

    @router.post('/{month}/expenses')
    def expenses(month: date, file: UploadFile = File(...), expected_report_id: int | None = Form(None),
                 expected_raw_id: int | None = Form(None), actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        _run(payouts.synchronize, conn, month, actor.id, content=_upload(file), filename=file.filename,
             expected_report_id=expected_report_id, expected_raw_id=expected_raw_id)
        return view(conn, month)

    return router
