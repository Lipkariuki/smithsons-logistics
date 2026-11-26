"""Admin-only autosave facade over the existing immutable monthly services."""
from datetime import date
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, StrictStr, StrictBool
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
    accept_cent_differences: StrictBool | None = None


def create_router(connection_dependency, admin_dependency):
    def no_cache(response: Response):
        response.headers['Cache-Control'] = 'no-store'

    router = APIRouter(prefix='/dhl-reports/monthly-payouts', tags=['Monthly Payouts'], dependencies=[Depends(no_cache)])

    def view(conn, month,lightweight=False):
        with reporting_read_scope():
            return render_month(conn, month,lightweight)

    def render_month(conn, month,lightweight=False):
        metadata, batch = _run(payouts.state, conn, month,latest_files_only=lightweight)
        report = _view(conn, batch) if batch else None
        approvals=(report or {}).get('truck_confirmation_summary',{}).get('current_approvals')
        if approvals is None:
            from sqlalchemy import select
            from services.truck_confirmations import confirmations,available
            from services.monthly_expense_models import rows
            query=select(confirmations,rows.c.import_id,rows.c.vehicle_owner_snapshot['owner_name'].astext.label('owner_name'),
                rows.c.gross,rows.c.operating_expenses,rows.c.commission,rows.c.net_payable).join(rows,rows.c.id==confirmations.c.expense_row_id).where(
                    confirmations.c.reporting_month==month,confirmations.c.status=='current')
            approvals=[dict(r) for r in conn.execute(query).mappings()] if available(conn) else []
        if report:
            # A revenue-only truck must not disappear from the monthly control
            # totals or make an incomplete month appear fully calculated.
            report['totals'] = decimal_json(totals([*batch['rows'], *metadata['unmatched_trucks']]))
            from services.monthly_statement_documents import transport_components
            for row in report['rows']:
                if row.get('truck_confirmation',{}).get('record'):row['financial_status']='confirmed'
                elif row.get('truck_confirmation') and row['financial_status']=='ready' and not row['truck_confirmation']['can_confirm']:row['financial_status']='blocked'
                if row['gross'] is not None:
                    original = next(r for r in batch['rows'] if r['normalized_plate'] == row['normalized_plate'])
                    dist, off = _run(transport_components, original)
                    row['revenue_breakdown'] = dict(distribution=format(dist,'.2f'), offloading=format(off,'.2f'))
                    transport=original.get('cell_audit',{}).get('_dhl_transport')
                    if transport:
                        row['revenue_breakdown'].update(distribution=transport['distribution'],surcharge=transport['surcharge'])
                        if transport.get('rounding_difference') is not None:row['revenue_breakdown']['rounding_difference']=transport['rounding_difference']
                elif row.get('provisional_financial'):
                    original=next(r for r in batch['rows'] if r['normalized_plate']==row['normalized_plate'])
                    t=original.get('cell_audit',{}).get('_dhl_transport')
                    if t:
                        from decimal import Decimal
                        row['revenue_breakdown']=dict(distribution=t['distribution'],surcharge=t['surcharge'],offloading=t['offloading'],
                            rounding_difference=format(Decimal(t['gross'])-Decimal(t['distribution'])-Decimal(t['surcharge'])-Decimal(t['offloading']),'.2f'))
        return dict(files=decimal_json(metadata), report=report,
                    approvals=decimal_json(approvals))

    @router.get('/{month}')
    def get_month(month: date, actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        return view(conn, month)

    @router.get('/{month}/overview')
    def get_overview(month: date,actor=Depends(admin_dependency),conn=Depends(connection_dependency)):
        from services.monthly_payout_reads import overview
        return _run(overview,conn,month,lambda c,m:view(c,m,True))

    @router.get('/{month}/trucks/{plate}')
    def get_truck(month:date,plate:str,actor=Depends(admin_dependency),conn=Depends(connection_dependency)):
        from services.monthly_payout_reads import truck_detail
        return _run(truck_detail,conn,month,plate,lambda c,m:view(c,m,True))

    @router.post('/{month}/sync')
    def sync(month: date, payload: SyncRequest, compact:bool=False,actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        _run(payouts.synchronize, conn, month, actor.id, **payload.model_dump())
        if compact:
            from services.monthly_payout_reads import overview
            return _run(overview,conn,month,lambda c,m:view(c,m,True))
        return view(conn, month)

    @router.post('/{month}/expenses')
    def expenses(month: date, file: UploadFile = File(...), expected_report_id: int | None = Form(None),
                 expected_raw_id: int | None = Form(None), compact:bool=False, actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        _run(payouts.synchronize, conn, month, actor.id, content=_upload(file), filename=file.filename,
             expected_report_id=expected_report_id, expected_raw_id=expected_raw_id)
        if compact:
            from services.monthly_payout_reads import overview
            return _run(overview,conn,month,lambda c,m:view(c,m,True))
        return view(conn, month)

    return router
