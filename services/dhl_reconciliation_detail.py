"""Read-only REF NO and truck investigations; never authorizes or changes payouts."""
from collections import defaultdict
import calendar
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
import unicodedata

CENT = Decimal('.01')


def normalize(value):
    return ''.join(unicodedata.normalize('NFKC', '' if value is None else str(value)).split()).upper()


def number(value):
    if value is None:
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def money(value):
    return None if value is None else format(value.quantize(CENT, rounding=ROUND_HALF_UP), '.2f')


def day(value):
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10]) if value else None


def investigate(dhl, orders, trips, vehicles, start, end, batch=None):
    """All monetary results are Decimal strings; absent evidence stays absent.

    DHL input is imported date/ref/plate records with DIST and Offloading fields,
    not net-summary financial references. Internal candidates include matching
    references outside the date window to diagnose date mismatches.
    """
    drefs, irefs, dtrucks, trip_map, vehicle_map = (defaultdict(list) for _ in range(5))
    warnings = []
    for vehicle in vehicles:
        vehicle_map[normalize(vehicle['plate_number'])].append(vehicle)
    for trip in trips:
        trip_map[trip['order_id']].append(trip)
    selected = [r for r in dhl if day(r['date']) and start <= day(r['date']) <= end]
    invalid_amounts = sum(any(number(r.get(k)) is None for k in ('distribution_cost','offloading_cost')) for r in selected)
    if invalid_amounts:
        warnings.append('Some imported source amounts are missing or invalid. Control totals are incomplete and must not be treated as verified gross.')
    # The legacy importer retains zero DIST/Offloading records for Admin-only
    # rows (often REF 0). COST itself is not persisted. Keep these in a separate
    # audit list instead of manufacturing duplicate/missing transport orders.
    zero_records=[]
    for row in selected:
        transport = bool(row.get('has_transport_charge')) or any(number(row.get(k)) not in (None, Decimal(0)) for k in ('distribution_cost','offloading_cost'))
        if transport:
            drefs[normalize(row['ref_no'])].append(row)
        else:
            zero_records.append(dict(reference=normalize(row['ref_no']),truck=normalize(row['truck_plate']),date=str(day(row['date'])),
                                     reason='No transport amount: Admin-only or zero-value charge; raw COST provenance required'))
        dtrucks[normalize(row['truck_plate'])].append(row)
    if zero_records:
        warnings.append('Zero-transport imported records are shown separately for audit; COST is not retained by the importer. They are not duplicate or missing transport orders.')
    for order in orders:
        ref = normalize(order['order_number'])
        if (day(order['date']) and start <= day(order['date']) <= end) or ref in drefs:
            irefs[ref].append(order)
    operational = []
    for ref in sorted(drefs.keys() | irefs.keys()):
        sources, matches = drefs[ref], irefs[ref]
        dist = sum((number(r['distribution_cost']) or Decimal(0) for r in sources), Decimal(0))
        off = sum((number(r['offloading_cost']) or Decimal(0) for r in sources), Decimal(0))
        status = []
        if any(number(r.get(k)) is None for r in sources for k in ('distribution_cost', 'offloading_cost')):
            status.append('invalid_dhl_amount')
        if not sources: status.append('internal_only')
        if not matches: status.append('dhl_only')
        if not ref: status.append('missing_reference')
        if len(matches) > 1: status.append('ambiguous_internal_reference')
        source_plates = sorted({normalize(r['truck_plate']) for r in sources})
        source_dates = sorted({str(day(r['date'])) for r in sources})
        if len(source_plates) > 1 or len(source_dates) > 1:
            status.append('reference_multiple_trucks_or_dates')
        associated = [t for o in matches for t in trip_map[o['id']]]
        internal_plates = {normalize(o.get('truck_plate')) for o in matches if o.get('truck_plate')}
        internal_plates |= {normalize(t.get('plate_number')) for t in associated if t.get('plate_number')}
        if sources and matches and set(source_plates) != internal_plates:
            status.append('plate_mismatch')
        if any(len(trip_map[o['id']]) > 1 for o in matches): status.append('ambiguous_internal_trips')
        if matches and not associated: status.append('missing_trip')
        values = [number(t.get('revenue')) for t in associated]
        internal = sum(values, Decimal(0)) if values and all(v is not None for v in values) else None
        if associated and internal is None: status.append('missing_internal_revenue')
        comparable = sources and len(matches) == 1 and len(associated) == 1 and internal is not None
        difference = internal - dist if comparable else None
        if difference is not None and difference.quantize(CENT, rounding=ROUND_HALF_UP) != 0:
            status.append('transport_revenue_difference')
        if sources and any(str(day(o['date'])) not in source_dates for o in matches): status.append('date_mismatch')
        if any(t.get('status') != 'completed' for t in associated): status.append('trip_not_completed')
        operational.append(dict(reference=ref, order_numbers=[o['order_number'] for o in matches],
            order_ids=[o['id'] for o in matches], dhl_plates=source_plates, internal_plates=sorted(internal_plates),
            dhl_dates=source_dates, internal_dates=[str(day(o['date'])) for o in matches],
            trip_statuses=[t.get('status') for t in associated], dhl_record_count=len(sources),
            dhl_distribution=money(dist), dhl_offloading=money(off), dhl_gross=money(dist+off),
            internal_amount=money(internal), difference=money(difference),
            amount_basis='Internal Trip.revenue minus transport-only DIST; Offloading is disclosed separately. Manual overrides require review.',
            status=status or ['matched'], matched=not status))
    roster = defaultdict(list)
    active_approvals={r['normalized_plate']:r for r in (batch.get('current_truck_approvals',[]) if batch else [])}
    if batch:
        for row in batch['rows']:
            roster[normalize(row['normalized_plate'])].append(row)
    trucks = []
    for plate in sorted(dtrucks.keys() | roster.keys() | active_approvals.keys()):
        sources, matches = dtrucks[plate], roster[plate]
        transport_sources=[r for r in sources if r.get('has_transport_charge') or any(number(r.get(k)) not in (None,Decimal(0)) for k in ('distribution_cost','offloading_cost'))]
        gross = sum(((number(r['distribution_cost']) or Decimal(0)) + (number(r['offloading_cost']) or Decimal(0)) for r in sources), Decimal(0))
        status = []
        if not transport_sources and matches: status.append('workbook_only')
        if not matches: status.append(('dhl_only' if transport_sources else 'outside_selected_workbook') if batch else 'workbook_not_available')
        if len(matches) > 1: status.append('ambiguous_workbook_plate')
        if len(vehicle_map[plate]) > 1: status.append('ambiguous_vehicle_plate')
        if any(r.get('vehicle_id') is None for r in sources) or not plate: status.append('unassigned_dhl_revenue')
        linked = matches[0] if len(matches) == 1 else None
        # Zero is verified only by saved evidence and source-completeness review.
        verified_zero = bool(linked and (linked['revenue_status'] == 'verified_no_activity'
                             or (linked['revenue_status'] == 'dhl_records' and number(linked.get('gross')) == 0))
                             and linked.get('revenue_evidence') and batch.get('source_verification'))
        if not transport_sources and not verified_zero: status.append('revenue_not_verified_zero')
        snapshot_gross = number(linked.get('gross')) if linked else None
        if linked and snapshot_gross is not None and sources and money(snapshot_gross) != money(gross):
            status.append('live_revenue_differs_from_snapshot')
        financial_keys = ('operating_expenses', 'commission', 'net_payable')
        financial = {k: money(number(linked.get(k))) if linked else None for k in financial_keys}
        blockers = bool(linked and any(i.get('blocking', True) for i in linked['issues']))
        confirmed = bool(batch and batch['status'] in {'confirmed', 'superseded'})
        # Advisory discrepancies never become eligibility gates. Existing immutable
        # confirmation is whole-month; do not imply a draft row is independently approved.
        eligible = bool(linked and confirmed and not blockers
                        and all(linked.get(k) is not None for k in ('gross', *financial_keys)))
        truck_state=(batch.get('truck_states') or {}).get(linked['id']) if batch and linked and linked.get('id') else None
        if truck_state:
            eligible=truck_state['status']=='confirmed'
        eligibility='Confirmed snapshot available' if eligible else ('Whole-month confirmation required; independent truck confirmation needs approval' if linked else 'No financial snapshot')
        if truck_state:
            active=truck_state.get('current')
            eligibility=(f"Truck confirmed in version {active['report_version']}" if eligible else
                f"Confirmed version {active['report_version']} remains available; selected version is {truck_state['status']}" if active else
                'Ready for independent truck confirmation' if truck_state['can_confirm'] else
                truck_state.get('review_issue') or 'Truck needs review')
        if not linked and plate in active_approvals:
            eligibility=f"Confirmed version {active_approvals[plate]['report_version']} remains available; truck absent from selected workbook"
        trucks.append(dict(plate_number=plate or '(unassigned)', dhl_reference_count=len({normalize(r['ref_no']) for r in transport_sources}),
            dhl_record_count=len(transport_sources), zero_transport_record_count=len(sources)-len(transport_sources),
            dhl_gross=money(gross) if transport_sources or verified_zero else None,
            recorded_dhl_gross=money(gross), snapshot_gross=money(snapshot_gross),
            workbook_row_count=len(matches), **financial, status=status or ['matched'], matched=not status,
            payslip_eligible=eligible,payslip_eligibility=eligibility,
            source_version=batch['version'] if batch else None, source_status=batch['status'] if batch else None))
    by_ref = sum((Decimal(r['dhl_gross']) for r in operational), Decimal(0))
    by_truck = sum((Decimal(r['recorded_dhl_gross']) for r in trucks), Decimal(0))
    roster_gross=sum((Decimal(r['recorded_dhl_gross']) for r in trucks if r['workbook_row_count']==1),Decimal(0))
    outside_gross=sum((Decimal(r['recorded_dhl_gross']) for r in trucks if r['workbook_row_count']==0),Decimal(0))
    ambiguous_gross=sum((Decimal(r['recorded_dhl_gross']) for r in trucks if r['workbook_row_count']>1),Decimal(0))
    if batch is None: warnings.append('No saved expense workbook version is available; do not infer a payout roster or expenses.')
    if not (start.day == 1 and (end.replace(day=1) == start) and (end.day == calendar.monthrange(end.year,end.month)[1])):
        warnings.append('Select a complete single month for workbook financial comparison; order investigation still uses the selected dates.')
    return dict(order_rows=operational, truck_rows=trucks, zero_transport_audit_rows=zero_records, warnings=warnings,
        totals=dict(complete=not invalid_amounts, invalid_dhl_record_count=invalid_amounts,
                    dhl_gross_by_reference=money(by_ref), dhl_gross_by_truck=money(by_truck),
                    payout_roster_dhl_gross=money(roster_gross) if batch else None,
                    outside_payout_roster_gross=money(outside_gross) if batch else None,
                    ambiguous_roster_gross=money(ambiguous_gross) if batch else None,
                    roster_accounting_difference=money(by_truck-roster_gross-outside_gross-ambiguous_gross) if batch else None,
                    difference=money(by_ref-by_truck), unassigned_dhl_gross=money(sum(
                        ((number(r['distribution_cost']) or Decimal(0))+(number(r['offloading_cost']) or Decimal(0))
                         for r in selected if r.get('vehicle_id') is None),Decimal(0)))),
        source=dict(reference_field='orders.order_number', financial_report_id=batch.get('id') if batch else None,
                    financial_version=batch.get('version') if batch else None,
                    financial_status=batch.get('status') if batch else None,
                    reconciliation_is_advisory=True,
                    truck_confirmation_available=bool(batch and 'truck_states' in batch),
                    confirmation_scope='per_truck_and_whole_month' if batch and 'truck_states' in batch else 'whole_month'))


