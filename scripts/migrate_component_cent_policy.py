"""Explicit 007 guard migration; production execution needs separate approval."""
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
        print('Review migrations/007_component_cent_policy.sql; no connection opened.')
        return
    url=os.environ.get('DHL_COMPONENT_CENT_MIGRATION_URL')
    if not url:parser.error('Set DHL_COMPONENT_CENT_MIGRATION_URL privately')
    if urlsplit(url).hostname not in {'localhost','127.0.0.1','::1'} and not args.allow_nonlocal:
        parser.error('Nonlocal execution requires separate approval and --allow-nonlocal')
    with psycopg.connect(url) as conn:
        conn.execute("SET LOCAL lock_timeout='5s'")
        conn.execute("SET LOCAL statement_timeout='120s'")
        conn.execute('SELECT pg_advisory_xact_lock(736282,7)')
        conn.execute((Path(__file__).resolve().parents[1]/'migrations/007_component_cent_policy.sql').read_text())
    print('Component cent policy migration committed atomically.')


if __name__=='__main__':main()
