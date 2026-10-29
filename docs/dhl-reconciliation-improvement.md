# Existing DHL reconciliation: compatible improvements and February findings

Later update: independent truck confirmation has now been implemented locally
following business approval. See per-truck-confirmation-release-plan.md for the
current schema, safeguards and required production execution approvals. The
proposal-only section below records the earlier investigation stage.

## Verified existing behavior

`src/pages/reports/DhlReconciliationPage.jsx`, mounted at
`/admin/reports/dhl-reconciliation`, calls GET `/dhl-reports/reconciliation`
when Check Month is clicked. This remains the same page, endpoint, date selectors
and button. There is no new navigation item.

The endpoint in `routers/dhl_reports.py` uses `DHLOrder.ref_no` against
`Order.order_number`, normalizing spaces and case. Invoice, purchase-order and
dispatch-note fields are NOT its keys. The verified 2026-10-29 09:16:47 EAT backup
contains 229 February raw-workbook references matching order_number and zero
matching the other three fields. This is backup evidence, not a current live
production query. No production connection was used for this investigation.

Orders persist the submitted order_number directly. The importer reads REF NO,
groups `(date, reference, normalized plate)`, sums AMOUNT for DIST and Offloading,
and stores distribution_cost/offloading_cost/total_revenue in dhl_orders. It does
not query the original workbook when reporting. Repeating DIST/Offloading rows
under one reference are legitimate charge components, not duplicate orders.

The old reconciliation aggregates by vehicle, compares reference SETS per truck,
counts trips versus imported DHL date/reference/truck records, and compares
Trip.revenue with DHL total_revenue. Internal dates come from Order.date, or
Trip.created_at for orphan trips. DHL dates come from DHLOrder.date. It does not
match amounts/dates/statuses for individual references. Repeated references across
dates affect old counts differently from set comparisons. Existing aggregate
results and the old Vehicle Comparison/Review Mismatch controls are preserved.

Internal Trip.revenue is initially the transport rate-card rate (or zero if none),
and can subsequently be manually edited. Offloading is communicated separately
by order creation, not stored as an explicit internal revenue component. The new
diagnostic comparison explicitly uses Trip.revenue minus DIST and displays gross
and Offloading separately. These are investigation differences, not established
owner-payable discrepancies; manual override semantics may need review. No old
financial formulas, trip statuses, orders or trip records are changed.

## Compatible changes implemented locally

The existing endpoint accepts opt-in `include_details=true` and optional positive
`financial_version`. Without the flag it retains its prior results; an optional
details field is the only response addition. Admin authorization is unchanged.

- Reference detail: both unmatched directions, normalized ambiguity, plate/date
  mismatch, missing/multiple trips, noncompleted status, transport differences.
  Matching references outside the selected dates are retained for date review.
- Truck detail: exact-source plate normalization, unique reference counts, live
  gross versus frozen snapshot gross, workbook expense/commission/net snapshots,
  roster gaps, duplicate matches, unassigned revenue, and eligibility explanation.
- Control totals: reference gross, truck gross, roster-assigned/unassigned/
  ambiguous-roster gross, reconciliation differences and unassigned vehicle gross.
- The same frontend shows Order Reconciliation and Truck Financial Reconciliation,
  matched/review filters, optional saved version selection, missing-data warnings,
  historical source issues and a separate zero-transport audit list. Scoped styling
  gives the new sections scrollable tables without redesigning the old page.
- Expense figures are read only from one selected saved workbook version. They
  never come from trip/manual expenses or accumulated import deductions. Existing
  v2 blank-to-zero auditing and dynamic categories remain unchanged.
- Latest saved version is the default and its draft/confirmed/superseded status is
  displayed explicitly. Enter a version number to inspect a previous snapshot.
  No saved version means unknown expenses/roster, not zero. Partial or multi-month
  ranges do not invent a monthly workbook comparison.
- Missing reporting storage is isolated with a savepoint: operational results
  remain available with a warning, without changing schema or starting a migration.

The old importer retains Admin-only entries as zero DIST/Offloading records,
usually REF 0; COST itself is not persisted. New operational detail separates such
zero-transport records instead of treating REF 0 across trucks as duplicate orders.
Where the raw workbook is available the audit knows which entries are Admin. From
database records alone it cannot distinguish Admin-only from genuinely zero-valued
charges, so it explicitly requests raw COST provenance. No nonzero transport revenue
is discarded; Admin never becomes an expense or reduces gross.

Historical raw dates can only be shown from saved monthly raw-review evidence or
the exact local workbook. A month-filtered dhl_orders query alone cannot reveal
rows excluded by the importer; absence of stored evidence produces a warning.

