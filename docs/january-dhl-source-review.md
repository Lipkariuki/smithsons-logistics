# January DHL source validation — local correction

Status: administrator authorized deployment of the January correction and a targeted loading improvement. Prepare/test an isolated backend-only release; no migration, production financial write, upload, confirmation or SMS.

## Exact cause

The actual uploaded file, `data/JANUARY 2026 TRIPS SUMMARY (1).xlsx`, has one worksheet, `Sheet1`, header row 1 and 747 data rows: 361 DIST, 361 **Offload** and 25 Admin rows. All transaction dates are within January 2026. The new `charge_issues()` whitelist accepted only DIST/Offloading/Admin, incorrectly rejecting all 361 Offload rows. The proven legacy importer already recognizes Offload, and the immutable manifest parser already sums it correctly; neither needs rewriting.

A narrow, read-only production check against the previously verified Railway target confirmed:

- 386 persisted January DHL reference/date/truck groups; DIST 9,286,008.41 plus Offloading 282,052.50 equals **KES 9,568,060.91** gross.
- Saved raw workbook id 2/version 1 hash exactly matches the local January file. Saved expense import id 2/version 1 is a draft; its hash matches the local Net workbook.
- Date/reference/registration/separate charge amounts match the complete persisted manifest. Before the correction the only 361 issues were unsupported COST labels; against the same read-only source snapshot the corrected validator returns no issues.
- No source replacement, revenue reimport or historical payslip change is necessary.

## Small correction

`services/monthly_expense_dates.py`: accept exact **Offload / Offloading** aliases (case/outer whitespace insensitive), canonicalizing both to the same duplicate-charge identity. Unknown or mixed COST values still block and now name the actual offending label. Date, reference, truck and amount checks remain strict. Admin remains audit-only. The source manifest and retained metadata format are unchanged so immutable archives and checksums remain compatible.

`services/monthly_payouts.py`: an already-saved draft can retain unavailable figures even after the validator is corrected. Detect when its prior unsupported-charge issues have genuinely decreased under current validation; reopening returns a **read-only preview** from the saved original files. Do not rewrite the original report. A later explicit user action appends a new draft with an alias-revalidation audit reason, avoiding the existing duplicate-workbook shortcut returning the old unavailable snapshot. Confirmation and PDF issuance remain explicit. Unknown charge types do not trigger a spurious recovery or become verified automatically.

No frontend or migration change is required. Existing saved files can be reused without another upload. Confirmed versions, source bytes, historical manual payslips, source dates and immutable statement PDFs are preserved.

## Actual January checks and remaining business review

Net workbook: `JANUARY NET SUMMARY.xlsx`, one worksheet, header row 2, **31 truck rows** (rows 3–33), total row 34. Five supplied expense categories; absent Kasarani fuel is audited zero. No blank-cell blocking issues. Approved operating expenses sum to **KES 4,604,877.05**. NET PAID 1/2/final and workbook commission are comparisons only, never calculation inputs.

KAV086M January calculation (not February):

| Figure | KES |
|---|---:|
| DIST | 343,716.88 |
| Offloading | 11,169.00 |
| Gross | 354,885.88 |
| Fuel | 153,450.00 |
| Breakages | 9,012.53 |
| Telematics & VSS | 8,758.00 |
| GPRS | 0.00 |
| Shunting | 2,280.00 |
| Total expenses | 173,500.53 |
| Commission base | 181,385.35 |
| 7% commission, ROUND_HALF_UP | 12,696.97 |
| Net payable | **168,688.38** |

Real remaining source discrepancies must stay visible:

- DHL has **KDV188C**; the Net workbook has **KDV118C** (expense row 33, expenses 74,517.57). This could be a typing error, but it requires administrator identification. Do not alias registrations, move revenue, assume zero expenses or edit either original silently. An approved workbook correction must be a new version.
- Six other expense rows have no DHL transport rows: KBE438V (0.00 expenses), KBK988F (4,698.00), KBM439P (14,211.03), KCA661S (2,668.00), KCH333X (2,668.00), KDG264X (8,758.00). Legitimate no-activity status requires explicit evidence; preserve the resulting zero/negative balances and zero commission where appropriate.
- Thus January has 31 expense trucks plus one DHL-only registration, yielding the screenshot’s 32 visible trucks. Fixing Offload should not hide the plate/no-activity review items or make every monthly total appear complete. Eligible matching trucks remain independently confirmable.

