"""Private, immutable raw workbooks; expense bytes stay in their existing table.
No global engine, financial confirmations, SMS or source revenue writes.
"""
import base64
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import MetaData, Table, Column, BigInteger, Integer, String, Date, DateTime, LargeBinary, select, insert, text
from sqlalchemy.dialects.postgresql import JSONB
from services.monthly_expense_models import imports, rows
from services.monthly_expense_dates import inspect_source, retain_source, validate_source
from services.monthly_reporting_scope import request_read

MAX_BYTES=20_000_000
metadata=MetaData()
workbooks=Table('dhl_monthly_workbooks',metadata,
 Column('id',BigInteger,primary_key=True),Column('reporting_month',Date),Column('version',Integer),
 Column('original_filename',String),Column('content_sha256',String),Column('content',LargeBinary),
 Column('uploaded_by',BigInteger),Column('uploaded_at',DateTime(timezone=True)),Column('previous_id',BigInteger),
 Column('reason',String),Column('date_review',JSONB))


def available(conn):
 return conn.execute(text("SELECT to_regclass('dhl_monthly_workbooks') IS NOT NULL")).scalar_one()


def register(conn,content,month,filename,actor,previous_id=None,reason=''):
 from services.monthly_expense_persistence import _lock, VersionConflict
 if month.day!=1 or actor<=0 or not filename.strip():raise ValueError('Month, filename and administrator are required')
 if not filename.lower().endswith('.xlsx'):raise ValueError('Retained raw workbooks must be XLSX')
 if not content or len(content)>MAX_BYTES:raise ValueError('Workbook must be nonempty and no larger than 20 MB')
 review,_=inspect_source(content,month)
 digest=hashlib.sha256(content).hexdigest();_lock(conn,month)
 old=conn.execute(select(workbooks.c.id).where(workbooks.c.reporting_month==month,workbooks.c.content_sha256==digest)).scalar_one_or_none()
 if old is not None:return get(conn,old)
 latest=conn.execute(select(workbooks).where(workbooks.c.reporting_month==month).order_by(workbooks.c.version.desc()).limit(1)).mappings().first()
 if (latest['id'] if latest else None)!=previous_id:raise VersionConflict('A saved raw workbook already exists or changed. Review its latest version before replacing it.')
 if latest and not reason.strip():raise ValueError('Explain why the raw workbook is being replaced')
 identifier=conn.execute(insert(workbooks).values(reporting_month=month,version=latest['version']+1 if latest else 1,
  original_filename=filename,content_sha256=digest,content=content,uploaded_by=actor,uploaded_at=datetime.now(timezone.utc),
  previous_id=previous_id,reason=reason.strip(),date_review=review).returning(workbooks.c.id)).scalar_one()
 return get(conn,identifier)


@request_read
def get(conn,identifier):
 return dict(conn.execute(select(workbooks).where(workbooks.c.id==identifier)).mappings().one())


def reference(record):
 return dict(record['date_review'],archive_id=record['id'])


def resolve_review(conn,review,month):
 if not review or 'archive_id' not in review:return review
 from sqlalchemy.exc import NoResultFound
 try:record=get(conn,review['archive_id'])
 except NoResultFound:raise ValueError('The saved raw workbook is missing; source review is required') from None
 if record['reporting_month']!=month:raise ValueError('Saved raw workbook belongs to a different month')
 actual=retain_source(bytes(record['content']),month)
 if {k:v for k,v in review.items() if k!='archive_id'}!={k:v for k,v in actual.items() if k!='source_content_base64'}:
  raise ValueError('Saved raw workbook checksum or validation metadata changed')
 return actual


def metadata_view(record):
 return {k:v for k,v in record.items() if k not in {'content','date_review'}}


def verification(conn,record):
 """Read-only evidence comparison, not an attestation or financial approval.

 Compare the importer-equivalent date/plate/reference groups, retaining separate
 DIST and Offloading amounts so equal grand totals cannot hide discrepancies.
 Existing date/manifest validation remains authoritative for confirmation.
 """
 from services.monthly_expense_persistence import _sources
 from services.monthly_expense_parser import money
 from services.monthly_expense_dates import _plate, _ref
 month=record['reporting_month']
 source,fingerprint=_sources(conn,month)
 review=resolve_review(conn,reference(record),month)
 actual,expected=inspect_source(bytes(record['content']),month)
 issues=validate_source(review,{},source,month,_inspected=(actual,expected))
 observed={}
 for row in source:
  key=(row['date'],_plate(row['truck_plate']),_ref(row['ref_no']))
  amounts=observed.setdefault(key,[Decimal('0.00'),Decimal('0.00')])
  for index,field in enumerate(('distribution_cost','offloading_cost')):
   amounts[index]+=money(row[field])
 differences=[]
 for key in sorted(expected.keys()|observed.keys()):
  left,right=expected.get(key),observed.get(key)
  if left==right:continue
  differences.append(dict(date=key[0],truck=key[1],reference=key[2],
   reason='missing_saved_record' if right is None else 'missing_workbook_record' if left is None else 'transport_amount_mismatch',
   workbook=None if left is None else dict(distribution=format(left[0],'.2f'),offloading=format(left[1],'.2f')),
   saved=None if right is None else dict(distribution=format(right[0],'.2f'),offloading=format(right[1],'.2f'))))
 def totals(groups):
  dist=sum((r[0] for r in groups.values()),Decimal('0.00'));off=sum((r[1] for r in groups.values()),Decimal('0.00'))
  return dict(distribution=format(dist,'.2f'),offloading=format(off,'.2f'),gross=format(dist+off,'.2f'))
 return dict(matches=not issues,status='matched_pending_administrator_review' if not issues else 'needs_review',
  source_fingerprint=fingerprint,saved_record_count=len(source),workbook_group_count=len(expected),
  workbook_totals=totals(expected),saved_totals=totals(observed),differences=differences,
  date_issues=actual['date_issues'],issues=issues,
  message='Evidence only. No DHL records, payslips or financial approvals were changed. Review and save a new expense report version using the retained workbook.')


