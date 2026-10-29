"""Explicit additive migration runner. Never imports the application's engine.

Example (DISPOSABLE LOCAL DATABASE ONLY):
  MONTHLY_EXPENSE_MIGRATION_URL=postgresql://.../smithsons_phase2_test \
    venv/bin/python scripts/migrate_monthly_expenses.py --apply
Nonlocal targets require --allow-nonlocal following separate deployment approval.
"""
import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit

import psycopg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Explicitly execute the additive migration')
    parser.add_argument('--allow-nonlocal', action='store_true', help='Use only after separate approval')
    args = parser.parse_args()
    url = os.environ.get('MONTHLY_EXPENSE_MIGRATION_URL')
    if not url:
        parser.error('Set MONTHLY_EXPENSE_MIGRATION_URL explicitly; no production default is used')
    if urlsplit(url).hostname not in {'localhost', '127.0.0.1', '::1'} and not args.allow_nonlocal:
        parser.error('Nonlocal migration targets require explicit --allow-nonlocal approval')
    migration = Path(__file__).resolve().parents[1] / 'migrations/001_dhl_monthly_expenses.sql'
    if not args.apply:
        print(f'Ready for review: {migration.name}. Nothing executed; pass --apply to run.')
        return
    with psycopg.connect(url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '5s'")
            cursor.execute("SET LOCAL statement_timeout = '60s'")
            cursor.execute(migration.read_text())
    print('Additive monthly expense migration committed successfully.')


if __name__ == '__main__':
    main()
