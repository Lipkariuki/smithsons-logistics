"""Manual actual-workbook performance benchmark; disposable PostgreSQL only.
Run from the repository venv with MONTHLY_EXPENSE_TEST_URL pointing to a loopback
_test database. Output remains private in /private/tmp, never in Git.
"""
import os,sys,time,json,io
from pathlib import Path
from datetime import date
from contextlib import ExitStack
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from sqlalchemy import text,event
from test_dhl_reliability_persistence import ReliabilityPersistenceTests
import test_monthly_expense_api as api
from routers.monthly_payouts import create_router
from services.monthly_expense_dates import inspect_source,retain_source,validate_source
from services.monthly_expense_parser import parse_expenses
from services.monthly_expense_persistence import _sources
from services import monthly_payouts as payout
from services.truck_confirmations import confirm_truck
from services.monthly_statement_documents import create_document,get_document
import services.monthly_expense_parser as parser
import services.monthly_expense_dates as dates
import services.dhl_revenue_policy as policy
import services.dhl_rounding_reconciliation as rounding
label=sys.argv[1] if len(sys.argv)>1 else 'current';assert label in {'before','after','current'};results={};month=date(2026,9,1)
ReliabilityPersistenceTests.setUpClass();f=ReliabilityPersistenceTests('test_migration_atomic_idempotent_and_legacy_pdf_bytes_unchanged');f.setUp()
from types import MethodType
f.request=MethodType(api.ApiTests.request,f)
queries=[];event.listen(f.engine,'before_cursor_execute',lambda *args:queries.append(1))
def measure(name,fn):
 q=len(queries);start=time.perf_counter();x=fn();results[name]={'seconds':round(time.perf_counter()-start,4),'sql_queries':len(queries)-q};print(name,results[name],flush=True);return x
try:
 raw=Path('data/SEPTEMBER 2026 GROSS TOTALS (1).xlsx').read_bytes();net=Path('data/SEPTEMBER 2026 NET SUMMARY.xlsx').read_bytes();results['file_bytes']={'dhl':len(raw),'expenses':len(net)}
 review,manifest=measure('raw_parse',lambda:inspect_source(raw,month));parsed=measure('expense_parse',lambda:parse_expenses(net,month))
 plates=sorted({k[1] for k in manifest}|{r.plate for r in parsed.rows})
 with f.engine.begin() as c:
  f.install(c)
  for i,p in enumerate(plates,100):c.execute(text("INSERT INTO vehicles VALUES(:id,:plate,7,'30T')"),{'id':i,'plate':p})
  for i,(k,v) in enumerate(manifest.items(),1000):c.execute(text('INSERT INTO dhl_orders VALUES(:id,:ref,:date,:plate,:vehicle,:dist,:off,:gross)'),{'id':i,'ref':k[2],'date':k[0],'plate':k[1],'vehicle':100+plates.index(k[1]),'dist':v[0],'off':v[1],'gross':sum(v)})
  source,_=_sources(c,month);measure('reconciliation',lambda:validate_source(retain_source(raw,month),{},source,month,reconcile_source_rounding=True))
  archive=measure('raw_persistence',lambda:payout.files.register(c,raw,month,'september.xlsx',7))
  with ExitStack() as stack:
   reads=[]
   for m in [parser,dates,policy,rounding]:
    original=m.load_workbook
    def spy(*a,_original=original,**k):reads.append(1);return _original(*a,**k)
    stack.enter_context(patch.object(m,'load_workbook',side_effect=spy))
   batch=measure('expense_sync',lambda:payout.synchronize(c,month,7,expected_report_id=None,expected_raw_id=archive['id'],content=net,filename='net.xlsx'))
   results['expense_sync']['workbook_opens']=len(reads)
 def connection():
  with f.engine.begin() as c:yield c
 f.app.include_router(create_router(connection,api.auth_functions(f.engine)))
 body=measure('monthly_full_http',lambda:f.request('GET','/dhl-reports/monthly-payouts/2026-09-01'))
 assert body[0]==200;results['monthly_full_http']['json_bytes']=len(json.dumps(body[1]))
 for path,name in [('/dhl-reports/monthly-payouts/2026-09-01/overview','monthly_overview_http'),('/dhl-reports/monthly-payouts/2026-09-01/trucks/KAY025L','truck_detail_http')]:
  if label!='before':
   b=measure(name,lambda:f.request('GET',path));assert b[0]==200,b;results[name]['json_bytes']=len(json.dumps(b[1]))
 row=next(r for r in batch['rows'] if r['normalized_plate']=='KAY025L')
 with f.engine.begin() as c:
  measure('confirm_truck',lambda:confirm_truck(c,row['id'],7,'Synthetic performance benchmark'))
  doc=measure('first_pdf',lambda:create_document(c,row['id'],7));again=measure('existing_pdf_generate_route',lambda:create_document(c,row['id'],7));assert bytes(doc['pdf_content'])==bytes(again['pdf_content'])
  measure('stored_pdf_lookup',lambda:get_document(c,doc['id']));results['pdf_bytes']=len(doc['pdf_content'])
 b=measure('pdf_http_transfer',lambda:f.request('GET',f"/dhl-reports/monthly-statement-documents/{doc['id']}/pdf"));assert b[0]==200
 results['financial']={k:str(row[k]) for k in ['gross','operating_expenses','commission','net_payable']}
 output=Path('/private/tmp/smithsons-performance-'+label+'.json');output.write_text(json.dumps(results,indent=2));output.chmod(0o600);print('Benchmark complete',flush=True)
finally:f.tearDown();ReliabilityPersistenceTests.tearDownClass()
