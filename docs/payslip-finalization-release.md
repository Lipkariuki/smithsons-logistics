# Payslip source breakdown — local release preparation

Scope: only the previously prepared revenue-breakdown PDF, original expense descriptions, duplicate/ambiguous COST safeguards, independent truck confirmation and saved-workbook review guidance. No database migration, new endpoint, payment module, manual payslip rewrite or production operation is included.

Release bases: backend `b8a90229390a48cb4afe065d82d3906db9ea99c5`; frontend `7e0c3949e969d670eee4c4a73161d19843893d79`. The new commits are local only. A push to main may trigger Render deployment and requires separate authorization.

## Result and compatibility

- Renderer `smithsons-monthly-statement-v3-revenue-breakdown` adds Distribution Revenue and Offloading Revenue from the confirmed row's frozen source snapshot. Their sum must equal frozen gross; it never reads current trip/manual-payslip revenue.
- Original approved nonzero Net Summary descriptions and amounts are itemized without normalization/relabeling. Item sum must equal Total Expenses. Existing positive-base 7%, Decimal ROUND_HALF_UP, negative-balance and zero-commission rules remain unchanged.
- Existing stored PDFs are returned without regeneration. Confirmed source versions, predecessor links and correction adjustments remain immutable. No schema changes are needed.
- Repeated identical transport charges and ambiguous COST labels block new verification/confirmation. No automatic deletion or deduplication occurs; distinct charge lines remain valid. Unrelated truck findings do not block an eligible truck's independent confirmation.
- The existing Saved Monthly Files panel explains how to review retained evidence, enter a completeness attestation/review note and create a new draft without selecting either workbook again. No checkbox, approval or financial confirmation is performed automatically.
- The legacy importer, historical manual payslips and their replacement HTTP 409 protection are unchanged.

## KAV086M acceptance scenario

The new real-browser test uses synthetic XLSX files, synthetic owner/admin identities and disposable local PostgreSQL. KAV086M's verified numeric example is recreated as test data; this is not a real February approval.

The workflow uploads each file once, saves an unverified draft, logs out/in, reopens February 2026, rechecks retained evidence, creates reviewed draft version 2 without another file upload, confirms only KAV086M while PENDING999 remains unresolved, and generates/downloads the immutable PDF. It verifies all original nonzero expense labels, every financial figure, source month, plate, Smithsons branding and byte-identical re-download after reopening. The original draft's unavailable gross remains unchanged.

Expected KES figures: DIST 294,261.41 + Offloading 7,848.00 = gross 302,109.41. FUEL 141,386.00 + TELEMATICS & VSS 8,758.00 + SHUNTING 2,390.00 = expenses 152,534.00. Base 149,575.41; commission 10,470.28; net 139,105.13. Blank GPRS is audited as zero and omitted from nonzero expense items. Admin and bogus manual reference values never become deductions or revenue.

The test requires localhost frontend/backend, disposable PostgreSQL with migrations 001–005, existing synthetic authentication fixtures, `KAV_BROWSER_FIXTURE_JSON` marked `synthetic: true` containing month/raw/net test payloads, Playwright/Chrome and a Python PDF reader through `PDF_TEST_PYTHON`. No production credentials/workbooks are fixtures or release artifacts.

## Verification

- 74 focused backend tests passed: workbook calculations, charge validation, saved originals/revisions, independent confirmations, immutable statements and real HTTP legacy replacement protection.
- All 44 frontend tests passed with no skips, including the exact KAV086M saved-workbook/new-version/independent-confirmation/PDF workflow against the real local backend.
- Production build and whitespace checks passed.
- Test setup corrections only: a synthetic KAV vehicle ID was reserved separately from existing acceptance fixtures, and the browser test now explicitly answers the existing synthetic review-reason prompt. Neither required an application behavior change.
- Final visual inspection of the one-page synthetic KAV086M PDF passed: every source component, original expense description and amount is legible, with no clipped text or overlapping lines. Its nonzero item sum was independently checked as 152,534.00. Existing non-failing SVG gradient, bundle-size and Browserslist warnings remain.

Exact release paths and hashes are in `payslip-finalization-manifest.json`. Exclude unrelated fleet/insurance/SMS edits, actual workbooks, backups, configuration, generated outputs and the detailed real-financial audit report. Staged bytes must pass the known-secret and credential-pattern scan before either local commit is created.

## Future release and rollback — not executed

After separate approval, deploy only the reviewed backend commit, verify active Render `smithsons-logistics`, then deploy the reviewed frontend commit to `smithsons-logistics-frontend`. No migrations or environment changes are required; never touch `smithsons-logistics-1`. Verify read-only reports/history/authorization and existing PDFs. Any real truck confirmation or new payslip generation requires genuine administrator review and separate business authorization; do not use February as a write smoke test.

Rollback frontend to `7e0c3949e969d670eee4c4a73161d19843893d79`, then backend to `b8a90229390a48cb4afe065d82d3906db9ea99c5` if needed. Keep all archive/confirmation/PDF records intact; existing v3 PDF bytes remain downloadable because the storage format is unchanged. Do not rewrite historical figures or restore a stale database over new transactions.
