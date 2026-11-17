-- Policy-aware guard extension only. Apply in one explicit transaction after 005.
-- No tables/columns/data are added, removed, renamed or rewritten.
-- Legacy formula and immutable-history guards remain intact. Safe to rerun.
CREATE OR REPLACE FUNCTION dhl_dist_admin_fee(r dhl_monthly_expense_rows, policy JSONB)
RETURNS NUMERIC LANGUAGE plpgsql STABLE AS $$
DECLARE s JSONB; t JSONB; a NUMERIC; extra NUMERIC; inclusive NUMERIC; fee NUMERIC;
 dist NUMERIC:=0; offload NUMERIC:=0; surcharge NUMERIC:=0; fees NUMERIC:=0;
 month DATE; field TEXT; seen JSONB:='[]'::jsonb;
BEGIN
 s:=r.cell_audit->'_dhl_transport';
 IF policy->>'version' <> 'monthly-expenses-v3-dist-admin' OR policy->>'version' IS NULL THEN
  IF s IS NOT NULL THEN RAISE EXCEPTION 'Transport policy does not match parent'; END IF;
  RETURN 0;
 END IF;
 IF policy->>'transport_policy' IS DISTINCT FROM 'dist-surcharge-admin-v1'
  OR policy->>'dhl_admin_rate' IS DISTINCT FROM '0.05'
  OR policy->>'dhl_admin_base' IS DISTINCT FROM 'DIST_including_surcharge_only'
  OR jsonb_typeof(s) IS DISTINCT FROM 'object' OR s->>'policy' IS DISTINCT FROM 'dist-surcharge-admin-v1'
  OR jsonb_typeof(s->'transactions') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'Invalid DIST admin source policy';
 END IF;
 SELECT reporting_month INTO month FROM dhl_monthly_expense_imports WHERE id=r.import_id;
 IF s->>'reporting_month' IS DISTINCT FROM month::text THEN RAISE EXCEPTION 'Source month mismatch'; END IF;
 FOREACH field IN ARRAY ARRAY['distribution','offloading','surcharge','gross','admin_fee'] LOOP
  IF jsonb_typeof(s->field) IS DISTINCT FROM 'string' OR (s->>field) !~ '^-?[0-9]+\.[0-9]{2}$' THEN
   RAISE EXCEPTION 'Invalid transport component';
  END IF;
 END LOOP;
 FOR t IN SELECT value FROM jsonb_array_elements(s->'transactions') LOOP
  IF t->>'plate' IS DISTINCT FROM r.normalized_plate OR left(t->>'date',7) IS DISTINCT FROM to_char(month,'YYYY-MM')
    OR NOT (t ? 'source_row') OR seen @> jsonb_build_array(t->'source_row') OR btrim(coalesce(t->>'reference',''))='' THEN
   RAISE EXCEPTION 'Invalid or repeated transport source identity';
  END IF;
  seen:=seen||jsonb_build_array(t->'source_row');
  FOREACH field IN ARRAY ARRAY['amount','surcharge','inclusive','admin_fee'] LOOP
   IF jsonb_typeof(t->field) IS DISTINCT FROM 'string' OR (t->>field) !~ '^-?[0-9]+\.[0-9]{2}$' THEN
    RAISE EXCEPTION 'Invalid source financial amount';
   END IF;
  END LOOP;
  a:=(t->>'amount')::numeric;extra:=(t->>'surcharge')::numeric;
  inclusive:=(t->>'inclusive')::numeric;fee:=(t->>'admin_fee')::numeric;
  IF a+extra<>inclusive THEN RAISE EXCEPTION 'Inclusive source mismatch'; END IF;
  IF t->>'cost'='dist' THEN
   IF fee<>round(inclusive*0.05,2) THEN RAISE EXCEPTION 'DIST fee must be rounded per row'; END IF;
   dist:=dist+a;
  ELSIF t->>'cost'='offloading' THEN
   IF extra<>0 OR fee<>0 THEN RAISE EXCEPTION 'Offloading is exempt from administration fees'; END IF;
   offload:=offload+a;
  ELSE RAISE EXCEPTION 'Invalid transport COST';
  END IF;
  surcharge:=surcharge+extra;fees:=fees+fee;
 END LOOP;
 IF dist<>(s->>'distribution')::numeric OR offload<>(s->>'offloading')::numeric
  OR surcharge<>(s->>'surcharge')::numeric OR fees<>(s->>'admin_fee')::numeric
  OR dist+offload+surcharge<>(s->>'gross')::numeric OR (s->>'gross')::numeric<>r.gross
  OR dist+surcharge<>(SELECT coalesce(sum((x->>'distribution_cost')::numeric),0) FROM jsonb_array_elements(r.dhl_source_snapshot) x)
  OR offload<>(SELECT coalesce(sum((x->>'offloading_cost')::numeric),0) FROM jsonb_array_elements(r.dhl_source_snapshot) x) THEN
  RAISE EXCEPTION 'Frozen transport components do not match revenue';
 END IF;
 RETURN fees;
