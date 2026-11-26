"""The existing guarded importer can consume saved bytes without a second upload."""
import ast,copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,patch
from datetime import date
from fastapi import HTTPException
from sqlalchemy import column
from sqlalchemy.exc import OperationalError

class SavedUploadReferenceTests(unittest.TestCase):
    def call(self,*,conflict=False,month=date(2026,9,1),identifier=3):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'routers/dhl_reports.py').read_text())
        node=copy.deepcopy(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='upload_dhl_report'))
        node.decorator_list=[];node.returns=None
        for a in node.args.args:a.annotation=None
        node.args.defaults=[ast.Constant(None) for _ in node.args.defaults]
        module=ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[]))
        importer=MagicMock(return_value=SimpleNamespace(period_start=date(2026,9,1),period_end=date(2026,9,30),inserted=1,unmatched=[]))
        ns=dict(HTTPException=HTTPException,OperationalError=OperationalError,parse_dhl_excel=lambda b:([],date(2026,9,1),date(2026,9,30)),
            import_dhl_report=importer,text=lambda s:s,DHLPayslip=SimpleNamespace(id=column('id'),period_start=column('period_start'),period_end=column('period_end')))
        exec(compile(module,'saved-upload-reference','exec'),ns)
        db=MagicMock();db.query.return_value.filter.return_value.first.return_value=object() if conflict else None
        with patch('services.monthly_files.get',return_value={'id':3,'reporting_month':date(2026,9,1),'content':b'synthetic saved bytes','original_filename':'raw.xlsx'}),patch('services.monthly_files.available',return_value=False),patch('services.monthly_files.register') as register:
            result=ns['upload_dhl_report'](file=None,raw_workbook_id=identifier,replace=True,reporting_month=month,db=db,current_user=SimpleNamespace(id=7))
            register.assert_not_called()
        return result,importer
    def test_saved_source_imports_exact_bytes_without_duplicate_archive(self):
        result,importer=self.call();self.assertEqual(result['retained_workbook_id'],3)
        self.assertEqual(importer.call_args.args[1],b'synthetic saved bytes')
    def test_existing_manual_payslips_still_block_reference_import(self):
        with self.assertRaises(HTTPException) as caught:self.call(conflict=True)
        self.assertEqual(caught.exception.status_code,409)
    def test_wrong_month_cannot_reuse_saved_source(self):
        with self.assertRaises(HTTPException) as caught:self.call(month=date(2026,8,1))
        self.assertEqual(caught.exception.status_code,422)
if __name__=='__main__':unittest.main()