## February findings (provisional, no approval)

Compared the exact February workbooks with internal records from the verified
backup restored into disposable PostgreSQL. The app never started against restored
real data. Audit connections used read-only transactions. Synthetic server/tests
used a separate empty database. All private financial outputs remain outside Git.

| Control | Result |
|---|---:|
| Valid February DIST | KES 9,560,700.63 |
| Valid February Offloading | KES 297,461.00 |
| Gross grouped by reference | KES 9,858,161.63 |
| Gross grouped by truck | KES 9,858,161.63 |
| Difference | KES 0.00 |
| Gross on payout roster | KES 9,858,161.63 |
| Gross outside payout roster | KES 0.00 |
| Unassigned/ambiguous-roster gross | KES 0.00 |
| Admin audit-only total | KES -475,891.06 |
| Transport references with an internal order | 229 |
| Transport references without an internal order | 182 |
| Gross for those 182 references | KES 438,168.42 |
| Internal-only references in selected order-date window | 5 |
| Sum of their internal Trip.revenue amounts | KES 200,743.10 |

There are 25 imported-style zero-transport Admin audit records from 26 Admin rows,
kept separate from transport-order discrepancy counts. All actual transport gross
is accounted for. There are no DHL-only trucks outside the workbook roster.

Internal-only references (internal TRANSPORT amounts, not DHL gross comparisons):

| Order number | Truck | Internal amount | Order date |
|---|---|---:|---|
| 119825524 | KBA838N | 13,236.52 | 2026-02-01 |
| 119855140 | KDK394Z | 11,346.46 | 2026-02-01 |
| 119856051 | KDM008F | 119,959.00 | 2026-02-01 |
| 119856212 | KDK767A | 42,027.00 | 2026-02-01 |
| ORD-2025-99 | TEST001 | 14,174.12 | 2026-02-23 |

TEST001 and its order already exist in the backup; this investigation did not
create them in production or infer that they belong to an approved payout roster.

Workbook-only trucks (no transport charges; gross requires completeness/no-activity
evidence before being treated as confirmed zero):

| Truck | Workbook expenses |
|---|---:|
| KBE438V | 0.00 |
| KBK988F | 4,698.00 |
| KBM439P | 8,758.00 |
| KCA661S | 2,668.00 |
| KCE726U | 0.00 |
| KCH333X | 2,668.00 |
| KDG264X | 8,758.00 |
| KDK766A | 25,338.03 |
| Total | 52,888.03 |

KDK766A has only Admin entries. KCE726U's blank Telematics cell is zero under the
new workbook policy with audit, not a fabricated individual financial approval.

Other findings overlap: 136 date differences, 157 transport-amount differences,
one plate mismatch, one missing trip, and 233 noncompleted trip findings (started).
These counts are not additive and do not imply that 233 payouts are invalid.
Order and transport dates can legitimately differ; each remains an investigation.

Historical rows remain excluded and require separate review:

| Excel row | Date | Truck | REF NO | Charge | Amount |
|---|---|---|---|---|---:|
| 850 | 2024-05-27 | KDB924H | 615391 | DIST | -78,305.40 |
| 851 | 2025-03-26 | KAY025L | 118741043 | DIST | 15,704.85 |
| 852 | 2025-03-26 | KDG264X | 118729429 | DIST | 42,026.67 |
| 853 | 2025-05-19 | KCX114D | 0-661578 | DIST | 66,091.45 |
| 854 | 2025-10-06 | KDL090S | 667309 | DIST | 9,167.67 |
| 855 | 2025-10-06 | KDL090S | 667309 | Offloading | 600.00 |

Detailed private outputs in output/reconciliation-improvement/:
february-dhl-only-references.csv (all 182 and amounts),
february-internal-only-orders.csv, february-workbook-only-trucks.csv,
february-orders.csv, february-trucks.csv, february-historical.csv and
february-reconciliation.json. Reproduce with scripts/audit_february_reconciliation.py
using an explicit LOCAL test database URL, never production.

## Independent truck confirmation: proposal only, approval required

Confirmed monthly rows already generate independent stored statements. Operational
reconciliation is advisory and is not consulted by the statement generator. Thus
Truck B's missing operational reference does not invalidate Truck A's EXISTING
confirmed snapshot. This is covered by focused non-blocking eligibility tests.

