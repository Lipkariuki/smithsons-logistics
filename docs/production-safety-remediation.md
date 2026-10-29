# Production safety remediation

Status: **local remediation and regression verification complete; production rollout pending approval and private configuration verification.** No production connection, data change, migration, deployment, commit, push, secret rotation, SMS or email occurred.

## Issues found and corrections

| Area | Previous behavior | Correction |
|---|---|---|
| Database | database.py selected a literal remote URL regardless of DATABASE_URL; SQL echo enabled | Required environment URL; declared psycopg driver; exact host/port/database/credentials/query retained; SQL echo disabled, parameters hidden, pooled connections checked before reuse |
| JWT | Code read JWT_SECRET_KEY with a known insecure default; Render declared SECRET_KEY | Required canonical JWT_SECRET_KEY; corrected blueprint name; no default/automatic alias/key generation; existing configured key bytes, HS256 and normal 30-minute expiry preserved |
| Auth logging | Printed signing secret, bearer tokens, decoded payload, identity and decoder errors | Fixed event labels only; no credentials, token, payload, identity or exception body |
| JWT error handling | A signed nonnumeric subject could produce a 500 | Invalid subjects return 401, as other invalid credentials do; valid existing user tokens unchanged |
| SMS credentials | Embedded API key overrode environment; account username defaulted implicitly | Lazy client requires explicit username and API key from environment; initialization errors sanitized; no network or initialization at import |
| SMS logging | Printed complete provider responses/errors; returned raw exception text | Success/failure labels only; sanitized failure response; existing sender/phone normalization and SDK keyword compatibility retained |
| Bootstrap utilities | create_users.py had embedded account passwords and printed a password | Explicit bootstrap password settings, checked before any script writes; no password logging or raw failure text; script never executed here |
| Hosted .env loading | main/auth loaded development files implicitly | Central settings loader ignores .env in production and when Render/Railway host markers are present; development files remain optional locally, never override environment |
| Deployment | Render referenced Gunicorn without declaring it; fixed listening ports | Declared and locally installed gunicorn 26.2.0 only; commands use platform PORT, matching existing Uvicorn worker class |
| Frontend logging | Raw Axios errors could expose login passwords, bearer headers and response bodies in browser console | Logging-only helper emits fixed labels and numeric HTTP status codes; raw error objects no longer logged across the affected pages |

No financial calculation, DHL importer, reconciliation formula, report persistence, manual payslip formula, auth storage/navigation, SMS delivery endpoint or notification schedule was redesigned.

## Files changed in this remediation

Backend:

- `settings.py` (new): validated environment configuration and controlled local .env loading.
- `database.py`: environment-only target; no SQL/parameter echo.
- `routers/auth.py`: required configured key, safe diagnostics and invalid-subject handling.
- `services/africastalking_client.py`: remove embedded provider key/account fallback; lazy configured client.
- `utils/sms.py`: safe diagnostics/failures, preserve send contract.
- `create_users.py`: explicit bootstrap credentials, remove stale credential examples/password output and sensitive failure logging.
- `main.py`: import centralized settings before database/services instead of unconditional .env loading. Existing startup SQL/notification behavior remains unchanged.
- `render.yaml`: secret settings are user-supplied, canonical JWT variable, production mode and platform listening port.
- `Procfile`: matching declared Gunicorn/Uvicorn worker startup, with platform port and existing local port fallback.
- `requirements.txt`: add gunicorn 26.2.0; no unrelated package upgrade. Local install added only Gunicorn.
- `.env.example` (new), `.gitignore`: names-only/safe nonsecret template, explicitly allowed into version control; actual .env files remain ignored.
- `tests/test_production_safety.py` (new): 20 configuration/auth/logging/SMS regressions.
- `tests/test_monthly_expense_api.py`: inject the safe logger when loading real auth function bodies into its isolated fixture; financial assertions unchanged.
- `scripts/smoke_production_safety.py` (new): guarded real Gunicorn/auth/monthly-report smoke test requiring a fresh loopback test DB.
- This document.

Frontend:

- `src/utils/logSafeError.js` (new).
- Logging-only import/call changes in LoginPage, AdminEarnings, ExpensesPage, admin/AdminDashboard, admin/AdminFleetPage, admin/AdminTripsPage, driver/TripsPage, driver/DriverExpensesPage, driver/DriverTripsPage, orders/OrdersDashboard, partners/PartnerOrdersDashboard, partners/OwnerDashboard, revenue/RevenueDashboard.
- `tests/logSafeError.test.mjs` and `tests/authLogging.browser.test.mjs` (new).

Other dirty files in these repositories predate this remediation. Do not include unrelated changes or financial workbooks in a release automatically.

## JWT compatibility and required stop condition

Previously, only JWT_SECRET_KEY controlled signing. SECRET_KEY was ignored by the auth implementation, even though the blueprint declared it. Selecting SECRET_KEY automatically now would change the effective key for installations that previously used the fallback. We intentionally do not implement that unsafe alias.

