# Saved monthly files — local implementation and release plan

Status: implemented and validated locally. Local release commits are authorized; see `saved-files-release-readiness.md` for the fresh backup, restore rehearsal and execution gates. Release bases are backend `4c6ba5f383805f77ae6331eca15716b4190bfca0` and frontend `1048c8c30b9dba2d958a562a1ef444dc60bd03eb`. No push, deployment, production migration or production financial write was performed.

Follow-up: `docs/february-evidence-verification.md` documents the explicit attach-only action, detailed ledger comparison and stricter archived-evidence revenue readiness. The implementation and migration 005 remain local; production execution requires separate approval.

## February diagnosis

Safe read-only inspection found 436 February 2026 `dhl_orders` records, with stored DIST + Offloading of KES 9,858,161.63. The saved Net Summary draft (import 1/version 1) retains its original 12,235-byte workbook. All 32 truck rows have incomplete revenue verification and NULL gross snapshots; their source snapshots already contain the 436 DHL records. The draft has no source-completeness attestation and no retained raw source/date review.

Revenue is present, but not verified for this financial report. This is not a second disconnected revenue ledger. Existing DHL reports and monthly calculations both read `dhl_orders`; the raw workbook supplies provenance, completeness and date evidence. Uploading a raw file is not itself financial approval. The implementation does not repair or confirm this draft in place.

The six historical February workbook entries at Excel rows 850–855 still need separate explicit date review. The stored gross above describes the existing ledger, not approval to include those entries in a confirmed February statement.

## Existing and added storage

| Item | Previously persisted | Change |
| --- | --- | --- |
| Parsed DHL revenue | `dhl_orders` | Reused unchanged |
| Original raw DHL file/name/upload audit | Generally discarded by legacy upload | New immutable raw archive |
| Raw review attached to a financial import | Embedded bytes only when originally supplied | Legacy evidence remains supported/downloadable; new reports reference archive ID |
| Net Summary original bytes/name/uploader/time | Existing monthly import table | Reused; no second expense-file table |
| Financial report versions and decisions | Existing imports/rows | Reused; source archive reference added to decisions |
| Confirmed truck snapshots and PDFs | Existing immutable statements | Reused without changing financial formulas or PDF layout |

Unknown legacy raw filenames/upload times cannot be recovered from parsed revenue. The UI explicitly discloses missing metadata rather than inventing it. Where original raw bytes were lost, one attachment of the actual workbook is necessary. Saved Net workbooks need not be selected again.

## Storage choice and migration 005

The actual February originals are 79,914 bytes raw and 12,235 bytes Net: approximately 92 KB per pair, or 1.1 MB for twelve comparable months before revisions. Render local filesystem storage would be ephemeral. No private object-store infrastructure is configured in these repositories; adding it would require credentials, access controls and backup/lifecycle operations.

The smallest current solution is one PostgreSQL table, `dhl_monthly_workbooks`, storing bounded raw XLSX bytes with immutable metadata. The existing Net byte storage remains in place. Raw uploads are capped at 20,000,000 bytes. Identical content within a month is deduplicated by SHA-256; new financial versions reference the same archive instead of repeating base64 source bytes. Monitor database/backup growth and reconsider private object storage if actual files or replacement frequency grow substantially. Provider storage capacity has not been asserted or changed.

`migrations/005_saved_dhl_workbooks.sql` adds only the archive table, index, function and triggers. Fields include reporting month, source version, original filename, SHA-256, bytes, uploader/time, previous version, correction reason and date-review metadata. Database checks validate size/hash/month/version; unique month/version and month/hash constraints prevent duplicates. A month-scoped transaction advisory lock and predecessor checks prevent conflicting successor versions. Triggers reject UPDATE, DELETE and TRUNCATE. Existing tables are not altered or backfilled.

005 is an explicit one-shot migration, not a startup migration. Repeating it fails and rolls back; it does not silently alter an already existing table. Its runner executes the SQL in one transaction with bounded lock/statement timeouts. Tests cover rollback, repeat rejection and concurrent upload deduplication.

## Application behavior

All new routes require the existing administrator authorization. Original downloads use authenticated requests, attachment filenames and `Cache-Control: no-store`; there are no public storage URLs. File metadata responses exclude workbook bytes.

- GET `/dhl-reports/monthly-files?month=YYYY-MM-01`: file/status/history and informational parsed revenue.
- POST `/dhl-reports/monthly-files/dhl`: retain missing or corrected raw evidence without altering parsed revenue or approving a source.
- GET `/dhl-reports/monthly-files/raw/{id}`: original archived raw workbook.
- GET `/dhl-reports/monthly-files/report/{id}/expenses`: original Net workbook.
- GET `/dhl-reports/monthly-files/report/{id}/raw`: retained legacy source evidence, when available.

The existing raw upload endpoint archives valid XLSX bytes in the same transaction as the existing importer. Its manual-payslip conflict guard still rejects replacement with HTTP 409 before changes. The importer itself is unchanged. Existing deployments without 005 retain their prior upload behavior and explicitly report that original-file retention is unavailable. Direct standalone importer calls are not a new archival interface.

