"""Retired manual writes fail before accessing records; historical read routes remain."""
import ast
from pathlib import Path
import unittest
from fastapi import HTTPException

class RetiredPayslipTests(unittest.TestCase):
    def test_manual_writes_return_gone_without_touching_data(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'routers/dhl_reports.py').read_text())
        functions={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
        for name in ['create_payslip','update_payslip']:
            with self.subTest(name=name):
                node=functions[name]
                wrapper=ast.FunctionDef(name='run',args=ast.arguments(posonlyargs=[],args=[],kwonlyargs=[],kw_defaults=[],defaults=[]),body=node.body,decorator_list=[])
                module=ast.fix_missing_locations(ast.Module(body=[wrapper],type_ignores=[]));ns={'HTTPException':HTTPException}
                exec(compile(module,'retired-endpoint','exec'),ns)
                with self.assertRaises(HTTPException) as caught:ns['run']()
                self.assertEqual(caught.exception.status_code,410)
                self.assertIn('DHL Monthly Payouts',caught.exception.detail)
                self.assertTrue(any(isinstance(x,ast.Call) and isinstance(x.func,ast.Name) and x.func.id=='require_role' and [getattr(a,'value',None) for a in x.args]==['admin'] for x in ast.walk(node)))
        self.assertNotIn('_compute_default_expenses',functions)
        for name in ['list_payslips','get_payslip','download_payslip_pdf','send_payslip']:
            self.assertIn(name,functions)

if __name__=='__main__':unittest.main()
