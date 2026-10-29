# Targeted legacy authorization remediation — 28 October 2026

Implemented the confirmed endpoint and frontend guard fixes from `auth-role-regression-verification.md`. No production access, database/schema migration, credential rotation, commit, push or deployment occurred. Unrelated pre-existing local changes were retained.

## Permissions changed

All routes in the following administrative routers now use the existing `Depends(require_role("admin"))` dependency. Owners and drivers continue to use their existing own-record APIs.

| Endpoint | Methods now admin-only |
| --- | --- |
| `/admin/orders` | GET |
| `/orders/` | GET, POST |
| `/orders/{order_id}` | PATCH |
| `/orders/{order_id}/assign-driver` | PUT |
| `/orders/{order_id}/assign-vehicle` | PUT |
| `/trips/` | GET, POST |
| `/trips/{trip_id}/revenue` | PATCH, PUT (already protected, now also covered at router level) |
| `/trips/{trip_id}/fuel` | GET, POST, PUT, DELETE (existing restrictions preserved) |
| `/trips/{trip_id}/with-expenses` | GET |
| `/trips/expenses-summary` | GET |
| `/trips/{trip_id}/profit` | GET |
| `/reports/summary` | GET |
| `/reports/pdf/{vehicle_id}` | GET |
| `/reports/send` | POST |
| `/vehicles/`, `/vehicles/{vehicle_id}` | GET only |
| `/users/` | GET only; `/users/me` remains available to all authenticated roles |

Real HTTP tests iterate every operation in the administrative router groups and verify anonymous 401 and owner/driver 403, including writes. Unauthorized write requests never execute business handlers. No SMS/report delivery was sent.

The existing `/partner/orders`, `/partner-dashboard/`, `/driver/trips` and `/driver/expenses` implementations were not modified. Owner orders, driver trips and driver expenses were verified against separate synthetic owners/drivers to ensure other users' records were not returned. Existing DHL/monthly-expense/fleet admin restrictions remain unchanged.

## Frontend and null handling

- Existing ProtectedRoute now verifies the session using real `/users/me`; it does not use an unverified role claim as the authority. It wraps admin, owner and driver route groups. An unauthorized signed-in user returns to their own dashboard before the other role's page shell mounts. Missing tokens return to login. Network/server verification failures fail closed with a retry message.
- The existing Axios client clears the current token and redirects once after an authenticated request receives 401. It preserves 403 as a permission denial. A stale request cannot clear a different newly issued token. Login failures are excluded so existing login behavior is preserved.
- Internal report PDFs now download via authenticated Axios rather than an uncredentialed `window.open` URL. The backend's PDF filename is retained through Content-Disposition; PDF content and calculations are unchanged.
- Only order response serialization changed: null purchase-order and dispatch-note references become empty strings for the existing string response contract. No database values or schema were changed.

## Files changed in this task

Backend:

- `routers/admin.py`
- `routers/orders.py`
- `routers/trips.py`
- `routers/reports.py`
- `routers/vehicles.py`
- `routers/users.py`
- `tests/test_legacy_authorization_http.py` (new, opt-in real HTTP integration checks)

Frontend (`../smithsons-logistics-frontend`):

- `src/App.jsx`
- `src/components/ProtectedRoute.jsx`
- `src/utils/axiosAuth.js`
- `src/pages/ReportsPage.jsx`
- `tests/legacyAuthorization.real.browser.test.mjs` (new, real backend, no API response mocks)

Documentation/evidence: this file and `output/legacy-authorization-fix/` (protected endpoint inventory and credential-free HTTP/monthly results).

Hash comparison confirmed no changes in this task to `main.py`, `routers/auth.py`, `settings.py`, `database.py`, `models.py` or `services/monthly_expense_calculations.py`. Login endpoint, JWT key/algorithm/lifetime, password handling, CORS, database schema and financial formulas were preserved.

## Verification

