# Financial completion and snapshot truck statements — local review

Production remains at backend commit `6f05d75213b9430addac7ddedfa2ec1df8b778cc`.
The original frontend commit `adbd135143653ab23cc68ae50632bd368abd96a5` is unchanged and unpushed.
Everything below is a separate, uncommitted local change; no production migration,
financial write, SMS, confirmation or deployment was performed.

## Source-of-truth clarification

The newly approved workbook expense policy replaces the previous blank-cell blocker.
Blanks become decimal zero with source cell, original value, interpreted amount and
policy in cell_audit; deductions use resolution `blank_to_zero`. Unknown headers
still require administrator classification. Formula cells without cached values
remain errors: a missing formula result is not a blank spreadsheet cell.

Absent known categories generate visible assumptions and contribute zero. Absent
dynamic categories contribute zero by omission; they are never copied from a prior
version. Numeric cells use Decimal(str(value)), ROUND_HALF_UP to two decimals.
Nonmatching API correction values are rejected: replace the workbook to correct
expenses. Identical legacy correction inputs are accepted without changing amounts.
No manual/trip expenses or earlier import deductions are queried or combined.

Calculation policy is now monthly-expenses-v2 / flexible-xlsx-v2. Pre-change drafts
must be revised into a new version; confirmed old snapshots stay unchanged. Each
replacement re-parses only its own retained workbook. Existing source provenance,
date exclusion evidence, revenue completeness and no-activity confirmation remain
required. This does not approve any February record.

## February verification

Exact workbooks: data/FEBRUARY 2026 TRIPS SUMMARY.xlsx and
data/FEBRUARY NET SUMMARY 1.xlsx. Run scripts/verify_dhl_revenue.py then
scripts/reconcile_february_snapshots.py. The first uses isolated SQLite and denies
network; the second has no database or network access. No source workbook changes.

- DIST: KES 9,560,700.63; Offloading: KES 297,461.00.
- Gross: KES 9,858,161.63; all 25 revenue trucks match existing importer/report/
  reconciliation/monthly-source amounts to the cent.
- Admin: KES -475,891.06, audit-only; never deducted or reclassified as expenses.
- Operating expenses across 32 spreadsheet trucks: KES 4,684,756.77.
- Known commission subtotal: KES 365,840.49.
- Known net subtotal: KES 4,835,114.37.
- Seven unknown-revenue trucks: KBE438V, KBK988F, KBM439P, KCA661S,
  KCE726U, KCH333X, KDG264X. Commission/net subtotals are NOT complete monthly totals.
- KCE726U D17 is now audited zero under the user's new policy, not a fabricated
  individual approval. Its revenue remains unverified.
- Per-truck operating expenses match direct workbook category sums (difference zero).
  No gross column exists. Commission reference basis and NET PAID I/2/final meanings
  remain unverified: no final commission/net differences are asserted from them.
- Historical rows 850–855 (2024/2025) remain excluded and unresolved. Exact dates,
  references and amounts are in output/dhl-revenue-verification/excluded-historical-rows.csv.

Per-truck category/financial values, manual raw references and comparison limitations:
output/financial-completion/february-reconciliation.csv. Monthly completeness:
output/financial-completion/february-summary.json. These are private generated review
outputs, excluded from any commit along with both source workbooks.

## New individual truck statements

One additive append-only `monthly_statement_documents` table references only the
immutable monthly row; no monetary duplication and no legacy payslip relationships.
One stored PDF per source row; renderer changes cannot silently replace it.
Stored bytes, SHA-256, renderer version, generating administrator/time and predecessor
document are retained. Update, delete and truncate are blocked by database triggers.
Application-parent locks plus uniqueness serialize concurrent generation.

Financial presentation uses only the selected confirmed monthly snapshot (including
previously confirmed/superseded versions); stored arithmetic is integrity-checked,
never replaced with live DHL, vehicle, owner or manual expense values. Old PDFs are
downloaded byte-for-byte; corrected monthly versions create new documents. Generation
does not record payment, send anything, or modify manual payslips.

Admin-only API additions:

- POST /dhl-reports/monthly-statement-documents/from-row/{row_id}: explicit, idempotent generation.
- GET /dhl-reports/monthly-statement-documents/{document_id}/pdf: stored PDF/hash, no-store.
- GET /dhl-reports/expense-imports/{import_id}/statement-documents: metadata history.

Frontend local changes remove expense override controls, explain audited zeros and
replacement workbooks, and offer Generate / download truck statement on expanded
confirmed/historical truck rows. A confirmation dialog names truck/source version.
No financial arithmetic is added to React. The original approved frontend commit
does not contain these changes and must not be represented as the completed release.

## Separate migrations — NOT approved or applied in production

002_monthly_statement_documents.sql: new table, index, guard function and triggers.
It neither alters nor replaces historical manual payslip tables.

