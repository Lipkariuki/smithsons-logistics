"""Core tables with PRIVATE metadata; never registered in startup create_all.

Migration SQL is authoritative for constraints/triggers. No production engine import.
Legacy IDs are informational snapshots, intentionally not foreign keys that could
change legacy delete behavior. The two new tables reference only each other.
"""
from sqlalchemy import (MetaData, Table, Column, BigInteger, Integer, String, Date,
                        DateTime, Numeric, LargeBinary, ForeignKey)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
imports = Table(
    'dhl_monthly_expense_imports', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('reporting_month', Date, nullable=False),
    Column('version', Integer, nullable=False),
    Column('status', String, nullable=False),
    Column('original_filename', String, nullable=False),
    Column('file_sha256', String(64), nullable=False),
    Column('source_content', LargeBinary, nullable=False),
    Column('decisions', JSONB, nullable=False),
    Column('decisions_sha256', String(64), nullable=False),
    Column('header_mappings', JSONB, nullable=False),
    Column('assumptions', JSONB, nullable=False),
    Column('issues', JSONB, nullable=False),
    Column('dhl_source_fingerprint', String(64), nullable=False),
    Column('source_verification', String, nullable=False),
    Column('calculation_policy', JSONB, nullable=False),
    Column('uploader_id', BigInteger, nullable=False),
    Column('confirmer_id', BigInteger),
    Column('created_at', DateTime(timezone=True), nullable=False),
    Column('confirmed_at', DateTime(timezone=True)),
    Column('previous_version_id', BigInteger, ForeignKey('dhl_monthly_expense_imports.id')),
)
rows = Table(
    'dhl_monthly_expense_rows', metadata,
    Column('id', BigInteger, primary_key=True),
    Column('import_id', BigInteger, ForeignKey('dhl_monthly_expense_imports.id'), nullable=False),
    Column('source_worksheet', String, nullable=False),
    Column('source_row', Integer, nullable=False),
    Column('original_plate', String, nullable=False),
    Column('normalized_plate', String, nullable=False),
    Column('vehicle_id', BigInteger),
    Column('vehicle_owner_snapshot', JSONB, nullable=False),
    Column('deductions', JSONB, nullable=False),
    Column('cell_audit', JSONB, nullable=False),
    Column('dhl_source_snapshot', JSONB, nullable=False),
    Column('revenue_status', String, nullable=False),
    Column('revenue_evidence', String, nullable=False),
    Column('gross', Numeric(18, 2)),
    Column('operating_expenses', Numeric(18, 2)),
    Column('commission_base', Numeric(18, 2)),
    Column('commission', Numeric(18, 2)),
    Column('net_payable', Numeric(18, 2)),
    Column('issues', JSONB, nullable=False),
)
