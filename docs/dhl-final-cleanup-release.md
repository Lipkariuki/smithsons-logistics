# Focused DHL cleanup release — 26 November 2026

## Production database gate completed

The private connection file contained three identical public PostgreSQL URLs concatenated together. It was corrected to one entry without changing credentials or provider settings. The target was verified by the established public endpoint, database identity, PostgreSQL 16 and the expected 22-table Smithsons application schema. Render management environment values could not be independently inspected; the operator's prior private confirmation remains the environment comparison evidence.

A fresh PostgreSQL custom archive (1,192,448 bytes) was created on 26 November at 15:38 EAT in the private backup directory outside Git. Its archive list was readable and all 22 tables' row hashes/counts matched after offline restore. The offline 007 → 008 rehearsal preserved all existing table data and PDF/workbook bytes.

Production 006 was present; 007 and 008 were absent. The operator explicitly approved 007 as the required prerequisite. Exact reviewed SQL 007 followed by 008 ran in ONE transaction with bounded locks/timeouts. Before commit, all 22 table row hashes/counts, columns, constraints and indexes were verified unchanged; both validation helpers and the current dispatcher were present. No financial approvals, payslips, uploads, SMS or data deletion occurred. Migration 008 is now installed; its UI warning remains a compatibility check and naturally disappears when the backend reports that guard present.

## Application scope

- Keep the single existing Reports → DHL Monthly Payouts page and its two saved workbook cards, four totals and truck table.
- Remove repeated filenames/row coordinates, previous-statement buttons, archive/version controls and unused experimental frontend components. Source diagnostics remain collapsed for administrators; material errors stay actionable.
- A complete saved source which reconciles to the ledger can substantiate zero activity for an expense-only truck. This is calculation evidence, not payout approval. Proof records the raw workbook hash and is re-established on every request. Missing files, unimported/contradictory source rows or unresolved dates do not prove zero. Other trucks' financial errors do not fabricate activity for an absent truck. Expenses and negative balances remain intact.
- Valid rows show View payslip; existing confirmations and PDFs are reused idempotently. Confirmation is still an explicit administrator action, independently per truck.
- Retire legacy manual DHL POST/PUT payslip operations with HTTP 410 and a link in wording to the supported workflow. Remove their unused manual-expense/revenue helpers. Historical read/download routes, SMS sending implementation and integrity constraints remain unchanged.
- Current financial formulas, per-DIST 5% fee, positive-base 7% commission, HALF_UP rounding and approved evidence-based 0.01/0.05/0.25 limits are unchanged.

## Verification

Actual August and September source tests preserve KAV086M August net KES 190,320.09 and KAY025L September net KES 101,630.52. Actual-workbook real browser → FastAPI → disposable PostgreSQL testing passes uploads, reopening, independent confirmation, PDF download, correction version and immutable prior bytes; removed previous-statement UI is absent. No production truck was confirmed.

Frontend: 22 unit tests, 20 browser tests and production build passed; existing large-chunk warning remains. Backend regression results are recorded in the final handoff. Stored manual PDF branding/read tests remain relevant and preserved despite retirement of manual writes. No authentication, SMS, fleet or general reporting redesign.

## Test-data reset is separate and pending approval

See `docs/dhl-test-data-cleanup-plan.md` for the exact eight-table, 259-record proposal and explicit operational exclusions. This inventory is local review material, not a release artifact. No deletion is authorized merely by merging this release. Do not drop tables, reset sequences, delete `dhl_orders`, reset Railway, or bypass integrity triggers globally.

## Deployment and rollback

1. Database prerequisites 007/008 are now complete; do not replay migrations at application startup.
2. Commit only approved backend application/test/document changes, push main, and wait for active Render `smithsons-logistics` to be Live. Read-only root/OpenAPI and protected monthly endpoints must pass.
3. Then push frontend main and verify Render `smithsons-logistics-frontend`, saved workbook cards, truck details and browser errors. Do not touch `smithsons-logistics-1` or redeploy Railway PostgreSQL.
4. Without provider management/admin access, Render Live status and authenticated production UI verification require operator confirmation; a Git push alone is not deployment verification.
5. On failure, stop. Roll application code back to backend `133f30d` and frontend `8df68e9` as needed, keeping compatible migration guards installed. Do not restore an old database over new activity. Do not delete any data or send SMS as a smoke test.
