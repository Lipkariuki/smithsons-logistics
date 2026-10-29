# February revenue evidence attachment — local verification handoff

Implemented locally on top of the pending Saved Monthly Files change. Local release commits are authorized; see `saved-files-release-readiness.md` for final verification and production execution gates. No production migration, financial write, confirmation, push or deployment has been performed.

## Diagnosis and evidence

February's parsed revenue is stored in `dhl_orders`, the same source used by existing DHL reporting and monthly financial snapshots. Previous read-only production inspection found 436 February records with gross KES 9,858,161.63. The saved 32-truck expense draft retains its Net workbook but lacks source-completeness attestation and raw date evidence. Thus its gross snapshots are NULL/incomplete, rather than proof that revenue is absent. The existing expense workbook can be reused through `/expense-imports/{id}/revise` without a new file upload.

Local inspection of `data/FEBRUARY 2026 TRIPS SUMMARY.xlsx` found 436 February date/plate/reference groups with DIST + Offloading KES 9,858,161.63. Count and gross agree with the prior production summary. This is not a claim that an unprovided corrected original was inspected, or that every production row has now been certified: the attachment workflow performs the exact comparison against the current ledger.

The local original also contains six historical transactions, all excluded from the in-period totals by the strict inspector and still unresolved:

| Excel row | Original date | Truck | Reference | Amount |
| --- | --- | --- | --- | ---: |
| 850 | 2024-05-27 | KDB924H | 615391 | -78,305.40 |
| 851 | 2025-03-26 | KAY025L | 118741043 | 15,704.85 |
| 852 | 2025-03-26 | KDG264X | 118729429 | 42,026.67 |
| 853 | 2025-05-19 | KCX114D | 0-661578 | 66,091.45 |
| 854 | 2025-10-06 | KDL090S | 667309 | 9,167.67 |
| 855 | 2025-10-06 | KDL090S | 667309 | 600.00 |

Attaching that file does not approve the historical entries. Existing explicit, reasoned historical exclusion review remains available; missing/invalid dates cannot be guessed. A corrected evidence workbook must genuinely match saved February transactions. A correction to an actual February reference, plate, date or amount that disagrees with the ledger will be flagged, not used to replace the ledger or bypass historical payslip protection.

## Minimal change

The pending migration 005 already provides immutable, private, versioned workbook storage. No extra table, column or migration beyond 005 is needed. Expense originals and immutable statements retain their existing storage.

The existing attachment endpoint `/dhl-reports/monthly-files/dhl` only inserts archived evidence. It never invokes the DHL importer, replacement deletion, manual payslip logic or financial confirmation. It now returns a read-only verification result. File history also exposes the comparison, and the new admin-only GET `/dhl-reports/monthly-files/raw/{id}/verification` reruns it against the current ledger.

Comparison uses the existing strict source inspector and validator, with diagnostic details added:

- Both year and month are checked; invalid/out-of-period rows show Excel row, original date, plate, reference and amount.
- Date/normalized-plate/reference groups compare DIST and Offloading separately, not just grand totals. This matches the persisted import granularity: a single saved row can represent multiple workbook charge lines. The original lines remain in the archived bytes.
- Missing workbook groups, missing saved groups and charge differences are shown separately. Equal totals cannot conceal a moved reference, changed plate or offsetting DIST/Offloading discrepancy.
- Stored total revenue must equal its DIST + Offloading. Admin never reduces gross and is not an expense input.
- Workbook and saved DIST, Offloading and gross totals are displayed. Verification output includes the current source fingerprint; stale results are not persisted as approvals.
- A match is labelled **matched, pending administrator review**, not automatically verified. Source-completeness attestation is still explicit, with an audit reason, in a new financial draft.

When building a new report from archived evidence, a truck with unresolved source/date/manifest discrepancies keeps incomplete revenue and unavailable gross. A textual completeness claim cannot override those discrepancies. Validation is truck-scoped, so another truck's unresolved entry does not by itself block an eligible truck. Whole-month confirmation retains its stricter global checks. No frozen draft/report is recalculated in place, and confirmed snapshots/PDFs remain unchanged.

## Administrator controls

Saved Monthly Files now explicitly distinguishes:

1. **Upload new DHL month**: import revenue when no records exist.
2. **Attach original workbook to verify existing DHL records**: retain evidence for existing revenue without replacing it. This is February's intended action.
3. **Attach corrected evidence workbook (new source version)**: preserve the earlier original and correction reason; still no revenue replacement.
4. **Replace existing DHL records from this file (historical payslip protection applies)**: a separate explicit action, shown for ledger mismatches. It uses the existing protected uploader and may return HTTP 409. It is not a remedy for February's missing evidence.

After attachment, use **Review verification / reuse saved expenses**, explicitly review completeness and source warnings, update the server preview and save a new draft. The saved Net file is reused automatically. Calculations use saved DHL gross and that workbook's approved expenses, with Decimal rounding and the unchanged positive-base 7% commission formula. Confirm only independently eligible trucks after business review. No automatic February approval is part of this release.

## Verification and release

Focused additions cover attachment with historical manual payslips unchanged, original Net reuse with gross 1000.00 / expenses 200.00 / commission 56.00 / net 744.00, equal-total component mismatches, wrong references/plates, strict year checks, and audit-only Admin amounts. Real-browser coverage checks that attaching to an existing ledger calls only the evidence endpoint and never `/dhl-reports/upload`.

Results: the full 158-test backend regression run passed. Following the addition of the final unrelated-truck date case and verification-endpoint permission checks, all 15 focused evidence/storage tests passed. All 43 frontend tests passed with no skips, including real browser/API/PostgreSQL scenarios; production build and both repositories' whitespace checks passed. The final focused case confirms an eligible truck while leaving another truck's historical date unresolved. Tests used only disposable local PostgreSQL and synthetic accounts; external delivery was blocked.

See `docs/saved-monthly-files.md` for storage evaluation, migration runner, full file manifest and rollback. This extension modifies `services/monthly_files.py`, `routers/monthly_files.py`, `services/monthly_expense_persistence.py`, the Saved Monthly Files component and its tests. The manual-payslip HTTP 409 guard and legacy importer are not weakened.

Production requires separate approval: fresh target/backup verification; apply reviewed additive 005 transactionally; verify existing data/counts; deploy backend; deploy frontend; perform read-only smoke checks. Only afterward, with separate authorization for real financial workflow actions, attach February evidence and prepare a new draft using saved expenses. Do not replace February DHL data or automatically confirm it. Leave the unused Render backend untouched.
