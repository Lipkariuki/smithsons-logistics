-- Explicit opt-in cent policy. No row writes, table/column changes or backfill.
-- Apply after 006, inside one transaction. Existing confirmed snapshots stay v1.
CREATE OR REPLACE FUNCTION dhl_component_cent_admin_fee(r dhl_monthly_expense_rows, policy JSONB)
RETURNS NUMERIC LANGUAGE plpgsql STABLE AS $$
DECLARE s JSONB; t JSONB; field TEXT; original NUMERIC; delta NUMERIC;
 dist_original NUMERIC:=0; off_original NUMERIC:=0; proxy dhl_monthly_expense_rows; legacy_policy JSONB;
BEGIN
 s:=r.cell_audit->'_dhl_transport';
 IF (SELECT decisions->>'accept_cent_differences' FROM dhl_monthly_expense_imports WHERE id=r.import_id) IS DISTINCT FROM 'true' THEN
  RAISE EXCEPTION 'Explicit administrator cent-policy decision is required';
 END IF;
 IF policy->>'version' IS DISTINCT FROM 'monthly-expenses-v4-components-cent'
  OR policy->>'transport_policy' IS DISTINCT FROM 'dist-components-cent-v1'
  OR policy->>'source_cent_policy' IS DISTINCT FROM 'amount_plus_surcharge_max_0.01_dist_only'
  OR s->>'policy' IS DISTINCT FROM 'dist-components-cent-v1'
  OR jsonb_typeof(s->'transactions') IS DISTINCT FROM 'array' THEN
  RAISE EXCEPTION 'Invalid component cent policy';
 END IF;
 FOR t IN SELECT value FROM jsonb_array_elements(s->'transactions') LOOP
  FOREACH field IN ARRAY ARRAY['source_inclusive','source_adjustment','inclusive'] LOOP
   IF jsonb_typeof(t->field) IS DISTINCT FROM 'string' OR (t->>field) !~ '^-?[0-9]+\.[0-9]{2}$' THEN
    RAISE EXCEPTION 'Original source values and signed adjustment are required';
   END IF;
  END LOOP;
  original:=(t->>'source_inclusive')::numeric;delta:=(t->>'source_adjustment')::numeric;
  IF (t->>'inclusive')::numeric-original<>delta OR abs(delta)>0.01
   OR (t->>'cost' IS DISTINCT FROM 'dist' AND delta<>0) THEN
   RAISE EXCEPTION 'Only one-cent DIST differences may use calculated components';
  END IF;
  IF t->>'cost'='dist' THEN dist_original:=dist_original+original;
  ELSIF t->>'cost'='offloading' THEN off_original:=off_original+original;
  ELSE RAISE EXCEPTION 'Invalid transport COST'; END IF;
 END LOOP;
 IF dist_original<>(SELECT coalesce(sum((x->>'distribution_cost')::numeric),0) FROM jsonb_array_elements(r.dhl_source_snapshot) x)
  OR off_original<>(SELECT coalesce(sum((x->>'offloading_cost')::numeric),0) FROM jsonb_array_elements(r.dhl_source_snapshot) x) THEN
  RAISE EXCEPTION 'Original source values do not match retained ledger snapshot';
 END IF;
 -- Validation-only typed copy: never UPDATE stored source or ledger values.
 -- Reuse the unchanged v1 validator for identities, sums and per-row fees.
 proxy:=r;
 proxy.cell_audit:=jsonb_set(r.cell_audit,'{_dhl_transport,policy}','"dist-surcharge-admin-v1"'::jsonb);
 proxy.dhl_source_snapshot:=jsonb_build_array(jsonb_build_object(
  'distribution_cost',((s->>'distribution')::numeric+(s->>'surcharge')::numeric)::text,
  'offloading_cost',s->>'offloading'));
 legacy_policy:=(policy-'source_cent_policy')||jsonb_build_object(
  'version','monthly-expenses-v3-dist-admin','transport_policy','dist-surcharge-admin-v1');
 RETURN dhl_dist_admin_fee(proxy,legacy_policy);
END $$;

CREATE OR REPLACE FUNCTION dhl_dist_admin_fee(r dhl_monthly_expense_rows, policy JSONB)
RETURNS NUMERIC LANGUAGE plpgsql STABLE AS $$
DECLARE s JSONB; t JSONB; a NUMERIC; extra NUMERIC; inclusive NUMERIC; fee NUMERIC;
 dist NUMERIC:=0; offload NUMERIC:=0; surcharge NUMERIC:=0; fees NUMERIC:=0;
 month DATE; field TEXT; seen JSONB:='[]'::jsonb;
BEGIN
 IF policy->>'version'='monthly-expenses-v4-components-cent' THEN
  RETURN dhl_component_cent_admin_fee(r,policy);
 END IF;
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
