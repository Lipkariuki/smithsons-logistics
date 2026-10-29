# Smithsons final release handoff — 29 October 2026

**Local release verification passed. Production execution remains a separate approval.** The controlled JWT transition and user re-login are approved; no real key was generated/configured in this task. No production variables/data/migrations, commits, pushes, deployments or live SMS were performed.

Targets are only Render backend **smithsons-logistics**, Render frontend **smithsons-logistics-frontend**, and the existing Railway PostgreSQL service. **Do not open, rename, configure, deploy or otherwise change smithsons-logistics-1.** No Railway application deployment is required.

## Changes completed now

- All `/expenses/` and `/commissions/` operations require the existing admin dependency. Their frontend callers are administrative; owner/driver dashboards already use scoped endpoints. Anonymous callers receive 401; owner/driver callers receive 403.
- `POST /driver/expenses/` delegates to the existing slashless handler, so both URL variants require the driver role and a trip assigned to that driver. Existing missing/unassigned-trip validation returns 400, without writing a row.
- Corrected both driver submissions' database write mapping: only `trip_id`, `amount` and `description` are passed to Expense. The request's optional `order_number` is not an Expense model column and previously could cause a 500. No financial arithmetic changed.
- Expanded real HTTP tests for administrative expense/commission operations, unauthorized operations and both driver submission variants. The startup smoke script now accepts a test port to allow independent disposable databases.
- Existing environment-only JWT/database configuration, login/password handling, CORS, financial rules, manual payslip behavior and previously completed frontend guards were preserved.

Files changed in this task: `routers/expenses.py`, `routers/commissions.py`, `routers/driver_expense.py`, `routers/driver_trips.py`, `tests/test_legacy_authorization_http.py`, `scripts/smoke_production_safety.py`, this document and `output/final-release-preparation/`. No frontend source changes were necessary in this task. Earlier local release changes remain uncommitted in both repositories; review the combined release diff deliberately.

## Verification results

| Check | Result |
| --- | --- |
| All backend regressions, including PostgreSQL and real HTTP | **93 passed** |
| Frontend unit / mocked browser / real-backend browser | **20 / 9 / 8 passed — 37 total** |
| Final frontend production build | **Passed** |
| Exact declared Render Gunicorn command with real main.app startup | **Passed** |
| Synthetic monthly preview, stored revision, date blocking, confirm/history, XLSX/PDF exports | **Passed** |
| Existing manual payslip calculation | **Passed — synthetic net 730.00 unchanged** |
| Synthetic monthly positive/negative-balance workflow | **Passed — total net 624.25** |
| SMS configuration, request contract and secret-log regression tests | **Passed; provider mocked, no live sends** |
| Backend compilation and whitespace checks | **Passed** |

Tests used fresh disposable local PostgreSQL databases, synthetic admin/two owners/two drivers and actual frontend/backend requests. The exact-startup process used the real settings/database modules, disabled the notification scheduler and blocked nonlocal sockets. No real February workbook decision was approved. Existing warnings about SVG gradients, stale Browserslist data and frontend bundle size do not fail these checks. Runtime proof is in `output/final-release-preparation/startup-and-workflow.json`; test summary is alongside it.

## Unresolved vehicle permission decision

`POST /vehicles/` and `PUT /vehicles/{vehicle_id}` retain the existing authenticated fleet-manager phone restriction. `/fleet` writes already require admin. Replacing the legacy phone rule with all-admin access would broaden permissions; adding admin on top could revoke an intentional fleet-manager exception. Neither change is inferred here. Decide whether to retain this exception, require admin plus the existing restriction, or use the existing admin-only fleet policy. This portion is stopped and unchanged pending that decision. Current registered fleet workflows and their rules are preserved.

## JWT generation and Render variables — instructions only

The updated backend already requires `JWT_SECRET_KEY` and rejects the known hardcoded fallback. Existing `SECRET_KEY` is not used as an alias. Accounts, password hashes and database roles are not regenerated. Changing the effective signing key invalidates previous tokens; users must log in again. Normal HS256 signing and the existing 30-minute token lifetime remain unchanged.

During the separately authorized release, on a trusted Mac, this command generates 48 cryptographically random bytes as a URL-safe key and copies it directly to the clipboard without terminal output or a key-containing shell command:

```sh
venv/bin/python -c 'import secrets, subprocess; subprocess.run(["pbcopy"], input=secrets.token_urlsafe(48).encode(), check=True)'
```

Do not run it now as part of this preparation. During release, store the generated value privately in the approved password manager and paste it into **smithsons-logistics → Environment → JWT_SECRET_KEY**. Never paste it into chat, source, `.env.example`, build commands or frontend variables. Once stored/configured, clear the clipboard:

```sh
pbcopy < /dev/null
```