003_expense_zero_policy.sql: replaces only the monthly confirmation guard function
to allow an empty approved category list when the workbook contains no expense
columns. All existing financial/revenue/immutability checks remain. No rows are
updated; 001 is left untouched. This is a separate schema-function change requiring
explicit production approval, even though common workbooks already work with 001.

Both were applied only in disposable PostgreSQL tests. Execute each as a single
transaction after a new backup and target verification. Never run automatically on
startup. scripts/migrate_monthly_statements.py is the explicit 002 runner, using
MONTHLY_STATEMENT_MIGRATION_URL and --apply; nonlocal execution additionally requires
--allow-nonlocal and user approval. For 003 use an explicitly configured psycopg
connection transaction with local lock/statement timeouts, or a separately reviewed
release migration runner. Never put credentials on a command line.

## Production verification and deployment gates

Public OpenAPI returned 200 and advertises the monthly preview/save/revise/retrieve/
confirm/summary/export routes. Anonymous monthly summary, import retrieval and DHL
summary return 401. Current public frontend bundle names the intended backend URL
and not the unused service. Render's next-build environment cannot be independently
inspected with the available tools.

No production admin browser session is available to these tools. User authorization
alone does not supply a session. Authenticated summary/history/retrieval/exports
remain PENDING; no token was requested, forged or logged. Where no confirmed report
exists, summary 404 is expected. Do not invent an import ID or generate production
documents to test retrieval. Existing APIs expose history through versioned summary
retrieval (version=1 includes versions); no GET import-list endpoint exists.

Release order after review/approval: verify authenticated existing live endpoints;
fresh backup and target check; separately approved additive 002 and policy 003;
review/commit/push new backend; verify startup and read-only APIs; review/commit/push
updated frontend; smoke-test only existing approved records. Do not approve February.
Do not push the old frontend as if it includes new policy/statement integration.
Only smithsons-logistics and smithsons-logistics-frontend are deployment targets.

Rollback: revert to the prior known-good application commits. Keep new document
storage and all history; do not drop tables or delete documents. Old backend logic
cannot confirm v2 drafts; preserve them until the compatible release is restored.
Restoring an entire production backup is not a routine code rollback.

## Verification performed

- 100 backend tests passed without skips in the final suite: monthly parser,
  persistence, API, Decimal calculations, source policy, immutable statements,
  real workbook revenue, branded PDFs and production configuration.
- One additional focused test passed for statement generation from an explicitly
  verified zero-activity truck: expenses remain 200.00, commission 0.00, net -200.00.
- 20 frontend unit tests, nine mocked reporting browser tests (including explicit
  statement generation/download), and one login-logging browser test passed.
- Production frontend build passed. Existing bundle-size and stale Browserslist
  advisory warnings remain; no dependency upgrades were made.
- Python compilation and both repositories' diff whitespace checks passed.
- Synthetic sample PDF generated from a confirmed disposable PostgreSQL snapshot,
  extracted to verify financial values/header/metadata, rendered with Poppler and
  visually inspected. Optional existing gradient SVG is unsupported by FPDF; the
  renderer preserves the legacy text-header fallback. No new PDF dependency.
- Statement migrations exercised against disposable PostgreSQL: rollback on error,
  insert idempotency/concurrency, update/delete/truncate denial, historic version
  reprints, source replacement preservation, blank/missing categories, and complete
  zero-expense confirmation. Existing legacy financial sentinels stayed unchanged.
- Eight existing standalone real-HTTP legacy authorization tests were not rerun
  because their separate fixture server was not running. No additional production
  owner/driver checks were attempted, as requested. New statement role restrictions
  were tested through the existing JWT/role dependencies against local PostgreSQL.

The new browser test uses intercepted APIs; it is not a real production or full
frontend-to-backend end-to-end result. Statement service/API tests use real local
PostgreSQL and ASGI. Authenticated production checks still require a usable admin
session or user-provided status-only results; public OpenAPI/401 checks do not
prove authenticated data access.

## Changed files in this separate release

Backend: main.py; services/monthly_expense_parser.py;
services/monthly_expense_persistence.py; services/monthly_statement_documents.py;
routers/monthly_statement_documents.py; migrations/002_monthly_statement_documents.sql;
migrations/003_expense_zero_policy.sql; scripts/migrate_monthly_statements.py;
scripts/reconcile_february_snapshots.py; tests/test_monthly_expenses.py;
tests/test_monthly_expense_persistence.py; tests/test_monthly_expense_api.py;
tests/test_monthly_statement_documents.py; tests/test_expense_source_policy.py;
this document.

Frontend: src/pages/reports/MonthlyExpenseReports.jsx;
src/pages/reports/monthlyExpenseUi.js; tests/monthlyExpenses.browser.test.mjs.

Pre-existing insurance/SMS edits in fleet_schemas.py, routers/fleet.py and
services/fleet_notifications.py were not touched and must stay outside the release.
