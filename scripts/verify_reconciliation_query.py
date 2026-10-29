"""Isolated PostgreSQL query/legacy-route verification; refuses production targets."""
from datetime import date, datetime
import io
import json
import os
from pathlib import Path
import sys
import types
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import declarative_base, sessionmaker

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
url=make_url(os.environ['MONTHLY_EXPENSE_TEST_URL'])
if url.host not in {'127.0.0.1','localhost','::1'} or not url.database.endswith('_test'):
    raise RuntimeError('Only explicit local test targets allowed')
admin=create_engine(url);schema='reference_test_'+uuid.uuid4().hex
with admin.begin() as conn:conn.execute(text(f'CREATE SCHEMA {schema}'))
engine=create_engine(url,connect_args={'options':'-c search_path='+schema})
stub=types.ModuleType('database');stub.Base=declarative_base();stub.get_db=lambda:None
sys.modules['database']=stub
auth=types.ModuleType('routers.auth');auth.require_role=lambda *roles:lambda:None
sys.modules['routers.auth']=auth
try:
    from models import User,Vehicle,Order,Trip,DHLOrder
    from routers.dhl_reports import dhl_reconciliation
    from services.dhl_reconciliation_detail import from_database
    from services.monthly_expense_persistence import create_draft,confirm_import
    from services.monthly_expense_reconciliation import review_historical_adjustments
    sys.path.insert(0,str(ROOT/'tests'))
    from test_monthly_expense_persistence import book,raw_book
    stub.Base.metadata.create_all(engine)
    session=sessionmaker(bind=engine)
    with engine.begin() as conn:
        conn.exec_driver_sql((ROOT/'migrations/001_dhl_monthly_expenses.sql').read_text())
    with session.begin() as db:
        db.add(User(id=7,name='Synthetic owner',role='owner',password_hash='not-a-real-hash'));db.flush()
        db.add(Vehicle(id=1,plate_number='KAA123B',owner_id=7));db.flush()
        db.add(Order(id=1,order_number='REF1',date=datetime(2026,2,10),truck_plate='KAA123B',total_amount=900));db.flush()
        db.add(Trip(id=1,order_id=1,vehicle_id=1,status='completed',revenue=900))
        db.add(DHLOrder(id=1,ref_no='REF1',date=date(2026,2,10),truck_plate='KAA123B',vehicle_id=1,distribution_cost=900,offloading_cost=100,total_revenue=1000))
    with engine.begin() as conn:
        batch=create_draft(conn,book(),date(2026,2,1),'synthetic.xlsx',7,
            source_verification='Synthetic source verified',historical_review=review_historical_adjustments(raw_book(conn),date(2026,2,1)))
        confirm_import(conn,batch['id'],7)
    checks={}
    with session.begin() as db:
        args=dict(owner_id=None,vehicle_id=None,vehicle_plate=None,start_date=date(2026,2,1),end_date=date(2026,2,28),db=db,current_user=None)
        before={t:db.execute(text(f'SELECT count(*) FROM {t}')).scalar() for t in ['orders','trips','dhl_orders','dhl_payslips','expenses','commissions','dhl_monthly_expense_imports','dhl_monthly_expense_rows']}
        legacy=dhl_reconciliation(**args)
        detailed=dhl_reconciliation(**args,include_details=True)
        checks['legacy_fields_preserved']=legacy.model_dump(exclude={'details'})==detailed.model_dump(exclude={'details'})
        checks['reference_match']=detailed.details['order_rows'][0]['matched']
        checks['decimal_totals']=detailed.details['totals']['dhl_gross_by_reference']=='1000.00'
        checks['confirmed_eligible']=detailed.details['truck_rows'][0]['payslip_eligible']
        checks['no_source_bytes_exposed']='source_content' not in json.dumps(detailed.details)
        checks['owner_scope']=not from_database(db,date(2026,2,1),date(2026,2,28),owner_id=999)['truck_rows']
        checks['version_selection']=from_database(db,date(2026,2,1),date(2026,2,28),version=1)['source']['financial_version']==1
        checks['counts_unchanged']=before=={t:db.execute(text(f'SELECT count(*) FROM {t}')).scalar() for t in before}
    # Missing reporting storage uses a savepoint and preserves operational data.
    with engine.begin() as conn:
        conn.execute(text('DROP TABLE dhl_monthly_expense_rows,dhl_monthly_expense_imports CASCADE'))
    with session.begin() as db:
        missing=from_database(db,date(2026,2,1),date(2026,2,28))
        checks['missing_storage_preserves_operational']=bool(missing['order_rows']) and any('storage is unavailable' in w for w in missing['warnings'])
    if not all(checks.values()):raise AssertionError({k:v for k,v in checks.items() if not v})
    print(json.dumps(checks))
finally:
    engine.dispose()
    with admin.begin() as conn:conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
    admin.dispose()
