from datetime import date
from decimal import Decimal
import unittest

from services.dhl_reconciliation_detail import investigate

START=date(2026,2,1); END=date(2026,2,28)


def source(ref='123',plate='KAA123B',dist='100',off='20',stamp='2026-02-10',vid=1):
    return dict(ref_no=ref,truck_plate=plate,distribution_cost=Decimal(dist),offloading_cost=Decimal(off),date=stamp,vehicle_id=vid)


def order(ref='123',plate='KAA123B',stamp='2026-02-10',identifier=1):
    return dict(id=identifier,order_number=ref,truck_plate=plate,date=stamp)


def trip(identifier=1,plate='KAA123B',revenue='100'):
    return dict(order_id=identifier,id=identifier,status='completed',plate_number=plate,revenue=Decimal(revenue))


def snapshot(plate='KAA123B',gross='120',blocking=False):
    return dict(normalized_plate=plate,revenue_status='dhl_records',revenue_evidence='verified',
                gross=Decimal(gross),operating_expenses=Decimal('20'),commission=Decimal('7'),
                net_payable=Decimal('93'),issues=[{'blocking':True}] if blocking else [])


class DetailTests(unittest.TestCase):
    def run_report(self,dhl,orders=(),trips=(),batch=None,vehicles=()):
        return investigate(dhl,list(orders),list(trips),list(vehicles),START,END,batch)

    def test_multiple_dist_and_offloading_are_one_reference_not_duplicate_orders(self):
        result=self.run_report([source(dist='60',off='0'),source(dist='40',off='0'),source(dist='0',off='20')],[order()],[trip()])
        self.assertEqual(len(result['order_rows']),1)
        row=result['order_rows'][0]
        self.assertTrue(row['matched'])
        self.assertEqual(row['dhl_gross'],'120.00')
        self.assertEqual(row['difference'],'0.00')
        self.assertEqual(result['totals']['difference'],'0.00')

    def test_missing_orders_both_sides_preserve_all_gross(self):
        result=self.run_report([source()],[order('999')],[trip()])
        self.assertEqual({r['status'][0] for r in result['order_rows']},{'dhl_only','internal_only'})
        self.assertEqual(result['totals']['dhl_gross_by_reference'],'120.00')

    def test_duplicate_normalized_internal_references_are_ambiguous(self):
        row=self.run_report([source()],[order(),order(' 1 2 3 ',identifier=2)],[trip(),trip(2)])['order_rows'][0]
        self.assertIn('ambiguous_internal_reference',row['status'])
        self.assertIsNone(row['difference'])

    def test_plate_date_and_noncompleted_status_are_independent_findings(self):
        t=trip(plate='KBB123C');t['status']='cancelled'
        row=self.run_report([source()],[order(plate='KBB123C',stamp='2026-01-31')],[t])['order_rows'][0]
        self.assertTrue({'plate_mismatch','date_mismatch','trip_not_completed'}<=set(row['status']))

    def test_same_reference_across_trucks_is_ambiguous_but_revenue_is_not_lost(self):
        result=self.run_report([source(),source(plate='KBB123C')])
        self.assertIn('reference_multiple_trucks_or_dates',result['order_rows'][0]['status'])
        self.assertEqual(result['totals']['dhl_gross_by_reference'],'240.00')
        self.assertEqual(result['totals']['dhl_gross_by_truck'],'240.00')

    def test_unrelated_operational_difference_does_not_remove_confirmed_eligibility(self):
        batch=dict(id=1,version=1,status='confirmed',source_verification='verified',rows=[snapshot()])
        result=self.run_report([source(),source('MISSING','KBB123C')],batch=batch)
        self.assertTrue(next(r for r in result['truck_rows'] if r['plate_number']=='KAA123B')['payslip_eligible'])
        self.assertTrue(result['source']['reconciliation_is_advisory'])
        self.assertEqual(result['totals']['payout_roster_dhl_gross'],'120.00')
        self.assertEqual(result['totals']['outside_payout_roster_gross'],'120.00')
        self.assertEqual(result['totals']['roster_accounting_difference'],'0.00')

    def test_draft_good_row_is_not_falsely_presented_as_independently_confirmed(self):
        batch=dict(id=1,version=1,status='draft',source_verification='verified',rows=[snapshot(),snapshot('KBB123C',blocking=True)])
        row=self.run_report([source()],batch=batch)['truck_rows'][0]
        self.assertFalse(row['payslip_eligible'])
        self.assertIn('Whole-month',row['payslip_eligibility'])

    def test_roster_only_expenses_retained_missing_revenue_is_not_zero(self):
        batch=dict(id=1,version=1,status='draft',source_verification='',rows=[snapshot()])
        row=self.run_report([],batch=batch)['truck_rows'][0]
        self.assertEqual(row['operating_expenses'],'20.00')
        self.assertIsNone(row['dhl_gross'])
        self.assertIn('revenue_not_verified_zero',row['status'])

    def test_explicit_complete_no_activity_can_display_zero(self):
        r=snapshot(gross='0');r.update(revenue_status='verified_no_activity',revenue_evidence='Dispatch reviewed')
        batch=dict(id=1,version=1,status='draft',source_verification='Full source reviewed',rows=[r])
        self.assertEqual(self.run_report([],batch=batch)['truck_rows'][0]['dhl_gross'],'0.00')

    def test_ambiguous_truck_roster_and_unassigned_revenue_are_visible(self):
        batch=dict(id=1,version=1,status='draft',source_verification='',rows=[snapshot(),snapshot()])
        vehicles=[dict(id=1,plate_number='KAA123B'),dict(id=2,plate_number='KAA 123B')]
        row=self.run_report([source(vid=None)],batch=batch,vehicles=vehicles)['truck_rows'][0]
        self.assertIn('ambiguous_workbook_plate',row['status'])
        self.assertIn('ambiguous_vehicle_plate',row['status'])
        self.assertIn('unassigned_dhl_revenue',row['status'])
        self.assertFalse(row['payslip_eligible'])

    def test_invalid_source_amount_cannot_be_labelled_matched(self):
        r=source();r['distribution_cost']=None
        r['has_transport_charge']=True
        row=self.run_report([r],[order()],[trip(revenue='0')])['order_rows'][0]
        self.assertIn('invalid_dhl_amount',row['status'])

    def test_admin_only_ref_zero_is_audit_not_ambiguous_transport_order(self):
        result=self.run_report([source(ref='0',dist='0',off='0'),source(ref='0',plate='KBB123C',dist='0',off='0'),source()])
        self.assertEqual(len(result['order_rows']),1)
        self.assertEqual(len(result['zero_transport_audit_rows']),2)
        self.assertEqual(result['totals']['dhl_gross_by_reference'],'120.00')
