# Simple DHL Monthly Payouts — local review

Status: simplified workflow approved for isolated local release commits. Existing workbook and financial records will be retained. Push, deployment and production financial writes are not authorized in this preparation phase.

## Main workflow

The existing Reports → DHL Payouts route contains one month selector, two automatically saved workbook cards, four financial totals, and one truck table. Review shows source revenue components and original non-zero expense descriptions. One explicit truck acknowledgement precedes confirmation and issuance. Downloads reuse the immutable stored PDF. Unknown categories and provenance history remain under Advanced Details. Missing revenue/expense rows remain visible; they are never assumed to be zero.

Removed from the active route: the former `DhlReportsPage` legacy summary/upload/manual-payslip forms, manual expense entry, Update Payslip, Store & Send, duplicate monthly summary and version selectors. `MonthlyExpenseReports.jsx` and `SavedMonthlyFiles.jsx` remain in source for audit/reference but are no longer mounted. Historical APIs, records and PDFs remain intact; no legacy financial arithmetic is reused.

## Reused safeguards and services

The new admin-only `monthly-payouts/{month}` facade reuses monthly_files, monthly_expense_persistence, the existing dynamic expense parser, Decimal calculator, source-manifest/date validator, independent truck confirmation, adjustment audit and immutable statement document services. Authentication and CORS are unchanged. GET performs read-only calculation previews for older saved drafts; uploads and explicit reviews append drafts. Automatic mechanical source checking is identified as system validation, never a human approval. Only the administrator explicitly confirms a truck.

The original XLSX bytes remain in PostgreSQL, protected by existing archive/financial permissions and immutable records. The existing replacement HTTP 409 protection is unchanged. A raw upload with existing ledger records attaches evidence only; it never replaces revenue. A corrected raw workbook whose dates, charge identities or amounts disagree with the ledger remains blocked for review. A genuinely empty month can import through the existing guarded uploader after strict preflight. Cross-request failures retain saved files, expose an error and allow retry; saving a file is not confirmation.

Net workbook replacement creates a new complete expense snapshot. Prior deductions, manual cell overrides and internal trip/manual-payslip expenses are not accumulated. Previously explicit category approvals may be reused. No-activity attestations are not carried across changed raw sources or replacement expense workbooks. Original confirmed values and PDFs remain immutable; later confirmation records a separate correction, not a payment transaction.

## Fresh verified production backup and exact inventory

Snapshot: **2026-10-30 01:29:53 +03:00**. Owner-confirmed Railway target checked privately against the prior backup target. No connection strings or credentials are recorded here.

Backup outside both repositories: `/Users/philiptheuri/Smithsons-private-backups/2026-10-30_01-29-53_+0300/smithsons-production.dump` (424,896 bytes, custom PostgreSQL format; directory 0700, files 0600). `pg_restore --list` passed; full offline PostgreSQL 16 restore passed. All **22** table counts/content hashes and schema matched the exported production snapshot. Original workbook/PDF bytes are included in these content checks. Private verification and detailed inventory are beside the backup. Earlier failed attempts are retained privately and are not the verified backup.

Inventory is a snapshot, not a determination that business data is disposable:

| Record | Exact identity | Current state | Proposed handling |
|---|---|---|---|
| Raw workbook | dhl_monthly_workbooks id **1**, month 2026-02, version **1**, `FEBRUARY 2026 TRIPS SUMMARY (1).xlsx`, 76,679 bytes | Uploaded 2026-10-29 21:08:42 UTC; no linked expense imports or frozen references at snapshot | Retain immutable original/provenance. Do not physically delete. |
| Expense import | dhl_monthly_expense_imports id **1**, month 2026-02, version **1**, `FEBRUARY NET SUMMARY 1.xlsx`, 12,235 bytes | Draft, 32 child rows; no source attestation; no archive link; no truck confirmations or statement PDFs | Candidate for logical retirement only after administrator identifies it as unwanted. Prefer reusing saved bytes and appending a corrected/validated draft. |
| New expense rows | **32**, all parent import id 1 | Unconfirmed snapshots | Retain with their parent for provenance; do not modify in place. |
| New truck confirmations / statement PDFs | **0 / 0** | None at snapshot | Recheck immediately before any approved retirement. |

