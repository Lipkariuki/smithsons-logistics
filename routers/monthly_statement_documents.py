"""Explicit admin generation and immutable downloads, separate from manual payslips."""
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from routers.monthly_expense_reports import _run
from services.monthly_statement_documents import (create_document, get_document,
    document_info, documents)


class TruckConfirmationRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    reason: str=Field(min_length=1,max_length=2000)
    expected_current_confirmation_id: int | None=Field(None,gt=0)


def create_router(connection_dependency, admin_dependency):
    def no_cache(response: Response):
        response.headers['Cache-Control'] = 'no-store'

    router = APIRouter(prefix='/dhl-reports', tags=['Confirmed Truck Statements'],
                       dependencies=[Depends(no_cache)])

    @router.post('/expense-rows/{row_id}/confirm')
    def confirm_truck_row(row_id: int, payload: TruckConfirmationRequest,
                          actor=Depends(admin_dependency),conn=Depends(connection_dependency)):
        from services.truck_confirmations import confirm_truck
        return _run(confirm_truck,conn,row_id,actor.id,payload.reason,payload.expected_current_confirmation_id)

    @router.post('/monthly-statement-documents/from-row/{row_id}')
    def generate(row_id: int, actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        return document_info(_run(create_document, conn, row_id, actor.id))

    @router.get('/expense-imports/{import_id}/statement-documents')
    def history(import_id: int, actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        from services.monthly_expense_models import rows
        query = select(*[c for c in documents.c if c.name != 'pdf_content']).join(
            rows, rows.c.id == documents.c.expense_row_id).where(rows.c.import_id == import_id).order_by(documents.c.id)
        return [dict(r) for r in _run(lambda: conn.execute(query).mappings().all())]

    @router.get('/monthly-statement-documents/{document_id}/pdf')
    def download(document_id: int, actor=Depends(admin_dependency), conn=Depends(connection_dependency)):
        doc = _run(get_document, conn, document_id)
        return Response(bytes(doc['pdf_content']), media_type='application/pdf', headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': f'attachment; filename="smithsons_monthly_transport_statement_{doc["id"]}.pdf"',
            'X-Content-SHA256': doc['pdf_sha256']})

    return router
