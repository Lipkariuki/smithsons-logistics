# Saved Monthly Files release readiness — 29 October 2026

GO for local release artifacts. Production migration 005, pushes and deployments require separate explicit execution approval. No February reports or statements were approved, no SMS was sent, and no production data/schema/configuration was modified.

## Fresh backup and restore rehearsal

The direct Railway PostgreSQL 16 connection matched the same owner-confirmed public endpoint, port and database used for the previous verified backups and production migrations. Expected Smithsons schema and workbook vehicle overlap were checked read-only. Migrations 001–004 are present; 005 is absent. Render management access is unavailable: this does not independently re-read Render's DATABASE_URL. Its last owner-confirmed target remains the release configuration; recheck privately before execution if it has changed.

Backup snapshot: **2026-10-29 23:33:50 EAT**.

`/Users/philiptheuri/Smithsons-private-backups/2026-10-29_23-33-50_+0300/smithsons-production.dump`

- Custom-format PostgreSQL archive, **334,748 bytes**, directory 0700, dump 0600; outside both repositories.
- pg_restore listing and full restore passed into an offline PostgreSQL 16 container with no exposed ports, application or delivery processes.
- Source checks and pg_dump shared one exported repeatable-read, read-only snapshot. All **21 existing tables** matched canonical content hashes/counts and column definitions after restore.
- Includes 1,998 orders; 1,788 trips; 57 users; 34 vehicles; 1,533 expenses; 1,529 commissions; 2,360 DHL records; 6 historical manual payslips; 10 payslip expenses; 2 historical stored PDF documents; 1 monthly import and its 32 expense rows. Current truck confirmations and new monthly statement documents are both empty; synthetic regression tests cover their populated immutable behavior.
- The exact migration 005 was applied transactionally **only to the offline restore**. All 21 existing table contents, including workbook/PDF bytes and financial snapshots, remained identical. The new archive table is empty; expected columns, checks, unique keys, predecessor FK and immutability triggers were verified. Zero unvalidated restored constraints.
- Private `verification.json`, archive listing and snapshot-integrity hashes remain beside the backup, never in Git.

Migration SHA-256:
`e0f4e4f2fd20294d9e8180f9a3c5d4485ea5d563c310c2736dc2ece2d9617348`

005 creates only `dhl_monthly_workbooks`, its index, guard function and triggers. It does not alter existing tables or backfill/confirm any record. It is one-shot; replay fails transactionally rather than hiding schema drift. A failed migration rolls back all new objects. The explicit runner uses one transaction, an advisory lock, 5-second lock timeout and 120-second statement timeout. No startup migration is introduced.

## Storage and financial safeguards

Raw XLSX originals are retained persistently in PostgreSQL BYTEA, capped at 20 MB, hashed and deduplicated per month, with immutable version/provenance history. Private object storage was considered; see `saved-monthly-files.md` for the size/infrastructure tradeoff. This feature requires no new application environment variables or storage credentials. Existing Net Summary byte storage is reused.

File metadata, originals and verification endpoints require the existing admin dependency; anonymous/owner/driver responses are 401/403. Downloads are authenticated attachments with no-store/nosniff headers, not public links.

Evidence attachment never invokes the importer or deletes/replaces DHL records. Historical manual payslips remain unchanged. The existing replacement HTTP 409 guard remains, including atomic rejection/no partial writes. Date, reference, normalized plate, DIST, Offloading and source-total checks are rerun server-side. Equal gross alone is insufficient. Archived evidence failing a truck's validation cannot mark that truck's revenue verified, even with a textual attestation; unrelated truck issues preserve independent confirmation. Historical date decisions remain explicit and source-version-bound.

The local February original's 436 in-period groups total KES 9,858,161.63, but its six historical entries remain unresolved. No claim is made that an unprovided corrected file has passed. Attaching an original saves evidence, not financial approval. An administrator must explicitly review the source and save a new financial version using the already-retained Net workbook. Confirmed reports, truck statements, corrections and immutable PDFs retain their existing safeguards and formulas.

## Final checks

- **159 backend tests passed**, no skips, against disposable PostgreSQL and real synthetic localhost APIs.
- **43 frontend tests passed**, no skips, including real browser/API/PostgreSQL upload, attach-only, logout/reopen, original-file download, saved Net reuse, independent confirmation, replacement version and unchanged PDF scenarios.
- Production frontend build and both repositories' whitespace checks passed.
- Existing bundle-size/Browserslist and PDF SVG-gradient warnings remain non-failing. No unrelated dependency upgrades.
- Scoped release paths are listed in `saved-files-release-manifest.json`. Exclude unrelated `fleet_schemas.py`, `routers/fleet.py`, `services/fleet_notifications.py`, all workbooks/backups, generated output, local config and exploratory scripts. No broad git-add operation.
- Local commits alone do not push or deploy; no non-sample Git hooks or configured hooksPath were found. Treat subsequent pushes to main as potentially triggering Render automatic deployment. No provider auto-deploy setting is assumed or changed.

## Execution sequence — separate approval required

1. Review the two local commit hashes and manifests. Reconfirm the active Render `smithsons-logistics` DATABASE_URL privately against this Railway target; leave `smithsons-logistics-1` untouched. Verify backup accessibility, current schema and 005 absence. Pause financial writes; refresh the backup if meaningful new activity occurred.
2. Supply `SAVED_MONTHLY_FILES_MIGRATION_URL` privately (libpq PostgreSQL URL, never command-line credentials). Review-only command opens no connection:

   `venv/bin/python scripts/migrate_saved_monthly_files.py --allow-nonlocal`

3. Only after production migration execution approval:

   `venv/bin/python scripts/migrate_saved_monthly_files.py --allow-nonlocal --apply`

4. Verify new table/constraints/index/triggers and all pre-existing counts/content hashes against a consistent pre-migration snapshot. Stop on unexpected schema or data changes; never rerun 001–004.
5. After push/deployment approval, push only the reviewed backend commit to GitHub main. Monitor active Render backend for that exact commit. Check health, auth protection and read-only existing reporting/history/downloads.
6. If backend checks pass, push only the reviewed frontend commit to main. Monitor Render `smithsons-logistics-frontend`; retain its existing backend API target. Refresh and view Saved Monthly Files, report history, evidence controls and existing statement downloads read-only.
7. February evidence attachment/draft preparation and genuine financial confirmations require separately authorized business actions. They are not deployment smoke tests. Never use protected replacement as a workaround for February verification.

## Rollback

Before migration commit, any SQL error rolls back the transaction. Afterward, retain the additive archive and its history. Roll frontend back to `1048c8c30b9dba2d958a562a1ef444dc60bd03eb`, then backend to `4c6ba5f383805f77ae6331eca15716b4190bfca0` if necessary. Pause edits/confirmations of archive-reference drafts because older code cannot resolve those references; prefer a forward correction. Do not drop archive/history, mutate frozen statements, or restore an old database over new production transactions. Keep JWT/database/SMS configuration unchanged.
