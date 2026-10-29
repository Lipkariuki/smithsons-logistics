# Independent truck confirmation — local implementation and migration review

Status: implemented and tested locally only. No production migration, commit,
push, deployment, delivery call or real February confirmation is authorized by
this document. Backend HEAD remains 6f05d75213b9430addac7ddedfa2ec1df8b778cc;
frontend HEAD remains adbd135143653ab23cc68ae50632bd368abd96a5. Both have additional
uncommitted work; neither old release manifest describes the new release.

## Database design for approval

Pending prerequisites remain separate files:

| Migration | Purpose |
|---|---|
| 001 | Already applied in production: monthly imports and financial rows |
| 002 | Pending: append-only stored statement PDFs, hashes and predecessor links |
| 003 | Pending: allow zero expenses when a workbook has no expense columns |
| 004 | NEW: independent truck approvals and source-freezing/compatibility guards |

004 adds ONE table, dhl_monthly_truck_confirmations:

- id: bigint identity primary key.
- expense_row_id: unique FK to the exact existing monthly financial row.
- reporting_month, normalized_plate, report_version: checked against that row's parent.
- status: current or superseded. A partial unique index permits only ONE current
  approval per normalized truck and reporting month.
- method: truck or month, distinguishing explicit truck approval from whole-month approval.
- previous_confirmation_id: self-FK, validated as the latest earlier approval of
  the same truck/month. Corrections must advance the source report version.
- confirmer_id, confirmed_at, reason: immutable administrator audit details.
- row_sha256, parent_sha256, source_sha256: hashes of the exact row, immutable
  parent contents and selected-truck source records.
- validation: JSONB containing the scoped policy, raw workbook checksum, verified
  scope and unresolved OTHER-truck historical row numbers. These are explicitly
  not approvals of the other trucks.

Financial amounts are NOT duplicated. The existing NUMERIC totals and JSONB
deductions remain the authoritative frozen snapshot. The PDF's row FK plus the
unique truck-confirmation row link identify its approval without adding another
column to the document table.

004 also adds database triggers/functions that:

1. Check financial arithmetic, valid deductions, approved mappings, source identity,
   exact hashes and a complete target row before inserting an approval.
2. Allow only current-to-superseded metadata transitions. Reject financial/audit
   edits, deletes and truncation of confirmation history.
3. Require a successor in the SAME transaction when superseding an approval; a
   deferred constraint prevents committing a revoked current approval alone.
4. Freeze the entire parent workbook/version, its evidence/mappings and all its
   rows once ANY truck is approved. Subsequent corrections use the existing new-
   version workflow. Whole-month confirmation/supersession metadata may still change.
5. Register rows during ordinary whole-month confirmation. Existing CURRENT
   whole-month confirmations are registered during migration with their original
   confirmer/timestamp, without recalculation or source/PDF changes. Superseded
   historical months remain readable without inventing new approvals.
6. Extend the statement insertion guard to accept an immutable truck approval
   even while the parent month remains a draft.

004 changes NO legacy orders, trips, manual expenses, commissions, users, vehicles
or historical payslip records. It drops/renames no tables/columns. It DOES add
guards to existing monthly tables, replace the new statement guard function and
backfill the NEW registry; it is not merely an empty-table creation.

## Confirmation behavior and concurrency

POST /dhl-reports/expense-rows/{row_id}/confirm is protected by the existing
require_role('admin') dependency. Anonymous requests return 401, non-admin roles
403. The strictly validated body accepts only a review reason and optional
expected_current_confirmation_id, never financial values or approval flags.

The server reparses retained expense/raw workbooks, verifies checksums, rebuilds
the selected truck and checks it against the saved figures. Gross remains DIST +
Offloading; Admin is never a deduction. Expenses come only from that version's
workbook. Commission remains 7% of positive gross less expenses, ROUND_HALF_UP.

Shared month/header/identity/integrity failures still block affected approvals.
Known OTHER-truck date/source problems do not block a verified truck. Unattributable
raw date issues remain blocking because their financial scope cannot be established.
The selected truck's live source records must match its frozen candidate exactly;
an unrelated truck's live source change does not force rejection of unchanged
target figures. Full-month confirmation retains its original stronger all-row and
full-month fingerprint checks. Operational missing REF NO findings are advisory,
not an input into truck approval.

All approval and PDF paths use a consistent month advisory lock then parent-row
lock. The current-per-truck index provides an additional database constraint.
Retries of an existing current approval are idempotent. Competing report versions
cannot both become current without explicit predecessor review. A stale expected
confirmation receives 409; there is no automatic retry/overwrite.

A newer workbook never revokes a prior truck approval automatically. Correcting
Truck B in version 2 leaves Truck A's version-1 approval and PDF current. Correcting
A itself requires explicitly approving its newer row and identifying its current
approval. The old approval/PDF stay in history. Omitting A entirely from the new
workbook also leaves its prior approval visible; omission is NOT a cancellation.

