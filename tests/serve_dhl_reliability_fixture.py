"""Local real-HTTP fixture. Refuses production targets; never starts main/SMS.

MONTHLY_EXPENSE_TEST_URL must be loopback and its database end in _test.
Run with the repository venv; stop with Ctrl-C to drop its temporary schema.
"""
import io
import json
import os
from pathlib import Path
import sys
from datetime import date,datetime,timedelta,timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from fastapi import Depends
from fastapi.middleware.cors import CORSMiddleware
from jose import jwt
from sqlalchemy import text
from openpyxl import load_workbook
import uvicorn
from test_dhl_reliability_persistence import ReliabilityPersistenceTests
import test_monthly_expense_api as api
from routers.monthly_payouts import create_router
from services.monthly_expense_dates import inspect_source
from services.monthly_expense_parser import parse_expenses


def main():
    if not os.environ.get('MONTHLY_EXPENSE_TEST_URL'):raise SystemExit('Explicit disposable PostgreSQL URL required')
    ReliabilityPersistenceTests.setUpClass()
    fixture=ReliabilityPersistenceTests('test_migration_atomic_idempotent_and_legacy_pdf_bytes_unchanged')
    fixture.setUp()
    output=Path('/private/tmp/smithsons-reliability-http-fixture.json')
    try:
        month=date(2026,9,1)
        raw=(ROOT/'data/SEPTEMBER 2026 GROSS TOTALS (1).xlsx').read_bytes()
        net=(ROOT/'data/SEPTEMBER 2026 NET SUMMARY.xlsx').read_bytes()
        _,manifest=inspect_source(raw,month);parsed=parse_expenses(net,month)
        plates=sorted({k[1] for k in manifest}|{r.plate for r in parsed.rows})
        august=None
        if os.environ.get('DHL_LOCAL_INCLUDE_AUGUST')=='1':
            _,august=inspect_source((ROOT/'data/AUGUST 2026 GROSS TOTALS.xlsx').read_bytes(),date(2026,8,1))
            aug_expenses=parse_expenses((ROOT/'data/AUGUST 2026 NET SUMMARY 1.xlsx').read_bytes(),date(2026,8,1))
            plates=sorted(set(plates)|{k[1] for k in august}|{r.plate for r in aug_expenses.rows})
        with fixture.engine.begin() as conn:
            fixture.install(conn)
            conn.execute(text("UPDATE users SET name='Synthetic local administrator' WHERE id=7"))
            for i,plate in enumerate(plates,100):conn.execute(text("INSERT INTO vehicles VALUES(:id,:plate,7,'30T')"),dict(id=i,plate=plate))
            for i,(k,v) in enumerate(manifest.items(),1000):conn.execute(text('INSERT INTO dhl_orders VALUES(:id,:ref,:date,:plate,:vehicle,:dist,:off,:gross)'),dict(id=i,ref=k[2],date=k[0],plate=k[1],vehicle=100+plates.index(k[1]),dist=v[0],off=v[1],gross=sum(v)))
            for i,(k,v) in enumerate((august or {}).items(),2000):conn.execute(text('INSERT INTO dhl_orders VALUES(:id,:ref,:date,:plate,:vehicle,:dist,:off,:gross)'),dict(id=i,ref=k[2],date=k[0],plate=k[1],vehicle=100+plates.index(k[1]),dist=v[0],off=v[1],gross=sum(v)))
        def connection():
            with fixture.engine.begin() as conn:yield conn
        admin=api.auth_functions(fixture.engine)
        fixture.app.include_router(create_router(connection,admin))
        from services.dhl_performance import install
        install(fixture.app,fixture.engine)
        # Explicitly opt-in local slow-server simulation for transfer tests.
        delay=float(os.environ.get('DHL_LOCAL_TRANSFER_TEST_DELAY','0'))
        if delay:
            import asyncio
            @fixture.app.middleware('http')
            async def transfer_delay(request,call_next):
                if request.method=='POST' and request.url.path.endswith(('/expenses','/dhl')):
                    await asyncio.sleep(min(delay,2))
                return await call_next(request)
        @fixture.app.get('/users/me')
        def me(actor=Depends(admin)):
            return dict(id=actor.id,name=actor.name,role=actor.role)
        fixture.app.add_middleware(CORSMiddleware,allow_origins=['http://127.0.0.1:8067'],allow_methods=['GET','POST','OPTIONS'],allow_headers=['Authorization','Content-Type'],expose_headers=['Content-Length','X-Request-ID','Server-Timing'])
        token=jwt.encode({'sub':'7','role':'admin','exp':datetime.now(timezone.utc)+timedelta(hours=1)},'isolated-phase3-test-only',algorithm='HS256')
        book=load_workbook(io.BytesIO(net));ws=book.active
        # Deliberately synthetic local correction; never modifies either source file.
        ws['D4']=ws['D4'].value+1
        corrected=Path('/private/tmp/smithsons-reliability-synthetic-correction.xlsx')
        book.save(corrected);book.close();corrected.chmod(0o600)
        output.write_text(json.dumps(dict(token=token,raw_path=str(ROOT/'data/SEPTEMBER 2026 GROSS TOTALS (1).xlsx'),
            net_path=str(ROOT/'data/SEPTEMBER 2026 NET SUMMARY.xlsx'),corrected_path=str(corrected))))
        output.chmod(0o600)
        print('Isolated financial API ready on 127.0.0.1:8071; no production connection or delivery endpoints.',flush=True)
        uvicorn.run(fixture.app,host='127.0.0.1',port=8071,access_log=False,log_level='warning')
    finally:
        fixture.tearDown();ReliabilityPersistenceTests.tearDownClass()
        output.unlink(missing_ok=True)


if __name__=='__main__':main()