These are the only saved original/draft records found. Their purpose cannot be inferred from filenames. No separately approved reset has occurred.

Protected pre-existing records: orders **1,998**; trips **1,788**; expenses **1,533**; commissions **1,529**; users **57**; vehicles **34**; DHL ledger rows **2,360**; historical manual payslips **6**, payslip expense rows **10**, stored manual PDF documents **2**. Other preserved tables: edited_reports 1; fleet_vehicle_compliance 3; fleet_driver_compliance 0; fleet_notification_history 0; fuel_expenses 0; owner_reconciliations 0; sms_logs 0. No operational table is in reset scope.

## Narrow reset recommendation — not executed

1. Keep the verified backup. Recheck target, exact IDs/hashes, descendants, confirmation/document references and counts immediately before any separately approved action.
2. Prefer **no reset**: open February and preview from the retained original workbooks. Only explicit user actions append validated drafts. All date/manifest discrepancies still block the affected truck. Do not confirm February automatically.
3. If a fresh expense workbook is desired, upload it as a new version. Retain import 1 and its 32 original rows behind Advanced Details; replacement does not accumulate deductions.
4. Raw archive deletion is deliberately prohibited by migration 005. Do not disable its triggers or clear protected evidence. To hide all originals and present an entirely empty active workspace would require a separately reviewed logical retirement/active-source design; it is not implemented in this release.
5. Do not use DELETE/TRUNCATE/reset sequences against DHL ledger, payslip, operational or immutable confirmation tables. There is no safe blanket “clear February” command. No deletion SQL is proposed.

## Schema and release plan

**No database migration is needed** for this local simplified workflow. Existing migrations 001–005 and their immutability constraints remain unchanged.

After review/approval: create isolated backend/frontend commits excluding unrelated fleet insurance/notification changes, workbooks, credentials, local fixtures, outputs and backups. Deploy backend facade first, verify admin protection/read-only saved-month endpoints, then frontend. Verify existing source downloads and historical PDF reads. Do not test production uploads or issue real statements without separate financial authorization. Keep the unused Render service untouched.

Rollback frontend to ea078326219943479aa025311ca13aa155183250; backend to da4065e21ccb6a4d0422ec9759fcbee4eed15ab5. No schema reversal or financial data deletion is needed. Append-only drafts/files created after release remain preserved. Restoring a database backup is a separate incident decision, never an automatic rollback that discards newer operational data.

## Verification

Final clean-run results are recorded below. All tests use disposable PostgreSQL and synthetic local accounts/workbooks; no production approval or statement generation is part of these tests.

## Exact implementation files for later release review

Backend (exclude existing unrelated fleet/notification edits):

- `main.py`: register the three admin-only orchestration endpoints.
- `routers/monthly_payouts.py`: read-only state, expense autosave and explicit draft synchronization; Decimal totals include revenue-only trucks.
- `services/monthly_payouts.py`: reuse saved bytes and proven calculations, optimistic source IDs, idempotence, unknown-source/expense visibility and older-duplicate conflict protection.
- `tests/test_monthly_expense_api.py`: optional JSON body support in the isolated test helper.
- `tests/test_monthly_payouts.py`: autosave, read-only old-draft preview, immutable corrections, mapping, no-activity proof, stale/duplicate conflicts, independent date gating, revenue-only and workbook-only visibility, totals and authorization.
- `docs/simple-dhl-payouts-review.md`: backup/inventory, retirement recommendation and handoff.

Frontend (sibling repository):

