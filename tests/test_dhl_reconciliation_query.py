"""Actual ORM queries and legacy endpoint run in a subprocess with local test data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


@unittest.skipUnless(os.environ.get('MONTHLY_EXPENSE_TEST_URL'),'Requires disposable local PostgreSQL')
class QueryTests(unittest.TestCase):
    def test_legacy_compatibility_snapshot_selection_readonly_and_missing_storage(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run([sys.executable,str(root/'scripts/verify_reconciliation_query.py')],cwd=root,
                              capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(all(json.loads(result.stdout).values()))