## Verification and execution boundary

Added `tests/test_dhl_source_aliases.py`: actual January totals/expenses/KAV net, Offload/Offloading case/whitespace for all 12 months plus January next year, canonical duplicate detection, unknown/ambiguous labels, strict month/year and reference/plate/amount mismatch blocking.

Expanded `tests/test_monthly_payouts.py`: simulate the old rejected saved draft, reopen with a read-only preview, verify the original and version count remain unchanged, explicitly create a new audited version without either upload, verify idempotence/independent confirmation/PDF behavior, and prove unknown charge types stay blocked.

Final clean isolated run: **187 backend tests passed** (38.632 seconds), **42 frontend checks passed with zero skipped** (51.591 seconds), and the production frontend build passed. This includes unchanged February calculations, authenticated reporting/reconciliation, legacy replacement protections and immutable PDF/correction regressions. Browser verification uses the unchanged deployed frontend against the isolated corrected backend; the synthetic future-January fixture uses Offload to exercise upload preflight and saved-file reopening end to end. No synthetic correction is a real January/February approval.

Proposed release, only after approval: isolated backend-only commit for the two services, two test files and this review; deploy active Render smithsons-logistics; verify admin-only read-only January state and source statuses; retain all originals. No migration, workbook replacement or frontend deployment. Administrator review/confirmation remains separate. Roll back the backend to 653abb7cea4d5103d7f2bbc503af47bcbc7bda1c if needed, without deleting any append-only drafts or financial records.

## Month-loading improvement in the approved follow-up

The monthly view repeatedly opened the same raw workbook during global/per-truck validation, report rebuilding and confirmation-state presentation. It also fetched the same immutable archived bytes repeatedly. This work scales with truck count even though the source file is identical.

`services/monthly_reporting_scope.py` adds request-local reuse (ContextVar cleared in finally) only for pure raw-workbook parsing and immutable archive lookups. `routers/monthly_payouts.py` wraps its read presentation in that scope. `inspect_source` and the complete charge scan each execute once per unique content/reporting-month within that request; per-truck issue filtering still runs. `monthly_files.get` reuses immutable source bytes only for that same connection/archive ID within that request. Returned objects are deep-copied so callers cannot corrupt cached validation inputs.

No financial result, live DHL rows, authorization result, source fingerprint, administrator decision or confirmation is cached. Every new request starts empty; confirmation endpoints remain outside this read-view scope and revalidate normally. Changed workbook bytes and reporting months are separate keys. Strict dates/duplicates/amounts and negative-balance behavior are unchanged.

Added `tests/test_monthly_reporting_scope.py` for bounded file-open counts, cross-request/exception cleanup, mutation isolation, and fresh validation of changed live amounts/different years. The actual-January PostgreSQL/API benchmark compares full responses with reuse disabled/enabled and asserts identical JSON and unchanged underlying legacy records; avoids flaky timing assertions by verifying workbook-open counts.

The approved release manifest is nine backend files: the monthly-payout router, monthly_expense_dates, monthly_files, monthly_payouts, monthly_reporting_scope, the source-alias tests, reporting-scope tests, monthly-payout tests, and this review. Exclude all unrelated fleet/notification edits, actual workbooks, local fixtures, output and credentials. No frontend commit or migration is needed. Deployment/acceptance results and exact SHA are reported separately.

### Loading benchmark and deployment readiness

Actual January workbook in disposable PostgreSQL/API, 32 visible trucks and 747 source rows: **28.235s → 0.564s**, raw workbook opens **265 → 2**; complete JSON responses identical and underlying historical/operational fixture records unchanged. These are local measurements, not a production latency guarantee. **192 backend tests passed** in 76.897 seconds, including this benchmark and all source/financial safety regressions. Final browser/build results follow in the deployment report.

Final clean release-only verification: **192 backend tests, all 42 frontend checks (zero skipped), production build passed**. The nine-file staged source manifest matches the isolated tested code; secret-pattern/whitespace scans passed. No schema, financial calculator, PDF renderer, frontend source, workbook or unrelated notification change is included. Execution is authorized by the administrator’s request to deploy the January fix and improve month loading. Read-only production acceptance must confirm the exact Render SHA Live, January/February opening behavior, preserved source warnings and absence of unexpected errors; do not save drafts, approve trucks or issue PDFs during verification.
