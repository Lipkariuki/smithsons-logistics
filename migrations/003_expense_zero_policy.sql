-- Explicit policy upgrade: transactional, no data updates or legacy DDL.
-- Allows zero expenses when a workbook includes no expense columns.
-- Existing confirmed snapshots and all remaining guards are unchanged.
CREATE OR REPLACE FUNCTION dhl_monthly_guard_import() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE r RECORD; entry RECORD; deduction_total NUMERIC; categories JSONB;
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
     OR r.operating_expenses <> deduction_total OR r.commission_base <> r.gross - deduction_total
     OR r.commission <> round(greatest(r.commission_base, 0) * 0.07, 2)
     OR r.net_payable <> r.commission_base - r.commission THEN
    RAISE EXCEPTION 'Financial totals do not match approved deductions';
   END IF;
  END LOOP;
 END IF;
 RETURN NEW;
END $$;
