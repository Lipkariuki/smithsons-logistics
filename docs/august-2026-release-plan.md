# Controlled August DHL release

Approved application scope: surcharge-inclusive gross; 5% administration fee on each DIST row including surcharge only (ROUND_HALF_UP per row); workbook-only operating expenses; 7% Smithsons commission on the positive remaining balance; existing independent truck confirmation and immutable itemized PDFs. Legacy-format calculations and historical documents remain unchanged.

## Local verification

- Backend: 207 tests discovered, 194 passed, 13 optional real-HTTP tests skipped because their separate synthetic HTTP fixtures were not started; zero failures.
- Frontend: 33 focused unit/browser tests passed; production build passed. Existing bundle-size and Browserslist warnings remain.
- Actual August tests cover saved originals/reopening, eligible independent confirmation, itemized PDF arithmetic, immutable history, successor versions and rejected source/fee tampering. Actual February regression remains unchanged.
- Migration 006 was tested transactionally and twice for idempotency only in disposable local schemas. Existing legacy data and stored PDF bytes were preserved.
- No production financial records, credentials, workbooks or approvals have been changed. No SMS was sent.

## Outstanding production gates

At preparation time there is no locally available production connection or authenticated Railway/Render management integration. The owner must privately supply the current Railway public connection URL and confirm it matches DATABASE_URL on active Render backend smithsons-logistics. A browser inspection attempt could not navigate successfully; no configuration is assumed verified.

Fresh production backup, restore verification, exact current target and current migration-006 state remain REQUIRED before any production migration or push. Previous October backups are retained but are not a fresh release backup. The private backup result belongs outside Git and must not contain a connection URL or password in a public report.

Unresolved business records remain blocked: four inclusive-amount cent mismatches; KDA267N's error-marked pair; eleven trucks lacking verified DHL activity. They do not block an eligible truck. Do not confirm the whole month or use deployment smoke tests to approve payouts.

## Production execution order — conditional authorization only

1. Confirm active architecture: Render smithsons-logistics backend and smithsons-logistics-frontend; Railway PostgreSQL only. Do not touch unused smithsons-logistics-1 or pending Railway configuration changes. Never redeploy/restart/reset the production PostgreSQL service.
2. Verify the private connection targets the previously owner-confirmed Railway database and matches active Render DATABASE_URL. Inspect existing schema and all migration-006 function definitions read-only. Stop on target uncertainty or partial/unexpected migration state.
3. Create a fresh custom-format PostgreSQL backup in a private directory outside Git (directory 0700, archive 0600), using read-only production access. Verify pg_restore listing and full offline restore. Compare all existing table contents/counts/schema, including original workbook and PDF bytes, against the same source snapshot.
4. Rehearse the exact 006 on the offline restore; verify unchanged records/columns and expected function changes. If production 006 is already present, compare exact definitions and do not blindly apply it again.
5. Only after the fresh backup and target checks pass, apply pending 006 with the explicit runner `scripts/migrate_dist_admin_policy.py --allow-nonlocal --apply`. Supply DHL_DIST_ADMIN_MIGRATION_URL privately in the process environment, never command arguments or logs. The runner uses a single transaction, migration advisory lock and bounded lock/statement timeouts. Recheck original table hashes/counts and the three function definitions after execution. No 001–005 replay, startup migration or data rewrite.
6. Push only the reviewed backend release commit to origin main. Treat the push as a Render auto-deployment trigger. Wait for that exact commit to be Live on smithsons-logistics before proceeding.
7. Check public OpenAPI and unauthenticated rejection, then authorized read-only existing reporting/history/downloads if an admin session is available. Do not generate production PDFs, replace workbooks, approve trucks or send SMS. Stop on failure.
8. Push only the reviewed frontend release commit to origin main after backend verification passes. Wait for its exact commit to be Live on smithsons-logistics-frontend. Verify the existing monthly page, saved-file statuses, surcharge/admin review lines, blocked rows, reconciliation and historical downloads read-only. No UI redesign is included.
9. Report exact live commits, migration verification, backup path and remaining business decisions. Provider deployment statuses must be verified through authenticated access or explicitly confirmed by the owner; code pushes alone do not prove Live status.

## Migration characteristics

006 creates/replaces one new helper and two existing confirmation guard definitions. It is not purely append-only DDL: those two guard functions deliberately change. There is no table/column creation/rename/drop, data backfill or historical row rewrite. Existing hash, immutable-history, supersession, category, source and lock protections remain. The legacy formula uses zero administration fee; only the explicit new source policy subtracts the separately frozen fee.

## Rollback

- Any migration error before commit rolls back the whole transaction. Stop and leave the old applications in place.
- Prior application baselines: backend c0f383d9539c99b4b3db2e41cc5d8661d71b4f13; frontend 2dd74ac850a9ff4ed882d1ccf34a4e2625e1b02b.
- If the backend deployment fails, do not push the frontend. Roll Render back to the reviewed backend baseline if needed and pause new-format confirmations. Do not reset GitHub history, credentials or the database without a separate recovery decision.
- If the frontend fails, roll it back to its baseline; keep the verified compatible backend and 006 while investigating.
- Retain migration 006 and all new-policy snapshots/PDFs after any new-policy statement exists; prefer a compatible forward fix. Never replay complete old migrations or force old calculation rules over new statements. If a function rollback is necessary before any new-policy records are confirmed, restore only the reviewed previous function definitions transactionally, with separate approval.
- Never restore an old backup over new production activity as an automatic rollback. Preserve all original financial history and backups.

## Release manifest

The companion JSON manifest lists the exact application/test/runner/release-document files. Workbooks, financial audit output, backups, private configuration and unrelated changes are excluded. Local commits do not deploy; no active Git commit hooks were found. No push is permitted before the production gates above succeed.
