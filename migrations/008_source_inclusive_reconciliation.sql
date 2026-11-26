-- Depends on 006 and 007. Transactional function extension only; no data writes.
CREATE OR REPLACE FUNCTION dhl_inclusive_rounding_admin_fee(r dhl_monthly_expense_rows, policy JSONB)
RETURNS NUMERIC LANGUAGE plpgsql STABLE AS $$
DECLARE s JSONB; t JSONB; proof JSONB; field TEXT; a NUMERIC; extra NUMERIC; inclusive NUMERIC;
 delta NUMERIC; q NUMERIC; net NUMERIC; signed_total NUMERIC:=0; absolute_total NUMERIC:=0;
 batch_absolute NUMERIC; transformed JSONB:='[]'::jsonb; proxy dhl_monthly_expense_rows; legacy_policy JSONB;
BEGIN
 s:=r.cell_audit->'_dhl_transport';
 IF policy->>'version' IS DISTINCT FROM 'monthly-expenses-v5-source-inclusive'
  OR policy->>'transport_policy' IS DISTINCT FROM 'source-inclusive-reconciled-v1'
  OR policy->>'source_cent_policy' IS DISTINCT FROM 'corroborated_inclusive_unchanged'
  OR policy->>'transaction_tolerance' IS DISTINCT FROM '0.01'
  OR policy->>'truck_absolute_cap' IS DISTINCT FROM '0.05'
  OR policy->>'month_absolute_cap' IS DISTINCT FROM '0.25'
  OR s->>'policy' IS DISTINCT FROM 'source-inclusive-reconciled-v1'
  OR jsonb_typeof(s->'transactions') IS DISTINCT FROM 'array'
  OR (SELECT decisions->>'source_reconciliation_policy' FROM dhl_monthly_expense_imports WHERE id=r.import_id)
     IS DISTINCT FROM 'source-inclusive-reconciled-v1' THEN
  RAISE EXCEPTION 'Invalid source-inclusive reconciliation policy';
 END IF;
 FOREACH field IN ARRAY ARRAY['rounding_difference','rounding_absolute_total','month_rounding_absolute_total'] LOOP
  IF jsonb_typeof(s->field) IS DISTINCT FROM 'string' OR (s->>field) !~ '^-?[0-9]+\.[0-9]{2}$' THEN
   RAISE EXCEPTION 'Missing source rounding totals';
  END IF;
 END LOOP;
 FOR t IN SELECT value FROM jsonb_array_elements(s->'transactions') LOOP
  FOREACH field IN ARRAY ARRAY['amount','surcharge','inclusive'] LOOP
   IF jsonb_typeof(t->field) IS DISTINCT FROM 'string' OR (t->>field) !~ '^-?[0-9]+\.[0-9]{2}$' THEN
    RAISE EXCEPTION 'Invalid source financial amount';
   END IF;
  END LOOP;
  a:=(t->>'amount')::numeric;extra:=(t->>'surcharge')::numeric;inclusive:=(t->>'inclusive')::numeric;
  delta:=inclusive-a-extra;proof:=t->'rounding_reconciliation';
  IF delta<>0 THEN
   IF t->>'cost' IS DISTINCT FROM 'dist' OR abs(delta)<>0.01
    OR proof->>'status' IS DISTINCT FROM 'accepted_source_rounding'
    OR proof->>'evidence' IS DISTINCT FROM 'inclusive_fee_and_net_references_consistent'
    OR proof->>'amount' IS DISTINCT FROM t->>'amount'
    OR proof->>'surcharge' IS DISTINCT FROM t->>'surcharge'
    OR proof->>'inclusive' IS DISTINCT FROM t->>'inclusive' THEN
    RAISE EXCEPTION 'Uncorroborated inclusive source mismatch';
   END IF;
   FOREACH field IN ARRAY ARRAY['difference','fee_reference','net_reference'] LOOP
    IF jsonb_typeof(proof->field) IS DISTINCT FROM 'string' OR (proof->>field) !~ '^-?[0-9]+(\.[0-9]+)?$' THEN
     RAISE EXCEPTION 'Invalid rounding corroboration amount';
    END IF;
   END LOOP;
   q:=(proof->>'fee_reference')::numeric;net:=(proof->>'net_reference')::numeric;
   IF (proof->>'difference')::numeric<>delta
    OR NOT (abs(q-inclusive*0.05)<=0.00000001 OR q=round(inclusive*0.05,2))
    OR NOT (abs(net-(inclusive-q))<=0.00000001 OR net=round(inclusive-q,2)) THEN
    RAISE EXCEPTION 'Contradictory source fee/net references';
   END IF;
   signed_total:=signed_total+delta;absolute_total:=absolute_total+abs(delta);
  ELSIF proof IS NOT NULL THEN RAISE EXCEPTION 'Unexpected rounding proof on an exact row';
  END IF;
  -- Validation-only adjustment reconciles the independent source columns for
  -- the unchanged v1 guard. Neither the workbook nor stored amounts are edited.
  transformed:=transformed||jsonb_build_array(jsonb_set(t,'{surcharge}',to_jsonb((extra+delta)::numeric(18,2)::text)));
 END LOOP;
 IF signed_total<>(s->>'rounding_difference')::numeric
  OR absolute_total<>(s->>'rounding_absolute_total')::numeric OR absolute_total>0.05
  OR (s->>'month_rounding_absolute_total')::numeric<absolute_total
  OR (s->>'month_rounding_absolute_total')::numeric>0.25 THEN
  RAISE EXCEPTION 'Source rounding cumulative limits exceeded';
 END IF;
 SELECT coalesce(sum(CASE WHEN x->'rounding_reconciliation'->>'difference' ~ '^-?[0-9]+\.[0-9]{2}$'
    THEN abs((x->'rounding_reconciliation'->>'difference')::numeric) ELSE 0 END),0)
 INTO batch_absolute FROM dhl_monthly_expense_rows other,
 LATERAL jsonb_array_elements(coalesce(other.cell_audit->'_dhl_transport'->'transactions','[]'::jsonb)) x
 WHERE other.import_id=r.import_id;
 IF batch_absolute>0.25 OR batch_absolute>(s->>'month_rounding_absolute_total')::numeric THEN
  RAISE EXCEPTION 'Monthly absolute source rounding limit exceeded';
 END IF;
 proxy:=r;
 proxy.cell_audit:=jsonb_set(r.cell_audit,'{_dhl_transport}',s||jsonb_build_object(
  'policy','dist-surcharge-admin-v1','transactions',transformed,
  'surcharge',((s->>'surcharge')::numeric+signed_total)::numeric(18,2)::text));
 legacy_policy:=(policy-'source_cent_policy'-'transaction_tolerance'-'truck_absolute_cap'-'month_absolute_cap')
  ||jsonb_build_object('version','monthly-expenses-v3-dist-admin','transport_policy','dist-surcharge-admin-v1');
 RETURN dhl_dist_admin_fee(proxy,legacy_policy);
END $$;

CREATE OR REPLACE FUNCTION dhl_dist_admin_fee(r dhl_monthly_expense_rows, policy JSONB)
RETURNS NUMERIC LANGUAGE plpgsql STABLE AS $$
DECLARE s JSONB; t JSONB; a NUMERIC; extra NUMERIC; inclusive NUMERIC; fee NUMERIC;
 dist NUMERIC:=0; offload NUMERIC:=0; surcharge NUMERIC:=0; fees NUMERIC:=0;
 month DATE; field TEXT; seen JSONB:='[]'::jsonb;
BEGIN
 IF policy->>'version'='monthly-expenses-v5-source-inclusive' THEN
  RETURN dhl_inclusive_rounding_admin_fee(r,policy);
 END IF;
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
