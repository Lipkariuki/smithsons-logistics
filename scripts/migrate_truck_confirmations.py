"""Explicit reviewed release migration; requires separate production approval."""
import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit

import psycopg


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--allow-nonlocal',action='store_true')
    parser.add_argument('--include-prerequisites',action='store_true',help='Apply pending 002 and 003 before 004 in the same transaction')
    args=parser.parse_args()
    url=os.environ.get('TRUCK_CONFIRMATION_MIGRATION_URL')
    if not url:parser.error('Set TRUCK_CONFIRMATION_MIGRATION_URL privately; no production default is used')
    if urlsplit(url).hostname not in {'localhost','127.0.0.1','::1'} and not args.allow_nonlocal:
        parser.error('Nonlocal targets require separate approval and --allow-nonlocal')
    paths=['002_monthly_statement_documents.sql','003_expense_zero_policy.sql'] if args.include_prerequisites else []
    paths+=['004_monthly_truck_confirmations.sql']
    if not args.apply:
        print('Review only; nothing executed: '+', '.join(paths));return
    root=Path(__file__).resolve().parents[1]/'migrations'
    with psycopg.connect(url) as conn:
        conn.execute("SET LOCAL lock_timeout = '5s'")
        conn.execute("SET LOCAL statement_timeout = '120s'")
        conn.execute('SELECT pg_advisory_xact_lock(736282,4)')
        for name in paths:conn.execute((root/name).read_text())
    print('Reviewed truck-confirmation migrations committed atomically.')


if __name__=='__main__':main()