def from_database(db, start, end, *, owner_id=None, vehicle_id=None, vehicle_plate=None, version=None):
    """Read existing data; retain original route's owner/vehicle filter scope."""
    from sqlalchemy import select
    from sqlalchemy.exc import ProgrammingError
    from models import DHLOrder, Order, Trip, Vehicle
    from services.monthly_expense_models import imports, rows
    from services.monthly_expense_reports import decimal_json
    vehicles = [dict(id=v.id, plate_number=v.plate_number, owner_id=v.owner_id) for v in db.query(Vehicle).all()]
    allowed = {v['id'] for v in vehicles if (owner_id is None or v['owner_id']==owner_id)
               and (vehicle_id is None or v['id']==vehicle_id)
               and (not vehicle_plate or normalize(v['plate_number'])==normalize(vehicle_plate))}
    scoped = bool(owner_id or vehicle_id or vehicle_plate)
    query = db.query(DHLOrder).filter(DHLOrder.date>=start, DHLOrder.date<=end)
    if owner_id is not None or vehicle_id is not None: query=query.filter(DHLOrder.vehicle_id.in_(allowed))
    dhl = [{k:getattr(r,k) for k in ('id','ref_no','date','truck_plate','vehicle_id','distribution_cost','offloading_cost')} for r in query.all()]
    if vehicle_plate: dhl=[r for r in dhl if normalize(r['truck_plate'])==normalize(vehicle_plate)]
    refs = {normalize(r['ref_no']) for r in dhl}
    # No normalized-reference index exists. Project only investigation fields and
    # normalize identically in Python, including Unicode whitespace and references
    # outside the date range. A date-only query would hide the mismatch itself.
    fields=('id','order_number','date','truck_plate','total_amount')
    order_query=db.query(*[getattr(Order,k) for k in fields])
    candidates=[dict(r._mapping) for r in order_query.all()
                if (day(r.date) and start<=day(r.date)<=end) or normalize(r.order_number) in refs]
    ts = db.query(Trip).filter(Trip.order_id.in_([o['id'] for o in candidates])).all()
    vehicle_ids={v['id']:v for v in vehicles}
    trips=[dict(id=t.id,order_id=t.order_id,vehicle_id=t.vehicle_id,revenue=t.revenue,status=t.status,
                plate_number=vehicle_ids.get(t.vehicle_id,{}).get('plate_number')) for t in ts]
    if scoped:
        ids={t['order_id'] for t in trips if t['vehicle_id'] in allowed}
        candidates=[o for o in candidates if o['id'] in ids or normalize(o.get('truck_plate')) in {normalize(v['plate_number']) for v in vehicles if v['id'] in allowed}]
        trips=[t for t in trips if t['order_id'] in {o['id'] for o in candidates}]
    batch = None
    storage_warning = None
    full_month=start.day==1 and end==start.replace(day=calendar.monthrange(start.year,start.month)[1])
    if full_month:
        try:
            # Missing storage must not roll back the surrounding legacy report.
            with db.begin_nested():
                q=select(imports).where(imports.c.reporting_month==start)
                q=q.where(imports.c.version==version) if version is not None else q.order_by(imports.c.version.desc()).limit(1)
                found=db.execute(q).mappings().first()
                if found:
                    batch=dict(found)
                    batch['rows']=[dict(r) for r in db.execute(select(rows).where(rows.c.import_id==batch['id'])).mappings()]
                    if scoped: batch['rows']=[r for r in batch['rows'] if r['vehicle_id'] in allowed]
        except ProgrammingError as exc:
            if getattr(exc.orig,'sqlstate',None)!='42P01': raise
            storage_warning='Monthly expense storage is unavailable; operational reconciliation is still shown.'
    if batch:
        from services.truck_confirmations import presentation
        truck_states=presentation(db.connection(),batch)
        if truck_states is not None:
            batch['truck_states']=truck_states['rows']
            batch['current_truck_approvals']=truck_states['current_approvals']
    result=investigate(dhl,candidates,trips,vehicles,start,end,batch)
    if storage_warning: result['warnings'].append(storage_warning)
    if batch:
        review=(batch.get('decisions') or {}).get('historical_review') or {}
        result['historical_source_rows']=review.get('date_issues',review.get('out_of_month_records',[]))
    else:
        result['historical_source_rows']=[]
        result['warnings'].append('Historical raw-source rows cannot be reconstructed from month-filtered imported records. Review the retained raw workbook.')
    return decimal_json(result)