- `src/pages/reports/DhlReportsPage.jsx`: replace active legacy forms with the single workflow.
- `src/pages/reports/DhlMonthlyPayouts.jsx` and `DhlMonthlyPayouts.css`: simplified main page, scoped responsive styling, review confirmation and authenticated immutable downloads; detailed diagnostics/source/PDF history under Advanced Details.
- `tests/monthlyExpenses.browser.test.mjs`: replace retired multi-form UI expectations with single-page controls, validation, concurrency, explicit confirmation and narrow-screen tests.
- `tests/kavSavedPayslip.real.browser.test.mjs`: both-file autosave/reopen, exact KAV figures, independent confirmation, repeat and archive PDF hashes, corrected expenses.
- `tests/savedMonthlyFiles.real.browser.test.mjs`: saved categories and existing-ledger evidence attachment without replacement.
- `tests/truckConfirmation.real.browser.test.mjs`: pre-existing verified drafts still confirm independently through the new UI.
- `tests/legacyAuthorization.real.browser.test.mjs`: update only the retired report-page selectors; authentication/role regression checks remain.
- `tests/simplePayoutsSupport.mjs`: shared localhost-only synthetic browser helper.

Old overlapping UI assertions were replaced, rather than skipped. Existing parser/calculator, immutable PDF renderer, legacy importer, manual payslip endpoints, reconciliation page, authentication and all existing migration files are unchanged by this work.

## Final verification results

- **178 backend tests passed**, final clean disposable PostgreSQL/HTTP run, no skips (38.538 seconds). Includes 12 new orchestration tests. A repeated earlier HTTP run hit a pre-existing non-repeatable synthetic vehicle fixture; the final full run used its required fresh database and passed.
- **42 frontend tests passed, zero skipped**, including real localhost browser/API flows, isolated failure mocks and existing unit/role/reconciliation checks (51.570 seconds). Retired-interface expectations were replaced with equivalent new-workflow checks.
- **Production frontend build passed** (3.64 seconds). Existing bundle-size warning remains; no unrelated build/package changes were made.
- **KAV086M complete workflow passed** with synthetic source workbooks: DIST 294,261.41 + Offloading 7,848.00 = Gross 302,109.41; Fuel 141,386.00 + Telematics & VSS 8,758.00 + Shunting 2,390.00 = Expenses 152,534.00; Base 149,575.41; Commission 10,470.28; Net 139,105.13. Admin charge and manual NET PAID/commission reference values were not calculation inputs. Blank GPRS remained audited zero. These are fixture values, not hardcoded application values or real February approvals.
- The same PDF was downloaded byte-for-byte after reopening, after corrected expenses and from the Advanced Details archive. A synthetic +100.00 fuel correction produced new expenses 152,634.00, commission 10,463.28 and net 139,012.13 without changing the prior PDF or confirming the correction.
- Expense-first upload, approved unknown category mapping and reopening without either file were also verified. Attaching evidence to an existing ledger made no replacement call and left ledger count/gross unchanged.
- PDF text and rendered page inspected: Smithsons branding, separate Distribution/Offloading, exact original expense descriptions and matching totals; zero expense items omitted. Main-page/review screenshots inspected locally.
- Narrow manifest scan: six backend review files and nine frontend files; no credential URL/private-key/GitHub-token/API-key/JWT patterns found. At initial review no files were staged, committed, pushed or deployed; the later local-commit authorization is documented below.

Private/local evidence: `/tmp/smithsons-simple-backend-all.log`, `/tmp/smithsons-simple-frontend-all.log`, `/tmp/smithsons-simple-payouts-build.log`, `/tmp/smithsons-simple-kav-synthetic.pdf`, `/tmp/smithsons-simple-kav-synthetic.png`, `/tmp/smithsons-simple-payouts-review.png`. These generated outputs are not release files.

**Current approval boundary:** the administrator accepted retaining existing workbook/history records and authorized the two isolated local release commits. No reset or migration is planned. Push and deployment still require explicit execution approval. Production February dates/amounts/attestations remain subject to genuine source validation and explicit administrator truck confirmation.

## Approved release preparation — 2026-10-30

Scope: six backend files and nine frontend files listed above; both release branches are `main`. Existing unrelated fleet/insurance/notification work, workbooks, generated outputs, credentials and local configuration are excluded. Local commits do not deploy: neither repository has active local Git hooks. Treat a future push as potentially triggering Render automatic deployment; do not push during preparation.

