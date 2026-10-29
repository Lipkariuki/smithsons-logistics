"""Separate, explicit transaction for reviewed statement storage. Never runs at startup."""
import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit

import psycopg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--allow-nonlocal', action='store_true')
    args = parser.parse_args()
    url = os.environ.get('MONTHLY_STATEMENT_MIGRATION_URL')
    if not url:
        parser.error('Set MONTHLY_STATEMENT_MIGRATION_URL explicitly')
    if urlsplit(url).hostname not in {'localhost', '127.0.0.1', '::1'} and not args.allow_nonlocal:
        parser.error('Nonlocal targets require separate approval and --allow-nonlocal')
    if not args.apply:
        print('Review migrations/002_monthly_statement_documents.sql; nothing executed.')
        return
    with psycopg.connect(url) as conn:
        conn.execute("SET LOCAL lock_timeout = '5s'")
        conn.execute("SET LOCAL statement_timeout = '60s'")
        conn.execute((Path(__file__).resolve().parents[1] / 'migrations/002_monthly_statement_documents.sql').read_text())
    print('Monthly statement document migration committed.')


if __name__ == '__main__':
    main()
