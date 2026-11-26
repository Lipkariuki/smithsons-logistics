# DHL reporting reliability review — 26 November 2026

Local implementation only. No production migration, records, confirmations, PDFs, SMS, commits, pushes or deployments were performed.

## Root causes and changes

1. The source itself stores the disputed numbers as literal values. For KAY025L, 14,134.37 + 1,089.07 = 15,223.44, while the inclusive value is 15,223.43. Parsing did not introduce the difference. The original rounding method cannot be proved from literal values alone. Cached fee and net references consistently corroborate the inclusive amount. Exact component equality formerly blocked otherwise calculable trucks; the previous component-adjustment policy changed the selected amount by cents.
2. Net Summary parsing assumed a narrower table layout and lacked safe owner/continuation handling. Table discovery now inspects actual headers across worksheets, retains original expense descriptions and workbook owners, handles reordered columns, repeated headers and clear notes, and requires explicit selection for competing tables. Merged financial cells, conflicting duplicates, numeric orphan rows and invalid nonblank values remain blocking.
3. Generic “Needs review” hid both safe provisional calculations and the actionable cause. Backend statuses now distinguish ready, calculated/source review, missing activity, blocked and confirmed. React displays server-calculated figures only. Material issues still prohibit confirmation/PDF issuance.
4. Expense approvals needed reusable provenance. Unambiguous previously approved expense mappings can be reused across months, retaining the original approving administrator, timestamp and import; ambiguous mappings still require review. Deductions are rebuilt from the current workbook, never accumulated from previous imports or manual expenses.

## Approved source reconciliation policy

- Retain the original valid DIST inclusive amount once; never adjust AMOUNT, SURCHARGE or inclusive values.
- Accept only an exactly KES 0.01 discrepancy with corroborating fee/net references, nonconflicting row/reference identity and no source error marker. If formulas exist, their references must support the same inclusive value; a contradictory formula is not accepted merely because its cached value matches.
- Absolute caps: KES 0.05 per truck and KES 0.25 per month. Opposite signs do not offset the caps. Missing evidence, larger differences and exceeded caps remain blocking.
- Persist original values, signed difference, evidence and accepted status in a new policy/version. Legacy policies and already-confirmed snapshots/PDF bytes remain intact.
- Fee = each inclusive DIST row × 5%, rounded HALF_UP, summed. Offloading is exempt. Base = gross − fee − workbook expenses; commission = 7% of positive base, HALF_UP; net = base − commission.
- PDF includes an explicit signed source reconciliation line, so displayed DIST + surcharge + Offloading + reconciliation equals source-inclusive gross. Expenses retain the approved workbook descriptions.

## September source verification

Corrected local DHL workbook: `SEPTEMBER 2026 GROSS TOTALS (1).xlsx`; Net Summary: `SEPTEMBER 2026 NET SUMMARY.xlsx`.

There are 508 charge rows (254 DIST, 254 Offloading), 20 transport trucks and 32 expense rows. Eleven evidenced one-cent differences have absolute total KES 0.11 and signed inclusive-minus-components total KES -0.09. Maximum truck absolute difference is KBM439P KES 0.05. No values were silently corrected.

| Truck | Gross | DHL fee | Expenses | Commission | Net |
|---|---:|---:|---:|---:|---:|
| KAY025L | 201,891.81 | 9,231.01 | 83,380.67 | 7,649.61 | 101,630.52 |
| KBM439P | 352,170.34 | 16,889.87 | 158,365.62 | 12,384.04 | 164,530.81 |
| KBZ339V | 333,727.80 | 16,283.94 | 181,897.45 | 9,488.25 | 126,058.16 |
| KCE864K | 303,030.02 | 14,492.49 | 159,005.88 | 9,067.22 | 120,464.43 |
| KDL090S | 297,953.84 | 14,524.66 | 185,571.44 | 6,850.04 | 91,007.70 |
| KAV086M | 281,630.35 | 13,319.83 | 183,544.95 | 5,933.59 | 78,831.98 |
| KBP997E | 33,944.16 | 1,533.21 | 93,682.54 | 0.00 | -61,271.59 |

Full 32-truck figures: `output/reliability/september-per-truck.csv` and `.json` (local financial outputs, excluded from release).

Known transport gross KES 9,004,306.22; DHL fee KES 434,588.19; commission KES 246,824.89; net across the 20 matched trucks KES 3,217,973.31. Expense total across all 32 rows is KES 5,131,067.83; KES 26,148.00 belongs to the 12 trucks without verified activity and is not included in the 20-truck net total.

Unresolved activity: KBC554F, KBE438V, KBK988F, KBT092Y, KBU121A, KCA661S, KCE726U, KCH333X, KDG264X, KDK394Z, KDK767A, KDV188C. KCA661S and KCH333X each retain KES 2,668 expenses; KDK767A retains KES 20,812. These are missing transport matches, not automatically verified zero months. KBE438V is explicitly present in the expense workbook as “KBE 438V”.

