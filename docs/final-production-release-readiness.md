# Final production release readiness — 29 October 2026

Decision: GO for reviewed local release artifacts; production migration, push and
Render deployment remain gated by explicit final approval. No production schema,
financial rows, February confirmations, environment settings or SMS were changed.

## Fresh backup and exact target

Read-only connection matched the owner-confirmed public Railway endpoint and the
previously migrated original Smithsons target. PostgreSQL 16 and the expected
Smithsons schema were verified. Both monthly tables from 001 exist and are empty;
002/004 tables are absent. The active backend remains Render smithsons-logistics;
frontend is smithsons-logistics-frontend. Never touch smithsons-logistics-1.

Backup started **2026-10-29 15:34:27 EAT**:

`/Users/philiptheuri/Smithsons-private-backups/2026-10-29_15-34-27_+0300/smithsons-production.dump`

- 279,594 bytes, custom PostgreSQL archive, directory 0700 and file 0600.
- pg_restore --list passed; full restore passed into an offline PostgreSQL 16
  container with no exposed ports and no application or delivery scheduler.
- All 19 tables matched canonical row counts/content hashes and column definitions.
  Includes 1,997 orders, 1,787 trips, 57 users, 34 vehicles, 1,533 expenses,
  1,529 commissions, 2,336 DHL rows, 5 legacy payslips, 10 payslip expenses and
  the existing stored PDF document. Zero unvalidated restored constraints.
- Live activity explains count differences from the earlier morning backup; no
  previous counts were used as an assumption. One exported repeatable-read
  snapshot was shared by the new dump and integrity checks.
- Private verification.json and final-migration-rehearsal.json sit beside the dump.
  No backup or private configuration is part of Git release artifacts.

No authenticated Render management integration is available to independently
re-read its environment. The direct Railway target matches the owner's saved
Render public-URL confirmation. Recheck that saved target before execution if any
configuration has changed; never paste credentials. Existing Render signing/SMS
settings stay unchanged. This feature requires no new environment variables.

## Migration review and actual restore rehearsal

001 is already applied; do not rerun it. Pending order is **002 -> 003 -> 004**:

| File | Change | Existing data |
| --- | --- | --- |
| 002_monthly_statement_documents.sql | New append-only stored PDFs, hashes, predecessor links and guards | Legacy PDFs/payslips untouched |
| 003_expense_zero_policy.sql | Replace monthly confirmation guard to permit workbook-authoritative zero expense cases | No UPDATE or backfill |
| 004_monthly_truck_confirmations.sql | New approval registry, immutability/current-version guards, scoped PDF compatibility | Registers current confirmed monthly rows only; no financial changes |

The exact final SQL was applied together in one transaction to a fresh offline
restore of this backup. All 19 original table contents, including document bytes,
remained identical; resulting schema has 21 tables. Expected guards/indexes and
concurrency/rollback behavior also pass isolated PostgreSQL regression tests.

These files are **one-shot, not rerunnable idempotent scripts**. Replaying the
batch was tested: it fails at the existing object and rolls back without partial
changes. Do not add IF NOT EXISTS to hide schema drift. Check table/function/trigger
state first; unexpected partial or already-applied schema means STOP and inspect.
003 is only safely repeatable in its intended order; do not replay it after 004 as
an isolated workaround. Record hashes from the final manifest/rehearsal report.

The runner uses one psycopg transaction, a migration advisory lock, 5-second lock
and 120-second statement timeouts. 004 briefly takes ACCESS EXCLUSIVE locks on the
monthly tables. Failed statements roll back the entire batch, including replaced
functions. Pause financial writes/confirmations during execution. No DROP, TRUNCATE,
legacy table rename, legacy financial UPDATE or production startup auto-migration
is part of the batch. Guard functions reject forbidden operations at runtime.

## Approved correction policy