If production already has a real JWT_SECRET_KEY configured, retain its exact value. The application neither trims, regenerates nor rotates it. Existing tokens signed with that key remain valid; this was verified with both isolated tests and a token created before the real Gunicorn worker started. Algorithms and normal token lifetime were not changed.

If production has only SECRET_KEY, an empty canonical setting, a development-file-only setting or the old known fallback, **stop the rollout**. Privately determine the effective old signing key and its source. A development-file key may be transferred unchanged to the platform setting only if it is a legitimate approved key. Do not copy the known insecure fallback into the new setting: the application rejects it.

Using the insecure fallback cannot be made both secure and transparently session-compatible. An explicit, approved key cutover and reauthentication plan is required. Do not add the insecure key as a secondary verification key. Pausing logins and allowing ordinary 30-minute tokens to drain can reduce disruption, but cannot make a compromised signing key trustworthy. If the existing real key was exposed through prior logs, its eventual rotation also requires a separate approved session-impact plan. No key or active session was changed here.

## Required variable names — no credential values

Application startup:

- `APP_ENV`: use production mode on hosted services; accepted modes are validated.
- `DATABASE_URL`: existing active PostgreSQL target, verified privately before rollout.
- `JWT_SECRET_KEY`: existing approved effective signing key, preserved exactly unless rotation is separately approved.

When SMS is requested:

- `AFRICASTALKING_USERNAME`
- `AFRICASTALKING_API_KEY`
- `AFRICASTALKING_SENDER_ID`: existing sender configuration; the existing nonsecret Smithsons branding default is retained when omitted. No account/key default remains.

Deployment/unchanged operational configuration to verify:

- `PORT`
- `VITE_API_BASE_URL` (frontend build setting, public URL only)
- `CORS_ORIGINS`, `CORS_ORIGIN_REGEX`
- `FLEET_SCHEDULER_ENABLED`, `FLEET_NOTIFICATION_RECIPIENTS`, `FLEET_NOTIFICATION_HOUR_UTC`
- `FLEET_INSURANCE_SMS_TEST_MODE` only for its explicitly authorized existing test feature.
- `WEB_CONCURRENCY` / `GUNICORN_CMD_ARGS` if configured by the host; review worker count and existing per-worker startup tasks.

Optional explicit account bootstrap script only:

- `BOOTSTRAP_ADMIN_PASSWORD`
- `BOOTSTRAP_DRIVER_PASSWORD`

`SECRET_KEY` is not a supported automatic JWT alias. No frontend VITE-prefixed variable should contain credentials or signing keys. No actual platform variable value was changed or included in this report.

## Tests

- **85 backend tests passed**: previous 65 financial/reporting/revenue/branding tests plus 20 new security/config/auth/SMS tests. PostgreSQL tests used temporary schemas in a new disposable loopback container only.
- **20 frontend unit tests passed**: previous 17 plus 3 safe-logging tests.
- **9 frontend browser tests passed**: previous 8 monthly/DHL regressions plus failed-login credential-logging regression. Browser API responses in these tests were intercepted; nonlocal requests were blocked.
- **Frontend production build passed** to a temporary output directory. Existing stale Browserslist and bundle-size warnings remain.
- **Exact Render Gunicorn command started real main.app successfully**, with ordinary startup lifecycle, real PostgreSQL, real auth/password verification and real reporting APIs. Production settings loader/database.py were used, not replaced by a fake database module.
- Token signed before startup remained valid; real login produced a valid token; incorrect password and invalid token returned 401. Captured Gunicorn/application logs contained no synthetic signing key, DB password, account password, bearer token or provider key.
- Real monthly API preview, date blocking, unresolved draft save, stored-workbook revision, synthetic category/blank/no-activity/date decisions, confirmation, history, monthly summary and Excel/PDF downloads passed. Synthetic total net 624.25; unchanged legacy manual payslip net 730. No actual February data was approved or altered.
- SMS SDK was mocked for configuration/send-contract tests. The real smoke process had notification scheduling explicitly disabled and a socket guard blocking every nonlocal connection. No real provider initialization or SMS/email delivery occurred.
- Gunicorn was tested on the local Python 3.13 environment and requires Python 3.10 or newer. Production runtime version must be checked before deploying; no Python upgrade was performed.

Reproduction: run the existing unittest suite with MONTHLY_EXPENSE_TEST_URL pointed to a loopback database ending `_test`; append the available test-only PDF dependency path if needed. The new smoke script additionally requires PRODUCTION_SAFETY_TEST_URL, refuses nonlocal/non-test targets and refuses a nonempty users table. It applies existing base/Phase 2 schema only in that disposable DB. Do not point either test command at production.

Sanitized smoke evidence: `output/security-remediation/startup-and-workflow.json`. Logs stay in temporary storage; test exports contain only synthetic data. Local services/test container were stopped after verification.

## Deployment findings and verification limits