New financial drafts resolve saved source references to the exact immutable bytes and rerun existing date/source checks. A new raw source cannot inherit historical date dispositions from a different source. A report displays the precise raw filename and source version it uses, distinct from the latest archive entry. Uploading a corrected raw file does not recalculate an older financial report.

## Administrator workflow

1. Select the reporting month in the existing DHL Payouts → Monthly Expense Reports section. Saved metadata and the latest report load automatically.
2. Review Saved Monthly Files: Uploaded, Missing or Needs Review, filenames, upload time, administrator, originals and version history.
3. If revenue is absent, the raw upload imports through the existing guarded importer and saves the original. If parsed revenue already exists, attach the missing raw evidence without replacing that revenue. For February this is the appropriate first step.
4. Reopen the saved Net report without selecting its workbook again. Upload a new Net workbook only to replace it. Choose the appropriate retained raw source when preparing a new financial version.
5. Explicitly review completeness, source dates, unknown expense categories and reconciliation warnings. Saving files is not confirmation. Where raw evidence and ledger differ, a separate explicit replacement action uses the existing manual-payslip guard.
6. Save a new draft/version; eligible trucks can be confirmed independently through the existing controls. Historical rows and other unresolved approvals remain unresolved until reviewed.
7. Download statements from stored immutable confirmations. Returning after logout needs no local spreadsheet files. Expense corrections create new financial versions and preserve earlier statements and adjustment history.

Gross remains DIST + Offloading. Admin entries remain audit-only. Expenses come only from the selected Net workbook, with existing blank-to-zero audit behavior and approved dynamic categories. No old manual deductions are mixed in. No automatic confirmations, fabricated zero-revenue verification or SMS were added.

## Files in this change

Backend: `main.py`, `routers/dhl_reports.py`, `routers/monthly_expense_reports.py`, `routers/monthly_files.py`, `services/monthly_files.py`, `services/monthly_expense_persistence.py`, `services/monthly_expense_reports.py`, `services/truck_confirmations.py`, migration 005, `scripts/migrate_saved_monthly_files.py`, `tests/test_saved_monthly_files.py`, this document.

Frontend: `src/pages/reports/SavedMonthlyFiles.jsx`, `MonthlyExpenseReports.jsx`, `DhlReportsPage.jsx`, `monthlyExpenseUi.js`, `tests/monthlyExpenses.browser.test.mjs`, `tests/savedMonthlyFiles.real.browser.test.mjs`.

Unrelated existing insurance/SMS edits, financial workbooks, local configuration, generated outputs and other untracked audit artifacts are excluded. No changes to financial calculator policy, legacy importer, immutable PDF renderer, migrations 001–004, authentication, CORS or SMS behavior.

## Verification

Final backend suite: 154 tests passed against disposable PostgreSQL and synthetic local HTTP data. Includes ten new archive, migration, authorization, source-validation and versioning tests.

The real-browser scenario uploads raw and Net workbooks once, reviews a dynamic Tyres category and blank-to-zero interpretation, saves, logs out/in, reopens without files, confirms eligible TEST100A while another truck remains unresolved, downloads originals byte-for-byte and its PDF, replaces the expense workbook, creates a correction and verifies the original PDF remains byte-identical. Synthetic figures: expenses 145.00 → 245.00; net 795.15 → 702.15; adjustment −93.00. No real February approvals are simulated as business approvals.

Final frontend suite: all 42 tests passed, with no skipped tests, including mocked regression coverage and real browser/API/PostgreSQL workflows. The production frontend build passed. Existing Vite chunk-size and PDF SVG-gradient warnings do not fail the checks. Both repositories pass `git diff --check`.

## Proposed production sequence — separate approval required

1. Review this scoped diff and migration 005. Verify the exact active Railway target and current migration state; take a fresh private backup and restore-test it. Do not touch the unused Render service.
2. Set `SAVED_MONTHLY_FILES_MIGRATION_URL` privately to the approved target. Review-only command opens no connection:
   `venv/bin/python scripts/migrate_saved_monthly_files.py --allow-nonlocal`
3. Only after explicit migration approval, run:
   `venv/bin/python scripts/migrate_saved_monthly_files.py --allow-nonlocal --apply`
4. Verify archive constraints/triggers/indexes, all existing tables/counts and unchanged financial records. No February backfill or approval is part of this migration.
5. After explicit release approval, prepare isolated commits; deploy backend first, then frontend. Preserve database/SMS/JWT configuration.
6. Read-only smoke: login, select saved month, view statuses, report/source version and download retained originals/existing statements. Test write flows only locally unless separately authorized for actual business use.

Rollback: revert the frontend to `1048c8c30b9dba2d958a562a1ef444dc60bd03eb` and backend to `4c6ba5f383805f77ae6331eca15716b4190bfca0` if required. Leave the additive archive/history intact; do not drop financial data. Pause confirmation/editing of new drafts containing archive references while older code is running, because it does not resolve those references. Prefer a forward correction; never rewrite frozen statements to make a rollback work.
