"""Explicit 006 guard migration; production execution needs separate approval."""
import argparse
import os
from pathlib import Path
from urllib.parse import urlsplit
import psycopg


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--allow-nonlocal',action='store_true')
    args=parser.parse_args()
    if not args.apply:
        print('Review migrations/006_dist_surcharge_admin_policy.sql; no connection opened.')
        return
    url=os.environ.get('DHL_DIST_ADMIN_MIGRATION_URL')
    if not url:parser.error('Set DHL_DIST_ADMIN_MIGRATION_URL privately')
    if urlsplit(url).hostname not in {'localhost','127.0.0.1','::1'} and not args.allow_nonlocal:
        parser.error('Nonlocal execution requires separate approval and --allow-nonlocal')
    with psycopg.connect(url) as conn:
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL statement_timeout='120s'")
        conn.execute('SELECT pg_advisory_xact_lock(736282,6)')
        conn.execute((Path(__file__).resolve().parents[1]/'migrations/006_dist_surcharge_admin_policy.sql').read_text())
    print('DIST admin guard migration committed atomically.')


if __name__=='__main__':main()