def month_files(conn,month):
 from services.monthly_expense_persistence import _sources
 from services.monthly_expense_parser import money
 source,fingerprint=_sources(conn,month)
 batches=[dict(r) for r in conn.execute(select(*[c for c in imports.c if c.name!='source_content']).where(imports.c.reporting_month==month).order_by(imports.c.version.desc())).mappings()]
 archived=[]
 if available(conn):
  for r in conn.execute(select(*[c for c in workbooks.c if c.name!='content']).where(workbooks.c.reporting_month==month).order_by(workbooks.c.version.desc())).mappings():
   entry=metadata_view(r)
   # Exact retained manifest is reparsed; upload is not a financial approval.
   check=verification(conn,get(conn,r['id']))
   issues=check['issues']
   entry.update(status='needs_review' if issues else 'uploaded',issues=issues,source_kind='archive',
    download=f"/dhl-reports/monthly-files/raw/{r['id']}",date_issue_count=len(r['date_review']['date_issues']),financially_verified=False,verification=check)
   archived.append(entry)
 # Retained legacy evidence remains downloadable; unknown filenames/timestamps are disclosed.
 known={r['content_sha256'] for r in archived}
 for batch in batches:
  review=batch['decisions'].get('historical_review') or {}
  if review.get('source_content_base64') and review.get('sha256') not in known:
   known.add(review['sha256'])
   archived.append(dict(id=batch['id'],version=None,original_filename=None,uploaded_at=None,uploaded_by=None,
    source_kind='retained_report_evidence',status='needs_review',download=f"/dhl-reports/monthly-files/report/{batch['id']}/raw",
    retained_in_report_version=batch['version'],content_sha256=review.get('sha256'),financially_verified=False))
 expenses=[]
 first_saved={b['file_sha256']:b for b in reversed(batches)}
 for batch in batches:
  row_issues=conn.execute(select(rows.c.issues).where(rows.c.import_id==batch['id'])).scalars().all()
  blocking=any(i.get('blocking',True) for i in batch['issues']) or not row_issues or any(i.get('blocking',True) for issues in row_issues for i in issues)
  original=first_saved[batch['file_sha256']]
  # Gross/source validation is separate from whether the expense file itself is retained.
  expenses.append(dict(id=batch['id'],version=batch['version'],status=batch['status'],review_status='needs_review' if blocking else 'uploaded',
   original_filename=batch['original_filename'],uploaded_at=original['created_at'],uploaded_by=original['uploader_id'],report_saved_at=batch['created_at'],
   content_sha256=batch['file_sha256'],download=f"/dhl-reports/monthly-files/report/{batch['id']}/expenses"))
 uploader_ids={r.get('uploaded_by') for r in archived+expenses if r.get('uploaded_by')}
 names={}
 if uploader_ids:
  # Existing identity snapshots stay unchanged. Display administrator names only.
  for r in conn.execute(text('SELECT id,name FROM users WHERE id=ANY(:ids)'),{'ids':list(uploader_ids)}).mappings():names[r['id']]=r['name']
 for r in archived+expenses:r['uploader_name']=names.get(r.get('uploaded_by'))
 gross=sum((money(r['distribution_cost'])+money(r['offloading_cost']) for r in source),Decimal('0.00'))
 return dict(reporting_month=month,archive_available=available(conn),raw_files=archived,expense_files=expenses,
  latest_report_id=batches[0]['id'] if batches else None,parsed_dhl=dict(records=len(source),gross=format(gross,'.2f'),fingerprint=fingerprint),
  source_verified=bool(batches and batches[0]['source_verification'] and batches[0]['dhl_source_fingerprint']==fingerprint and not any(i.get('blocking',True) for i in batches[0]['issues'])),
  message='Stored revenue is not proof of source completeness. Review raw dates and explicitly verify the source before confirmation.')