KBZ339V has a source fee reference of zero on a DIST row: approved calculated fee KES 664.84 remains in the payout, and the source reference mismatch remains audit-visible. Manual workbook gross/net columns are comparisons only; prior-month Trailer overpayments are not reintroduced as transport income or deductions.

## Compatibility

February legacy source gross remains KES 9,858,161.63. KAV086M remains gross 302,109.41; expenses 152,534.00; commission 10,470.28; net 139,105.13. Six historical out-of-period rows remain subject to date review; no dates were changed.

August source-inclusive gross remains KES 10,400,947.43, DHL fee 503,297.34 and expenses 5,521,182.00. The four one-cent differences now qualify under the evidenced policy without changing their money values. KDA267N's error-marked trip and 11 activity gaps remain unresolved. Historical confirmations/PDFs keep their original policies and figures.

## Migration and controlled release

Migration `008_source_inclusive_reconciliation.sql` extends the existing calculation validation function for the new frozen policy, with evidence and cumulative cap checks. It does not create/drop tables, change columns, update financial rows or rewrite documents. It requires migrations 006 and 007. The runner executes in one transaction; rollback and repeat execution are tested locally. Production 007 state has not been verified and must not be assumed from an application redeployment.

Before release: verify exact production target, create/restore-check a fresh backup, inspect applied guard definitions, apply pending prerequisite 007 only if needed and approved, then approved 008 transactionally. Verify record counts and confirmed PDF hashes unchanged. Deploy backend first, perform read-only checks, then frontend. Do not confirm unresolved financial records.

Rollback: stop new confirmations; roll application commits back in backend/frontend compatibility order. Keep any new confirmed policy snapshots and PDF bytes. Do not reverse schema by deleting records or restore an old database over subsequent financial activity. Retain the additive compatible guard dispatcher unless a reviewed replacement is required.

## Exact implementation files

Backend:
- `routers/monthly_payouts.py`
- `services/dhl_revenue_policy.py`
- `services/dhl_rounding_reconciliation.py` (new)
- `services/monthly_expense_dates.py`
- `services/monthly_expense_parser.py`
- `services/monthly_expense_persistence.py`
- `services/monthly_expense_reports.py`
- `services/monthly_payouts.py`
- `services/monthly_statement_documents.py`
- `services/truck_confirmations.py`
- `migrations/008_source_inclusive_reconciliation.sql` (new)
- `scripts/migrate_source_inclusive_reconciliation.py` (new)
- `tests/test_august_dist_admin.py`
- `tests/test_component_cent_policy.py`
- `tests/test_dhl_revenue_verification.py`
- `tests/test_monthly_payouts.py`
- `tests/test_dhl_reporting_reliability.py` (new)
- `tests/test_dhl_reliability_persistence.py` (new)
- `tests/serve_dhl_reliability_fixture.py` (new, loopback test server only)
- `tests/dhl_reliability_browser.mjs` (new, real local HTTP/browser workflow)
- This review document.

Frontend:
- `src/pages/reports/DhlMonthlyPayouts.jsx`
- `src/pages/reports/monthlyExpenseUi.js`
- `tests/monthlyExpenseUi.test.mjs`
- `tests/monthlyExpenses.browser.test.mjs`

No authentication, fleet, SMS or production configuration changes. Financial workbooks and generated financial outputs must remain excluded from commits.

## Verification results

- Backend: 244 tests executed, 230 passed, 14 skipped; no failures. Skips are optional external/browser fixtures and the unavailable older September filename; the corrected actual September workbook is explicitly covered by the new tests.
- Frontend: 22 unit tests and 17 browser tests passed. Production build passed, with the existing large-chunk warning.
- Actual September PDF extracted totals and visually rendered layout passed.
- Real browser → FastAPI → disposable PostgreSQL test passed: actual raw/expense uploads, automatic saving, reopen without reupload, source reconciliation, independent KAY025L confirmation, download, synthetic correction version, and byte-identical prior PDF. The initial browser attempt had a 30-second download timeout; retrying with a 120-second allowance completed successfully. Large-workbook processing latency remains a separate performance consideration.
- Additional expense-approval provenance regression passed.
- Local migration tests verify rollback on failure, idempotent reapplication, unchanged legacy records and byte-identical historical PDFs.
- PostgreSQL writes were limited to temporary schemas in a loopback disposable database. Browser tests used a synthetic administrator, actual workbook originals and a deliberately synthetic local correction; none constitutes business approval.

Controlled release requires separate authorization and production prerequisite/backup verification. No deployment is approved or performed by this report.