Original statements, PDFs and payment history remain unchanged. A successor truck
confirmation stores a **separate immutable financial_adjustment audit object** in
its validation JSONB: predecessor, prior/revised net and Decimal-string differences
for gross, operating expenses, commission and net. The database derives these
values from frozen rows, not client input. The corrected PDF shows the separate
net adjustment as well as the full revised snapshot. No extra payment table,
settlement module, payment instruction or inference that a statement was paid is
introduced. Existing payment fields and legacy generation APIs are untouched.

## Verification and exact release artifacts

- 139 backend tests passed, no skips, with disposable PostgreSQL and real synthetic
  local HTTP accounts. An initial run lacked its required October saved-draft
  fixture; after seeding only that disposable fixture, the full rerun passed.
- 41 frontend tests passed, no skips, including actual browser/backend/database
  confirmation, stored-PDF downloads and existing reporting/role regressions.
- Production frontend build passed; existing large-bundle/stale-Browserslist
  warnings remain. No unrelated dependency upgrades.
- Correction tests verify a separate -93.00 net adjustment for a +100.00 expense
  correction, original PDF retention and unchanged historical figures.
- Release delta: 34 backend files and 8 frontend files. Explicit manifests
  contain only financial reporting, expense source
  policy, scoped source/date safeguards, reconciliation, immutable itemized
  statements, confirmation UI, related tests/fonts and current release docs.
- Exclude fleet_schemas.py, routers/fleet.py and services/fleet_notifications.py
  unrelated insurance/SMS edits; preserve their existing HEAD versions.
- Exclude .env/local configuration, all workbooks, backup archives, generated
  outputs, exploratory scripts and build directories. Never git add -A.
- Local commits may be prepared; no push is authorized. Pushing main may trigger
  Render automatically. No provider auto-deploy setting was changed or assumed.

## Exact gated deployment sequence

1. Review final manifests, staged secret scan, local commit hashes and this plan.
   Obtain explicit approval for production migration and backend/frontend pushes.
2. Verify the saved DATABASE_URL on active Render smithsons-logistics still maps
   to the same backed-up Railway target. Recheck schema and backup readability;
   pause financial edits and take another backup if meaningful new writes occurred.
3. Privately supply libpq URL as TRUCK_CONFIRMATION_MIGRATION_URL (never in command
   arguments/history). Review-only runner opens no database connection:

       venv/bin/python scripts/migrate_truck_confirmations.py --allow-nonlocal --include-prerequisites

   After the separate explicit migration approval, execute:

       venv/bin/python scripts/migrate_truck_confirmations.py --allow-nonlocal --include-prerequisites --apply

4. Verify both new tables, indexes, triggers/functions and unchanged original
   row counts/hashes against a same-window snapshot. Do not approve February.
5. Push the reviewed backend commit to GitHub main only after push/deployment
   approval. Monitor Render smithsons-logistics for that exact commit and health.
   Keep DATABASE_URL, JWT_SECRET_KEY, APP_ENV and SMS configuration unchanged.
6. Verify read-only login/report/history/legacy PDF requests. Then push approved
   frontend to main and monitor smithsons-logistics-frontend. Verify its API base
   remains https://smithsons-logistics.onrender.com. No live SMS/write smoke tests.
7. Check per-truck status/history/reconciliation/PDF controls read-only. Financial
   approvals occur later through genuine administrator review, never smoke tests.

## Rollback

- Before migration COMMIT: any SQL error rolls back the whole batch; stop release.
- After migration: retain additive tables/history/adjustments and stored PDFs.
  Roll back frontend first to adbd135143653ab23cc68ae50632bd368abd96a5 if needed,
  then backend to the secure currently live 6f05d75213b9430addac7ddedfa2ec1df8b778cc.
  Keep the present JWT/environment/auth safeguards. Pause financial confirmations
  if old code cannot service newer drafts; restore compatible code/fix forward.
- Do not DROP new history, reactivate superseded approvals, rewrite financial rows
  or restore an old database over new transactions. Database recovery requires a
  separate reviewed incident plan and restore to a new isolated target first.