Final regression is run from clean HEAD-based temporary checkouts containing only the approved manifests, with PostgreSQL 16 disposable databases and synthetic local HTTP/browser accounts. Actual local February fixtures are copied privately for reference tests only and are not release artifacts. Authentication, CORS, SMS configuration, legacy reports and financial/PDF safeguards remain covered. No live SMS is sent.

Production was not connected to or modified in this preparation phase. The prior restore-verified backup verified all 22 production tables and their historical content; this release changes no migration/model/table definition. Existing raw/expense originals, ledger, manual payslips, confirmed financial snapshots and stored PDFs are retained. This does not claim a new live record-count snapshot while other administrators may use the system.

Execution plan after separate approval:

1. Recheck both approved commit IDs, remote `main` ancestry and active Render service targets. Never force-push. Verify the private backup remains accessible. Do not change database/SMS/JWT settings or run any migrations.
2. Push only the approved backend commit to `Lipkariuki/smithsons-logistics` `main`. Treat this as deployment-triggering. Monitor **smithsons-logistics** until the exact commit is Live and health is successful; never touch **smithsons-logistics-1**. Stop on failure.
3. Read-only backend smoke checks: health; anonymous new monthly-payouts GET returns 401; non-admin returns 403; authorized admin month state/file history/source downloads return expected responses; existing orders/trips/reconciliation and historical PDF reads work. No upload, sync, confirmation, statement generation or SMS in production verification. If provider/admin access is unavailable, obtain exact Live status and read-only browser results from the administrator before continuing.
4. Only after backend checks pass, push the approved frontend commit to `Lipkariuki/smithsons-logistics-frontend` `main`. Verify Render's frontend build still uses `VITE_API_BASE_URL=https://smithsons-logistics.onrender.com` (without changing unrelated settings). Monitor the exact commit until Live; stop on failure.
5. Refresh the admin session and open existing Reports → DHL Payouts. Verify month selection, two saved workbook cards, totals, truck review/download controls and Advanced Details; confirm no active legacy manual payslip form or version selector. Reopen an existing month using GET requests only, and read an already-stored PDF where available. Check DHL Reconciliation still loads. Do not approve February or issue a real statement.
6. On failure, stop the sequence. If frontend was deployed, roll it back first to `ea078326219943479aa025311ca13aa155183250`. If required, roll backend back to `da4065e21ccb6a4d0422ec9759fcbee4eed15ab5`, then repeat read-only health/auth/report checks. No down migration or financial deletion is needed. Retain any append-only records created through authorized normal use. Do not restore a whole database backup automatically.

The commit hashes and the new clean-run results are supplied with the release handoff. Push/deployment remains gated on separate approval.

### Release-only repeat verification

The final preparation repeat passed from clean HEAD-derived source copies with only the six backend and nine frontend manifest files overlaid, excluding unrelated fleet/notification edits: **178 backend tests (41.446 seconds), 42 frontend checks with zero skipped (53.966 seconds), production build (3.64 seconds)**. Runtime source hashes match the exact staged manifests. Both indexes passed whitespace checks and a credential URL/private-key/GitHub-token/API-key/JWT pattern scan. No workbook, environment edit, generated output, backup or unrelated fleet change is staged. The unchanged frontend public API setting matches the active `smithsons-logistics.onrender.com` backend; Render's build-time setting must still be checked during approved execution.

KAV086M’s synthetic saved-workbook → automatic save → reopen → individual review/confirmation → immutable itemized PDF workflow passed again, net KES 139,105.13. Corrected expense snapshots did not change the original PDF; expense-first uploads and existing-ledger evidence attachment also passed. Main-page manual payslip controls and version selectors remain absent. Existing calculators/importer/PDF renderer/migrations are unchanged.

**GO for the prepared release, subject to execution approval and the backend-first health gate.** No production connection, migration, record change, reset, confirmation, SMS, push or deployment was performed in this preparation phase. Existing 22-table schema and historical data remain outside release modification scope. The verified backup remains accessible. Create only the two local commits; report their exact IDs separately, then stop for execution approval.
