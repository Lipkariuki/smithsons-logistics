"""Explicit additive 005 migration. Never uses an application database default."""
import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit
import psycopg


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--apply',action='store_true');p.add_argument('--allow-nonlocal',action='store_true');args=p.parse_args()
 url=os.environ.get('SAVED_MONTHLY_FILES_MIGRATION_URL')
 if not url:p.error('Set SAVED_MONTHLY_FILES_MIGRATION_URL privately')
 if urlsplit(url).hostname not in {'localhost','127.0.0.1','::1'} and not args.allow_nonlocal:p.error('Nonlocal target requires --allow-nonlocal and separate approval')
 if not args.apply:print('Review only: 005_saved_dhl_workbooks.sql; no connection opened');return
 with psycopg.connect(url) as conn:
  conn.execute("SET LOCAL lock_timeout='5s'");conn.execute("SET LOCAL statement_timeout='120s'")
  conn.execute('SELECT pg_advisory_xact_lock(736282,5)')
  conn.execute((Path(__file__).resolve().parents[1]/'migrations/005_saved_dhl_workbooks.sql').read_text())
 print('Saved monthly file migration committed atomically.')


if __name__=='__main__':main()