Ordinary whole-month confirmations and whole-month corrections still work. A
whole-month action cannot silently replace a separately approved truck from a
different version: confirm that truck's correction explicitly first. Confirming
the same parent month after its individual trucks were approved preserves those
approval IDs/reasons instead of replacing them.

## PDF source and exact itemization

Only an existing whole-month approval or an immutable truck approval permits new
PDF generation. Generation reads frozen row values, not live revenue, current
owner data, manually entered deductions or historical payslip calculations.

The new renderer:

- Prints Smithsons Logistics branding, month, source report/version/row and truck
  approval reference. Corrections identify the prior truck confirmation.
- Prints EVERY non-zero approved operating expense, including credits/negative
  values, using its retained original workbook header and exact approved decimal
  amount. Zero categories are omitted from itemization.
- Verifies the sum of printed items equals Total Expenses exactly, separately
  from commission. Gross, commission base, commission and net use stored NUMERIC values.
- Preserves zero-business and negative balances. Missing data is not fabricated
  into zero activity; verified evidence is still required.
- Bundles unchanged open-licensed DejaVu fonts plus their license so Unicode
  descriptions such as “Repairs – Côte” remain exact. Unsupported glyphs are rejected
  rather than silently replaced. Long labels wrap; table rows can continue on new pages.
- Stores immutable bytes, SHA-256 and renderer version. Reprints return those
  same bytes. Existing PDFs are never regenerated in place, including old-format PDFs.
- States that the document is not a payment receipt. No payment/SMS/email is issued.

Synthetic March sample: output/pdf/smithsons_per_truck_confirmation_sample.pdf.
It is NOT a real February statement or a business approval: gross 1,000.00,
expenses 275.00, commission 50.75, net 674.25, with an unrelated unresolved truck.

## Administrator workflow and reporting

The existing Monthly Expense Reports truck rows now show Pending confirmation,
Needs review, Confirmed, Historical confirmed or Superseded. Expanded rows explain
blocking issues and provide Confirm this truck, with a reason and a financial
confirmation dialog. A successful approval enables its statement download while
other rows remain unresolved. Approval timestamp/reason remain visible.

Monthly status remains draft until the existing whole-month action succeeds;
partial approval is derived display metadata, not a misleading new month status.
The selected workbook's original totals remain unchanged. A separate collapsible
Current approved trucks across report versions view shows one current approval per
truck, its actual source version and server-calculated approved totals. This also
keeps omitted trucks visible and provides their exact-version statement downloads.
Those totals are NOT accumulated expense uploads or proof of payments made.

The existing DHL Reconciliation page reads these states. A missing operational
reference remains visible while a financially approved truck can show eligible.
When the selected workbook omits an approved truck, its prior confirmation is
identified separately instead of inventing new workbook expenses. No new navigation
item, duplicate dashboard, authentication change or importer rewrite was added.

## Exact production sequence — requires separate approval

1. Review this design and SQL 002/003/004, final code diffs and a new explicit file
   manifest. Exclude unrelated insurance/SMS edits, financial workbooks, generated
   PDFs/output, backups, credentials and local configuration. No commits/pushes yet.
2. Record the actual current Render backend AND frontend deployment commits for
   rollback. The known backend is 6f05d75213b9; do not treat the unpushed frontend
   commit as the currently deployed frontend. Treat later Git pushes as auto-deploys.
3. Before migration, verify the intended Railway database identity against Render
   smithsons-logistics DATABASE_URL privately. Create a NEW custom pg_dump backup
   including current monthly rows/documents and restore-verify it. Existing pre-001
   backups alone are insufficient for new reporting history.
4. Pause financial writes for a short migration window. Read-only preflight:
   verify 001 tables/functions, actual 002/003/004 state, current monthly approval
   counts and existing table counts. Review how many existing approvals 004 will
   register. Test the exact SQL on a disposable copy before production execution.
5. If ONLY 001 exists, privately configure TRUCK_CONFIRMATION_MIGRATION_URL on the
   release workstation (not in Git, shell arguments/output or Render variables).
   Review with:

       venv/bin/python scripts/migrate_truck_confirmations.py --allow-nonlocal --include-prerequisites

   After explicit execution approval, the command is:

       venv/bin/python scripts/migrate_truck_confirmations.py --allow-nonlocal --include-prerequisites --apply

   This executes 002, 003 and 004 in ONE psycopg transaction, with a migration
   advisory lock, 5-second lock timeout and 120-second statement timeout. 004 takes
   brief ACCESS EXCLUSIVE locks on the two monthly tables so source freezing and
   backfill cannot race writes. Any failure rolls back all SQL/function changes.
   If 002/003 already exist, inspect their definitions first and omit the prerequisite
   flag only when both have been verified. Never blindly rerun CREATE TABLE migrations.