Checked repository configuration, local variable names and official provider documentation. No authenticated Railway or Render management connector was available, so live dashboard settings, current production key source, actual production DB target, runtime version and provider account/key agreement remain **unverified**. No production database, secret retrieval or provider test request was attempted.

- DATABASE_URL previously did not control database.py. A preexisting platform value might point somewhere other than the active hardcoded target. Before deployment, an authorized operator must verify that the selected URL resolves to the SAME existing database/cluster and identity. Do not provision or switch databases as part of this remediation. URL normalization selects the declared psycopg driver without changing target/credentials/options.
- Same-project Railway services can use their private DB reference; an external Render backend cannot use Railway-private DNS and needs the approved external connection to the same DB, with appropriate TLS configuration. This is a connectivity/configuration choice, not authorization to change database. [Railway networking guidance](https://docs.railway.com/overview/best-practices), [Railway PostgreSQL reference](https://docs.railway.com/databases/postgresql).
- Render/Railway hosting markers prevent development .env fallback. [Render default variables](https://render.com/docs/environment-variables), [Railway variable reference](https://docs.railway.com/variables/reference).
- Render secret settings now use sync:false. There is no generated signing key or committed connection/API credential. An operator must stage the approved values without triggering an unapproved automatic deployment. [Render environment-variable management](https://render.com/docs/configure-environment-variables).
- Gunicorn is now declared and installed. PORT-based binding was tested; no new Uvicorn worker package or unrelated dependency upgrade was introduced. The existing pinned Uvicorn worker remains available but is deprecated upstream; a worker-package migration is separate from this targeted fix. [Gunicorn package](https://pypi.org/project/gunicorn/), [Render FastAPI startup guidance](https://render.com/docs/deploy-fastapi).
- Frontend authenticated Axios URL selection and Bearer/localStorage behavior are unchanged. Existing local frontend config contains only the public API-base setting. No frontend hosting manifest was found; verify dashboard build/publish/SPA fallback, actual HTTPS API base and backend allowed origins before any approved release. Build-time settings require a rebuild. [Vite environment guidance](https://vite.dev/guide/env-and-mode).

## Approved future rollout sequence

1. Review this security-only change set separately from earlier financial/fleet work. Review the required platform runtime and install the declared requirements in staging. No new migration is required for this remediation; the financial feature's existing Phase 2 migration remains a separate approval.
2. Privately verify the effective JWT key source. If a valid canonical key exists, preserve its exact value. If the insecure fallback is active, stop and obtain explicit approval for a secure key/session cutover before deployment.
3. Privately verify DATABASE_URL points to the currently active database. Stage that exact approved target, including correct driver/TLS/connectivity, without changing production data or creating a replacement DB.
4. Privately verify the configured SMS username/key equal the account/key intentionally used before this change. The embedded key previously overrode environment, so blindly trusting an old environment value could switch the provider credential. Move the approved existing credential into secure environment configuration without automatically rotating it. Confirm sender and scheduler settings; no live send is part of this verification.
5. Stage production mode and verified environment names in the provider's secret manager/settings. Do not trigger a deployment until separately approved. Never paste values into chat, reports or logs.
6. Run the same staged startup/login/token-continuity/report checks with scheduling disabled. The existing normal startup performs Base.metadata.create_all plus schema/data cleanup statements; this remediation did not change that behavior. A production rollout must explicitly account for those existing startup writes and per-worker scheduler behavior; do not use startup as an unreviewed migration mechanism.
7. After approval, deploy backend with safe config, observe sanitized startup/auth/report diagnostics, and validate existing-user access without exposing tokens. Deploy the logging-only frontend build after its separate approval. Enable/retain production SMS scheduling only under the approved operational plan.

## Rollback and remaining risks

- There is no security-remediation schema migration or production data rewrite to reverse. Preserve database/financial snapshots and the verified effective JWT/provider settings.
- Roll back to a reviewed safe artifact, or roll forward a corrected config. Do not restore a version that logs keys/tokens, chooses the old hardcoded target or uses embedded provider credentials. If no safe artifact exists, pause traffic and fix forward rather than reintroducing exposure.
- A startup-command problem can be isolated by temporarily using the already-declared Uvicorn server while retaining safe settings/logging, after approval; do not unset required variables to make startup succeed.
- Never auto-regenerate keys during rollback, silently accept the insecure JWT fallback or switch the DB target. Any rotation or forced reauthentication is a separate approved operation.
- Credentials and access tokens may already exist in Git history, older logs, external exports/backups or previously deployed artifacts. Removing them from current source/logging does not revoke those copies. Rotation and controlled historical-log/history cleanup require owner approval and were not performed.
- Existing in-process fleet scheduler/startup database writes and browser localStorage token storage remain unchanged. Scale/startup and XSS/storage hardening require separate review; no authentication-flow redesign occurred.
- All real production configuration checks listed above remain blockers to deployment approval. No production rollout or session/key transition has been authorized by this local remediation.