Actual FastAPI/Gunicorn and React/Vite ran locally against fresh disposable PostgreSQL 16, loopback port 55485. The Phase 2 migration was applied only to that disposable database. Fixtures used a synthetic admin, two owners, two drivers, two vehicles, separate orders/trips/expenses, synthetic DHL records and a synthetic monthly draft. The backend notification scheduler was disabled and external backend connections were blocked. Browser tests only blocked nonlocal resources; local APIs were real.

| Verification | Result |
| --- | --- |
| Backend existing regressions plus six new real HTTP tests | **91 passed** (85 existing + 6 new) |
| Existing frontend unit tests | **20 passed** |
| Existing mocked browser regressions | **9 passed** |
| New real-backend browser tests | **8 passed** |
| Frontend production build | **Passed** |
| Backend compile / both repositories' diff whitespace checks | **Passed** |

Real browser checks covered admin login and dashboard/orders/trips/fleet/users/expenses/finance/internal/DHL/reconciliation routes; owner/driver own pages and denied admin URLs; anonymous role-page denial; expired-token redirect without a loop; failed login with and without a prior token; authenticated DHL refresh; saved monthly draft loading; logout; and authenticated report PDF download with the original filename. No server 5xx responses were observed in the passing browser run.

The initial browser test attempt had two test synchronization errors (a locator matching two nested main elements and reading localStorage during a redirect). These were corrected in the test; the subsequent full run passed. A focused PDF check also passed after preserving the backend filename.

Backend tests include monthly expense parser/calculation/persistence/API, financial source-date and revenue verification, payslip branding, auth/configuration and SMS configuration regressions. Real monthly draft creation/retrieval succeeded; unresolved confirmation still returned 422. No real financial approvals were made.

Existing build notices remain: stale Browserslist data and a large JS bundle. No dependency upgrades or bundle redesign was undertaken.

The new integration tests require an explicitly provisioned disposable local fixture:

- Backend: `LEGACY_AUTH_HTTP_BASE` and `LEGACY_AUTH_FIXTURE_JSON`; the tests reject non-loopback backend hosts.
- Browser: `LEGACY_AUTH_FIXTURE_JSON`, `FRONTEND_TEST_URL`, plus optional `PLAYWRIGHT_MODULE` and `CHROME_PATH`; only local frontend URLs are accepted.
- The private temporary JSON fixture supplies generated synthetic credentials/tokens and the expired-token fixture. Seed IDs/records correspond to the synthetic dataset described above. It is deleted after testing, never committed or included in results. Ordinary test discovery skips these tests without the explicit fixture settings.

## Scope and permission decisions still needed — no changes made

1. **Legacy vehicle writes:** `POST /vehicles/` and `PUT /vehicles/{vehicle_id}` retain their existing authenticated fleet-manager phone rule. It is unclear whether that rule should be replaced with admin-only access or remain an intentional exception. The newer `/fleet` endpoints already require admin. Do not broaden/narrow these legacy write permissions without a decision.
2. **Adjacent financial routers:** the original audited endpoint list did not include `/expenses/` and `/commissions/`. A final local check confirmed anonymous GET requests still return 200. Their read/write role and ownership policy needs an explicit scope decision (admin-only versus scoped role access); they were not changed here. This remediation must not be represented as securing every API in the application.
3. **Alternate driver expense submission:** inspection found that trailing-slash `POST /driver/expenses/` checks the driver role but lacks the trip-ownership validation present in slashless `POST /driver/expenses`, which is used by the current frontend. This adjacent handler was not modified or exercised with a cross-user write. Review whether to make it follow the same own-trip policy in a separately approved fix.

Production JWT effective-key consistency still requires the manual platform verification described in the earlier report; no key was accessed or changed. Existing sessions remain compatible when the configured key remains unchanged. Expiration redirects occur when the guard/client receives an authentication failure; no refresh-token mechanism, lifetime change or server-side logout revocation was added.

Local test servers and the disposable database were stopped after verification. No deployment action was taken.