Choose **Save only**, not either deploy option, while staging settings. Render states that Save only defers applying variables until the next deployment: [Render environment-variable documentation](https://render.com/docs/configure-environment-variables). This allows key activation to coincide with the reviewed backend release. Do not click Restart or trigger an old build accidentally during preparation.

| Service / variable | Release action |
| --- | --- |
| Backend `JWT_SECRET_KEY` | Add the newly approved private key; never restore the fallback or blindly copy `SECRET_KEY`. |
| Backend `APP_ENV` | Add/verify `production`. Render host detection already prevents development `.env` loading, but explicit mode is recommended. |
| Backend `DATABASE_URL` | Verify it targets the same existing Railway database as the previously embedded connection. Use the approved public Railway connection reachable from Render; preserve credentials and TLS/query options. Do not switch/provision databases. |
| Backend `AFRICASTALKING_USERNAME`, `AFRICASTALKING_API_KEY` | Preserve and privately verify the approved working account/key. The old embedded key could differ from the environment; presence alone does not establish compatibility. |
| Backend `AFRICASTALKING_SENDER_ID` | Optional: verify the authorized existing sender. Omission retains the existing Smithsons default. |
| Backend `PORT` | Render-provided; do not hardcode a replacement port. |
| Backend `CORS_ORIGINS`, `CORS_ORIGIN_REGEX` | Optional overrides: retain actual frontend/custom-domain access; no wildcard workaround. Existing defaults and live Render preflights were previously verified. |
| Backend `FLEET_SCHEDULER_ENABLED` and notification settings | Review existing intended behavior. Local/staging tests use false; do not inadvertently enable/disable production delivery or invoke notification-test endpoints. |
| Backend `SECRET_KEY` | No JWT role in updated code. It may remain untouched during this release; no alias or unrelated removal is needed. |
| Frontend `VITE_API_BASE_URL` | Verify `https://smithsons-logistics.onrender.com/`. The public frontend bundles and local configuration already target this exact backend. No signing/provider/database secrets belong in VITE variables. |

Only `JWT_SECRET_KEY` is newly mandatory given the existing four backend variables. The existing SMS variables are required when SMS is requested, not for import. Bootstrap-password variables are not required for normal deployment; do not run `create_users.py`.

Backend build: `pip install -r requirements.txt`.

Backend start command:

```sh
gunicorn main:app -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT
```

Gunicorn is explicitly declared. Verify the Render Python runtime is compatible (Gunicorn requires Python 3.10+; local verification used 3.13). Configure the existing service directly: the repository blueprint's historical service name differs, so do not create/rename services by casually applying that blueprint.

## Backup and migration — do not run against production until approved

1. Privately identify the exact Railway service/database. Before any release, verify its service identity against the old working connection and proposed environment URL. Record only match/mismatch and masked identifiers in release notes.
2. Take a fresh Railway backup using the provider's supported backup facilities and retain it. Also make a full logical backup with a compatible PostgreSQL client and verify a restore into a separate isolated database. Protect backups: they contain users/password hashes, financial records, retained workbooks and PDFs. Preserve any separately stored uploads/PDFs too. [Railway backup/restore guide](https://docs.railway.com/guides/postgres-backups-restores), [PostgreSQL pg_dump reference](https://www.postgresql.org/docs/current/app-pgdump.html).
3. For credential-free shell commands, configure private libpq service/password files outside Git (`chmod 600`) with names `smithsons-production` and `smithsons-restore-check`. The latter MUST identify a disposable empty restore target, never production. Service settings must preserve the approved public target and TLS settings; do not print their contents.

Example logical backup and archive checks, only during the approved release:

```sh
umask 077
mkdir -p "$HOME/Smithsons-private-backups/2026-10-29"
PGSERVICE=smithsons-production pg_dump --format=custom --file="$HOME/Smithsons-private-backups/2026-10-29/before-release.dump"
pg_restore --list "$HOME/Smithsons-private-backups/2026-10-29/before-release.dump" > /dev/null
shasum -a 256 "$HOME/Smithsons-private-backups/2026-10-29/before-release.dump" > "$HOME/Smithsons-private-backups/2026-10-29/before-release.dump.sha256"
pg_restore --exit-on-error --no-owner --no-acl --dbname='service=smithsons-restore-check' "$HOME/Smithsons-private-backups/2026-10-29/before-release.dump"
```

Verify restored account/vehicle/financial row counts and retained document bytes privately. Record only verification outcomes. A dump listing is not a successful restore drill. Do not start an application or delivery scheduler against the restored production data.

4. Read-only check whether monthly tables exist:

```sh
PGSERVICE=smithsons-production psql -X -v ON_ERROR_STOP=1 -c "SELECT to_regclass('public.dhl_monthly_expense_imports'), to_regclass('public.dhl_monthly_expense_rows');"
```

Apply only if both are absent and target/migration approval is explicit. If either exists, inspect the installed schema/guards and stop rather than rerun blindly. The migration is intentionally not rerunnable.

5. Supply the approved public database URL privately using a hidden zsh prompt, not a pasted secret-containing command. Use a libpq `postgresql://` URL, not the SQLAlchemy `postgresql+psycopg://` spelling:

```sh
read -r -s 'MONTHLY_EXPENSE_MIGRATION_URL?Approved public PostgreSQL URL: '
printf '\n'
export MONTHLY_EXPENSE_MIGRATION_URL
venv/bin/python scripts/migrate_monthly_expenses.py --allow-nonlocal
```

The command above is review-only and opens no database connection. The following command is for a separately approved production migration ONLY:

```sh
venv/bin/python scripts/migrate_monthly_expenses.py --allow-nonlocal --apply
unset MONTHLY_EXPENSE_MIGRATION_URL
```

Check the command exit status; on failure stop and privately review sanitized diagnostics. Do not paste raw connection failures into chat. The runner uses a transaction, 5-second lock timeout and 60-second statement timeout. `001_dhl_monthly_expenses.sql` adds only the two monthly tables, indexes and guards. It does not alter/drop existing tables or backfill/approve financial records.

**The immutable payslip migration remains separate, pending approval and unimplemented.** Existing manual payslips and historical PDF records are retained. Do not approve the unresolved February Telematics value, historical source dates, reference meanings or no-activity decisions during deployment.

The application's pre-existing startup cleanup/DDL still runs on restart; the new monthly migration is not executed at startup. This is another reason to confirm the correct target and backup before deployment.

## Approved future deployment order

1. Resolve/explicitly accept the vehicle-write policy; verify private DB/SMS comparisons and runtime settings. Announce the re-login window and pause financial edits/import confirmations.
2. Verify backup/restore, record release and rollback artifacts, and agree the production migration. Review both repository diffs; exclude real workbooks, `.env`, backups and exports from release commits. No commit/push is authorized by this preparation.
3. Coordinate Render auto-deploy behavior before any later authorized push, so a push cannot deploy ahead of configuration or migration. Stage backend settings with Save only. Do not activate the new JWT key by deploying an old build.
4. Apply the approved additive migration only if absent. Preserve all existing tables/documents.
5. Deploy the exact reviewed backend artifact to **smithsons-logistics**. This activates the approved JWT transition; previous tokens will be rejected and users log in again. Verify actual database target, startup and auth before continuing.
6. Deploy/rebuild the reviewed frontend to **smithsons-logistics-frontend** with its existing exact backend URL. For its current Vite app, verify build command `npm ci && npm run build`, publish directory `dist`, and SPA rewrite to `index.html` before release. Retain custom domains and CORS.
7. Complete smoke checks below, monitor sanitized logs/errors, then resume financial work. Never access the unused service as part of this sequence.

## Post-deployment smoke checklist

- Backend starts on Render PORT without missing-setting, database or worker errors; no secrets appear in logs.
- Existing admin, owner and driver accounts can log in with unchanged passwords; old tokens return 401 as expected after transition. Use authorized designated accounts; no password resets/role edits are part of release.
- Admin areas load; owner/driver own dashboards and records remain scoped. Owner/driver admin API attempts return 403; anonymous attempts return 401. Admin URL shells redirect safely and expired sessions return to login without loops.
- `/expenses/` and `/commissions/` permit admin, deny non-admin. A driver cannot submit against another driver's trip through either URL variant. Perform write checks with disposable staging data, not by modifying production financial records.
- Existing orders, trips, vehicle listings, DHL summaries/reconciliation, manual payslip retrieval and existing PDF downloads work. Do not generate/revise real payslips merely to smoke-test production.
- Monthly pages load and migration-required errors are absent. Verify an existing approved report read-only if available; use synthetic staging data for upload/correction/confirmation/export tests. Do not create or approve synthetic/February financial records in production.
- Frontend build calls only the intended backend and actual frontend origins pass OPTIONS with Authorization. Reload protected deep links to verify SPA routing.
- Verify SMS configuration privately without sending. A real delivery test requires separate explicit authorization; do not invoke send/report/notification-test endpoints during this checklist.

## Rollback and readiness limits

- Keep the new JWT key and correct DATABASE_URL in place. Do not restore the insecure fallback, old secret logging or embedded DB/SMS credentials. Another key change would invalidate sessions again.
- For frontend problems, return to the recorded compatible frontend artifact and pause monthly operations while assessing backend compatibility.
- For backend problems, roll back only to a pre-reviewed artifact that retains required environment-only configuration and authorization safeguards. The previous pre-remediation production artifact is NOT automatically a safe rollback target. Prepare a security-preserving rollback artifact before release; if none is available, pause affected operations/use a controlled maintenance window and fix forward rather than restore insecure code.
- Retain additive monthly tables and all confirmed/source evidence. No DROP/down migration, manual confirmed-row edit, or automatic database-backup restore is part of application rollback.
- Database recovery is a separate approved incident procedure. Restore to a new isolated target first, reconcile writes since the backup, and never silently redirect production to another database.

Local code/tests are ready for release review. Production DB/SMS equality checks, vehicle-write policy, backup verification, exact-artifact approval and migration/deployment authorization remain gates. Provider management configuration was not accessed or changed here. Local test services and disposable PostgreSQL were removed after verification.