END $$;

CREATE OR REPLACE FUNCTION dhl_monthly_guard_import() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE r dhl_monthly_expense_rows; entry RECORD; deduction_total NUMERIC; categories JSONB;
BEGIN
 IF TG_OP = 'DELETE' THEN
  IF OLD.status <> 'draft' THEN RAISE EXCEPTION 'Confirmed history is immutable'; END IF;
  RETURN OLD;
 END IF;
 IF TG_OP = 'INSERT' AND NEW.status <> 'draft' THEN
  RAISE EXCEPTION 'Imports must start as drafts';
 END IF;
 IF TG_OP = 'UPDATE' AND OLD.status <> 'draft' THEN
  IF NOT (OLD.status = 'confirmed' AND NEW.status = 'superseded'
     AND (to_jsonb(NEW) - 'status') = (to_jsonb(OLD) - 'status')) THEN
   RAISE EXCEPTION 'Confirmed history is immutable except supersession';
  END IF;
 END IF;
 IF TG_OP = 'UPDATE' AND OLD.status = 'draft' AND NEW.status = 'superseded' THEN
  RAISE EXCEPTION 'Only confirmed reports can be superseded';
 END IF;
 IF NEW.previous_version_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM dhl_monthly_expense_imports p WHERE p.id = NEW.previous_version_id
    AND p.reporting_month = NEW.reporting_month AND p.version < NEW.version) THEN
  RAISE EXCEPTION 'Previous version must be an earlier version of the same month';
 END IF;
 IF TG_OP = 'UPDATE' AND OLD.status = 'draft' AND NEW.status = 'confirmed' THEN
  IF btrim(NEW.source_verification) = '' OR EXISTS (
    SELECT 1 FROM jsonb_array_elements(NEW.issues) x WHERE (x->>'blocking')::boolean IS DISTINCT FROM false) THEN
   RAISE EXCEPTION 'Unresolved import validation/source verification';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM dhl_monthly_expense_rows WHERE import_id = NEW.id) THEN
   RAISE EXCEPTION 'Cannot confirm an empty import';
  END IF;
  IF EXISTS (SELECT 1 FROM dhl_monthly_expense_rows WHERE import_id = NEW.id GROUP BY normalized_plate HAVING count(*) > 1) THEN
   RAISE EXCEPTION 'Duplicate truck registration';
  END IF;
  SELECT jsonb_agg(h->>'category') INTO categories FROM jsonb_array_elements(NEW.header_mappings) h
    WHERE h->>'classification' = 'expense';
  categories := coalesce(categories, '[]'::jsonb);
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(NEW.header_mappings) h WHERE h->>'classification' = 'unknown') OR EXISTS (
    SELECT 1 FROM jsonb_array_elements_text(categories) c GROUP BY c HAVING count(*) > 1) THEN
   RAISE EXCEPTION 'Unapproved or duplicate expense category mappings';
  END IF;
  FOR r IN SELECT * FROM dhl_monthly_expense_rows WHERE import_id = NEW.id LOOP
   IF r.vehicle_id IS NULL OR r.normalized_plate !~ '^[A-Z0-9]+$'
     OR r.revenue_status NOT IN ('dhl_records','verified_no_activity')
     OR btrim(r.revenue_evidence) = '' OR r.gross IS NULL OR r.operating_expenses IS NULL
     OR r.commission_base IS NULL OR r.commission IS NULL OR r.net_payable IS NULL
     OR (r.revenue_status = 'verified_no_activity' AND r.gross <> 0)
     OR EXISTS (SELECT 1 FROM jsonb_array_elements(r.issues) x WHERE (x->>'blocking')::boolean IS DISTINCT FROM false) THEN
    RAISE EXCEPTION 'Unresolved expense row validation';
   END IF;
   deduction_total := 0;
   FOR entry IN SELECT key, value FROM jsonb_each(r.deductions) LOOP
    IF jsonb_typeof(entry.value->'amount') IS DISTINCT FROM 'string'
      OR (entry.value->>'amount') !~ '^-?[0-9]+\.[0-9]{2}$'
      OR NOT (categories ? entry.key OR (entry.key = 'kasarani_ksm_fuel'
        AND entry.value->>'amount' = '0.00' AND entry.value->>'resolution' = 'absent_optional_category')) THEN
     RAISE EXCEPTION 'Invalid or unapproved deduction JSON';
    END IF;
    deduction_total := deduction_total + (entry.value->>'amount')::numeric;
   END LOOP;
   IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(categories) c WHERE NOT (r.deductions ? c))
     OR r.operating_expenses <> deduction_total OR r.commission_base <> r.gross - deduction_total - dhl_dist_admin_fee(r, NEW.calculation_policy)
     OR r.commission <> round(greatest(r.commission_base, 0) * 0.07, 2)
     OR r.net_payable <> r.commission_base - r.commission THEN
    RAISE EXCEPTION 'Financial totals do not match approved deductions';
   END IF;
  END LOOP;
 END IF;
 RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION dhl_truck_confirmation_guard() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE r dhl_monthly_expense_rows; p dhl_monthly_expense_imports; prev dhl_monthly_truck_confirmations;
 categories JSONB; entry RECORD; total NUMERIC; prior_row dhl_monthly_expense_rows;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF OLD.status='current' AND NEW.status='superseded' AND to_jsonb(OLD)-'status'=to_jsonb(NEW)-'status' THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Truck confirmations are immutable except explicit supersession';
 END IF;
 IF TG_OP<>'INSERT' THEN RAISE EXCEPTION 'Truck confirmation history cannot be deleted or truncated'; END IF;
 SELECT * INTO r FROM dhl_monthly_expense_rows WHERE id=NEW.expense_row_id;
 SELECT * INTO p FROM dhl_monthly_expense_imports WHERE id=r.import_id;
 PERFORM pg_advisory_xact_lock(736281, EXTRACT(YEAR FROM p.reporting_month)::int*12+EXTRACT(MONTH FROM p.reporting_month)::int);
 SELECT * INTO p FROM dhl_monthly_expense_imports WHERE id=r.import_id FOR UPDATE;
 SELECT * INTO r FROM dhl_monthly_expense_rows WHERE id=NEW.expense_row_id;
 IF NEW.status<>'current' OR NEW.reporting_month<>p.reporting_month OR NEW.normalized_plate<>r.normalized_plate
   OR NEW.report_version<>p.version OR NEW.row_sha256 IS DISTINCT FROM dhl_truck_row_hash(r.id)
   OR NEW.parent_sha256 IS DISTINCT FROM dhl_truck_parent_hash(p.id)
   OR NEW.source_sha256 IS DISTINCT FROM dhl_truck_source_hash(r.id)
   OR NEW.validation->>'verified' IS DISTINCT FROM 'true' OR NEW.validation->>'scope_plate' IS DISTINCT FROM r.normalized_plate
   OR (NEW.method='month' AND p.status<>'confirmed') OR (NEW.method='truck' AND p.status<>'draft') THEN
  RAISE EXCEPTION 'Truck confirmation must identify the verified exact financial source';
 END IF;
 SELECT * INTO prev FROM dhl_monthly_truck_confirmations WHERE reporting_month=p.reporting_month
  AND normalized_plate=r.normalized_plate ORDER BY report_version DESC LIMIT 1;
 IF FOUND AND (NEW.previous_confirmation_id IS DISTINCT FROM prev.id OR prev.report_version>=p.version OR prev.status<>'superseded') THEN
  RAISE EXCEPTION 'Correction must explicitly supersede the latest older truck confirmation';
 ELSIF NOT FOUND AND NEW.previous_confirmation_id IS NOT NULL THEN
  RAISE EXCEPTION 'Invalid predecessor confirmation';
 END IF;
 -- A correction records its own immutable difference; it never edits a payment
 -- or infers that the statement was paid. Amounts are decimal strings.
 IF NEW.previous_confirmation_id IS NOT NULL THEN
  SELECT * INTO prior_row FROM dhl_monthly_expense_rows WHERE id=prev.expense_row_id;
  NEW.validation := NEW.validation || jsonb_build_object('financial_adjustment',jsonb_build_object(
   'kind','statement_correction','previous_confirmation_id',prev.id,'previous_expense_row_id',prior_row.id,
   'previous_net_payable',prior_row.net_payable::text,'revised_net_payable',r.net_payable::text,
   'gross_difference',(r.gross-prior_row.gross)::numeric(18,2)::text,
   'expenses_difference',(r.operating_expenses-prior_row.operating_expenses)::numeric(18,2)::text,
   'commission_difference',(r.commission-prior_row.commission)::numeric(18,2)::text,
   'net_payable_difference',(r.net_payable-prior_row.net_payable)::numeric(18,2)::text,
   'payment_processing',false,'payment_status','not_assessed'));
 ELSIF NEW.validation ? 'financial_adjustment' THEN
  RAISE EXCEPTION 'An adjustment requires an earlier confirmed statement';
 END IF;
 IF r.vehicle_id IS NULL OR r.gross IS NULL OR r.operating_expenses IS NULL OR r.commission_base IS NULL
   OR r.commission IS NULL OR r.net_payable IS NULL OR r.revenue_status NOT IN ('dhl_records','verified_no_activity')
   OR btrim(r.revenue_evidence)='' OR btrim(p.source_verification)=''
   OR (r.revenue_status='verified_no_activity' AND r.gross<>0)
   OR EXISTS (SELECT 1 FROM jsonb_array_elements(r.issues) i WHERE (i->>'blocking')::boolean IS DISTINCT FROM false)
   OR (SELECT count(*) FROM dhl_monthly_expense_rows WHERE import_id=p.id AND normalized_plate=r.normalized_plate)<>1 THEN
  RAISE EXCEPTION 'Unresolved target-truck financial validation';
 END IF;
 SELECT coalesce(jsonb_agg(h->>'category'),'[]'::jsonb) INTO categories FROM jsonb_array_elements(p.header_mappings) h WHERE h->>'classification'='expense';
 IF EXISTS (SELECT 1 FROM jsonb_array_elements(p.header_mappings) h WHERE h->>'classification'='unknown')
  OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(categories) c GROUP BY c HAVING count(*)>1) THEN
  RAISE EXCEPTION 'Unapproved or duplicate expense mappings';
 END IF;
 total:=0;
 FOR entry IN SELECT key,value FROM jsonb_each(r.deductions) LOOP
  IF jsonb_typeof(entry.value->'amount') IS DISTINCT FROM 'string' OR (entry.value->>'amount') !~ '^-?[0-9]+\.[0-9]{2}$'
   OR NOT (categories ? entry.key OR (entry.key='kasarani_ksm_fuel' AND entry.value->>'amount'='0.00' AND entry.value->>'resolution'='absent_optional_category')) THEN
   RAISE EXCEPTION 'Invalid deduction snapshot';
  END IF;
  total:=total+(entry.value->>'amount')::numeric;
 END LOOP;
 IF EXISTS (SELECT 1 FROM jsonb_array_elements_text(categories) c WHERE NOT (r.deductions ? c))
  OR total<>r.operating_expenses OR r.commission_base<>r.gross-total-dhl_dist_admin_fee(r, p.calculation_policy)
  OR r.commission<>round(greatest(r.commission_base,0)*0.07,2) OR r.net_payable<>r.commission_base-r.commission THEN
  RAISE EXCEPTION 'Truck totals do not match approved deductions';
 END IF;
 RETURN NEW;
END $$;
