"""Admin-only file metadata and authenticated downloads. Never confirms finances."""
from datetime import date
from urllib.parse import quote
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from services import monthly_files as files
from services.monthly_expense_models import imports
from services.monthly_expense_persistence import get_import
from sqlalchemy import select
from routers.monthly_expense_reports import _run, _upload
from services.monthly_expense_reports import decimal_json


def attachment(content,filename):
 name=(filename or 'original_trips_workbook.xlsx').replace('\\','/').rsplit('/',1)[-1]
 return Response(content,media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={
  'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
  'Content-Disposition':"attachment; filename*=UTF-8''"+quote(name,safe='')})


def create_router(connection_dependency,admin_dependency):
 def no_cache(response:Response):response.headers['Cache-Control']='no-store'
 router=APIRouter(prefix='/dhl-reports/monthly-files',tags=['Saved Monthly Files'],dependencies=[Depends(no_cache)])
 @router.get('')
 def list_month(month:date,actor=Depends(admin_dependency),conn=Depends(connection_dependency)):
  if month.day!=1:raise HTTPException(422,'Select the first day of the reporting month')
  return decimal_json(_run(files.month_files,conn,month))
 @router.post('/dhl')
 def save_raw(month:date=Form(...),file:UploadFile=File(...),previous_id:int|None=Form(None),reason:str=Form(''),actor=Depends(admin_dependency),conn=Depends(connection_dependency)):
  if not files.available(conn):raise HTTPException(503,'Saved raw-file storage requires the approved 005 migration')
  record=_run(files.register,conn,_upload(file),month,file.filename,actor.id,previous_id,reason)
  return decimal_json(dict(files.metadata_view(record),verification=_run(files.verification,conn,record)))
 @router.get('/raw/{identifier}/verification')
 def verify_raw(identifier:int,actor=Depends(admin_dependency),conn=Depends(connection_dependency)):
  if not files.available(conn):raise HTTPException(503,'Saved raw-file storage requires the approved 005 migration')
  return decimal_json(_run(files.verification,conn,_run(files.get,conn,identifier)))
 @router.get('/raw/{identifier}')
 def download_raw(identifier:int,actor=Depends(admin_dependency),conn=Depends(connection_dependency)):
  if not files.available(conn):raise HTTPException(503,'Saved raw-file storage requires the approved 005 migration')
  record=_run(files.get,conn,identifier)
  return attachment(bytes(record['content']),record['original_filename'])
 @router.get('/report/{identifier}/{kind}')
 def original_report_file(identifier:int,kind:str,actor=Depends(admin_dependency),conn=Depends(connection_dependency)):
  if kind not in {'raw','expenses'}:raise HTTPException(404,'Unknown workbook type')
  batch=_run(get_import,conn,identifier)
  if kind=='expenses':return attachment(bytes(batch['source_content']),batch['original_filename'])
  review=_run(files.resolve_review,conn,batch['decisions'].get('historical_review'),batch['reporting_month'])
  if not review or not review.get('source_content_base64'):raise HTTPException(404,'The original raw workbook was not retained')
  import base64
  return attachment(base64.b64decode(review['source_content_base64'],validate=True),'original_trips_workbook.xlsx')
 return router