6. Verify new table/FKs/current index/guards, registration counts and unchanged
   original financial records/PDF hashes. Do not restart or reconfigure Railway,
   touch its pending service change, or touch Render smithsons-logistics-1.
7. Only after separate code-release approval: create reviewed backend/frontend
   commits, push/deploy backend to Render smithsons-logistics first, then verify
   startup, existing reporting/auth and read-only new API/report access. Keep the
   existing JWT/SMS/database configuration unchanged; no new Render app variable
   is required by this feature. Verify bundled font assets are present.
8. Push/deploy the reviewed frontend to smithsons-logistics-frontend only after
   the backend is healthy. Retain its correct VITE_API_BASE_URL. Test login, saved
   report/history display, pending/confirmed labels, current-version downloads and
   old PDFs. Do not generate/confirm real records simply to smoke-test deployment.
9. Resume financial operations only after those checks. Any first real truck
   approval requires an administrator's genuine source review. February remains
   unapproved; the six historical adjustments and actual no-activity evidence are
   not resolved by deployment.

## Rollback and decisions still required

Before COMMIT, any migration failure rolls back atomically. After successful
migration, use application rollback; do NOT drop new approval/PDF history or
reactivate superseded approvals. Roll back frontend first if it depends on new
routes, then backend to its recorded known-good commit. The old backend will not
expose per-truck controls and may reject newer-policy drafts; keep data intact and
restore compatible code. Do not routinely restore an entire old database backup
over newer financial records. Schema reversal requires a separately reviewed plan.

Approval is still required for the production migration batch, reviewed commits,
pushes and deployments. The business requirement approval is not execution approval.

This system prevents duplicate/current approval conflicts and duplicate PDF creation;
it does NOT maintain a cash-disbursement ledger. If a previously issued statement
was already paid, a corrected statement is not automatically an additional payment.
The approved policy preserves original statements/payment history and records the
difference separately. Each successor confirmation now contains an immutable
financial_adjustment audit object with predecessor identity and Decimal-string
gross/expense/commission/net differences. The PDF shows the separate net adjustment.
Payment status is not inferred, and no payment/settlement processing is introduced.
Automatic cancellation/voiding on roster omission is intentionally not implemented.
Existing legacy manual-generation APIs remain unchanged; no old manual expenses
enter this new flow. A future retirement/cutover of legacy new-generation controls
is a separate business decision, not a hidden financial-formula change here.

As with the existing snapshot design, privileged database administrators can bypass
ordinary triggers; restrict that access and retain backups/audit evidence. No
database-role/credential changes were made in this phase.

## Changes in this phase

New: migrations/004_monthly_truck_confirmations.sql;
services/truck_confirmations.py; scripts/migrate_truck_confirmations.py;
tests/test_truck_confirmations.py; this release plan;
assets/fonts/DejaVuSans.ttf, DejaVuSans-Bold.ttf and DejaVu-LICENSE.txt;
frontend tests/truckConfirmation.real.browser.test.mjs.

Updated: services/monthly_expense_dates.py (scoped source validation),
services/monthly_expense_persistence.py (whole-month conflict preflight),
services/monthly_statement_documents.py (approved source + exact itemization),
services/dhl_reconciliation_detail.py (truck approval state),
routers/monthly_expense_reports.py (display metadata),
routers/monthly_statement_documents.py (admin confirmation endpoint),
frontend MonthlyExpenseReports.jsx and DhlReconciliationDetails.jsx;
frontend tests/monthlyExpenses.browser.test.mjs (current-approved-version panel).

Existing unrelated local edits and previous uncommitted financial/reconciliation
work were preserved. No production configuration or data was changed. A subsequent readiness pass
performed the separately requested read-only backup and offline restore rehearsal;
see docs/final-production-release-readiness.md.


## Final local verification — 29 October 2026

- Backend: 139 tests passed, none skipped, using isolated PostgreSQL schemas and
  real local authenticated HTTP regression checks. Includes 17 truck-confirmation
  tests covering concurrency, immutability, replacements, source/date scope,
  whole-month compatibility, migration backfill/rollback and PDF itemization.
- Frontend: all 41 tests passed, none skipped. Includes real browser testing
  against the local FastAPI backend and disposable PostgreSQL without mocked
  financial responses: one synthetic truck confirmed and downloaded its stored
  PDF while another remained unresolved and the month remained draft.
- Production frontend build passed. Existing bundle-size/Browserslist warnings
  remain; no unrelated package upgrades were made.
- Python compilation and whitespace checks passed. Synthetic PDF text/metadata
  and rendered page were checked: exact Unicode workbook descriptions, non-zero
  itemization, expense sum, frozen totals, Smithsons branding and EAT timestamp.
- Sample: output/pdf/smithsons_per_truck_confirmation_sample.pdf (synthetic only;
  generated output is excluded from release manifests).

No production financial records, schema, configuration, stored PDFs or February
approvals were changed. No commit, push, deployment, SMS or email was performed.