However, `confirm_import` and the database guard validate every row in a month.
Rows remain editable until the parent is confirmed. Current statement storage
requires a confirmed or previously confirmed parent. A good row in an unresolved
draft therefore CANNOT safely receive a new confirmed statement independently.
No guard has been bypassed and no row has been marked eligible on that basis.

Smallest proposed architecture, NOT implemented:

1. Add one append-only truck-confirmation table (`dhl_monthly_truck_confirmations`,
   proposed name only) referencing the exact import row,
   with reporting month/normalized plate, previous confirmation, confirmer/time,
   policy/source-evidence hashes and a current/superseded lifecycle. Enforce one
   current confirmation per truck/month transactionally and at database level.
2. Freeze the referenced row AND its parent workbook, mappings, decisions and
   source evidence once any truck is confirmed. Existing revision flows already
   create a new import version, so remaining corrections use that mechanism.
   Do not weaken the existing whole-month confirmed/superseded invariants.
3. Add an explicit admin per-truck preview/confirmation action. Shared blockers
   (month identity, approved headers, source integrity/completeness) remain required;
   row-specific expense/revenue/date issues block only affected rows. Unattributable
   source issues require scoped evidence before any potentially affected truck is
   approved. Operational reference discrepancies alone remain advisory.
4. Let the immutable document store reference this explicit truck confirmation,
   while preserving compatibility with existing whole-month confirmations and
   historical PDFs. Reprints use stored bytes; corrections create new confirmation
   and document versions. Do not silently mark other rows confirmed or supersede
   their valid statements when a single truck is corrected.
5. Derive a display-only partial-confirmation state without reclassifying a draft
   as wholly confirmed. Keep the original month-confirmation/export workflow and
   explicitly label approved versus provisional truck figures.

This requires a separately reviewed additive migration plus narrow changes to row/
parent guards and document authorization. It is a significant immutable-record
change, so implementation is deliberately stopped pending user approval. It does
not authorize migration application or deployment. No new schema change was
implemented for this reconciliation improvement.

## Current release boundaries and risks

The prior local statement/policy migrations 002/003 remain separate and unapproved
for production. The frontend release remains unpushed. These reconciliation changes
are uncommitted on top of that existing local work; do not push the old commit as
if it contains this feature. No existing importer or financial confirmation,
statement calculation or production record was changed during this task.

Read-only reference matching currently projects all order reference/date/plate/
amount candidates to normalize Unicode consistently, including out-of-window
matches. At the current backup size (1,987 orders) this is small. A normalized
reference index or pagination would be a separately reviewed scalability change;
no schema/index migration was added here.

## Verification and changed files

All 122 backend tests passed with no skips, using disposable PostgreSQL and the
existing real HTTP synthetic-account fixture. All 39 frontend unit/browser tests
passed with no skips, including nine real-backend browser tests and ten mocked
browser tests. The new real-backend test logs in locally, uses Check Month and
version/filter controls, verifies both new sections and the original vehicle table,
and asserts that no writes other than synthetic login occur. No server errors were
observed. The remaining 20 frontend tests are isolated unit tests.

The focused 13 reconciliation tests were repeated after the final roster-control
totals addition; the new real-browser check and production build were also repeated
after scoped styling. Existing build warnings about bundle size and stale
Browserslist remain unchanged. Python compilation and diff whitespace checks pass.

One intermediate focused browser rerun failed after a local Gunicorn HUP reload:
macOS repeatedly aborted forked workers during Objective-C initialization. This
was a test-fixture reload failure, not a financial/authentication code change.
The fixture was restarted with single-process Uvicorn and the final real-browser
reconciliation check passed with no API writes or server errors. Production
startup configuration was not changed. All disposable services were stopped after
verification and synthetic credential files removed.

Backend files in THIS reconciliation change:
routers/dhl_reports.py; schemas.py; services/dhl_reconciliation_detail.py;
scripts/audit_february_reconciliation.py; scripts/verify_reconciliation_query.py;
tests/test_dhl_reconciliation_detail.py; tests/test_dhl_reconciliation_query.py;
docs/dhl-reconciliation-improvement.md.

Frontend files in THIS reconciliation change:
src/pages/reports/DhlReconciliationPage.jsx;
src/pages/reports/DhlReconciliationDetails.jsx;
src/pages/reports/DhlReconciliationDetails.css;
tests/dhlReconciliation.real.browser.test.mjs.

Other pre-existing local monthly statement/expense-policy and insurance/SMS changes
were preserved. No commit, push, deployment, production migration/data change,
delivery call or February confirmation was performed. Local restores, schema
migrations and synthetic writes were confined to explicitly named localhost test
databases. The production backup was mounted read-only and left unchanged.
