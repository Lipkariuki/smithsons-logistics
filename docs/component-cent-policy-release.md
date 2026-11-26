# Approved one-cent source calculation policy — local preparation

Business approval: 23 November 2026. Use system AMOUNT + SURCHARGE rather
than a conflicting inclusive amount for DIST differences of exactly KES 0.01.
This is not permission to alter source workbooks, ledger records or confirmed
statements. Larger differences, Offloading differences, unknown charge types,
date problems and unverified activity remain blocking.

## Explicit saved-workbook review

The administrator selects **Use calculated totals for one-cent differences**.
This calls the existing monthly sync endpoint with
`accept_cent_differences: true`. It requires the current report/workbook IDs and
the installed 007 guard, and creates a new financial version with an audit reason.
GET/refresh never changes a saved report or enables the policy automatically.
The policy is carried forward only while the same raw workbook remains selected;
a different source requires a new explicit review.

Each frozen transport transaction retains `source_inclusive` and the signed
`source_adjustment`. Its calculated inclusive amount equals AMOUNT + SURCHARGE.
The existing `dhl_source_snapshot` remains the literal unmodified ledger snapshot.
The policy verifies the original source against that ledger before applying the
separate financial calculation. DIST admin remains 5%, rounded per row; Offloading
is exempt. Expenses and positive-base 7% commission rules are unchanged.

New policy: `monthly-expenses-v4-components-cent`; transport policy:
`dist-components-cent-v1`. Older policy dictionaries and confirmed PDFs remain
supported. No payment processing or automatic truck/month confirmation is added.

## Migration 007

`migrations/007_component_cent_policy.sql` creates one validation helper and
extends the existing administration-fee function with a policy branch. The legacy
function body is otherwise retained. No tables, columns, indexes or financial
records are changed. Existing whole-month and per-truck guards call that validator.
The helper checks explicit parent approval, signed one-cent adjustments and the
original ledger totals, then uses a validation-only typed copy to reuse the v1
identity, component and fee checks. That copy is never persisted.

The runner `scripts/migrate_component_cent_policy.py` does nothing without
`--apply`, refuses nonlocal targets without `--allow-nonlocal`, and uses one
transaction, advisory lock and statement/lock timeouts. Its private environment
variable is `DHL_COMPONENT_CENT_MIGRATION_URL`. Do not put a URL in documentation,
shell history, reports or Git.

## Controlled production sequence — separate approval required

1. Verify the active Render backend's Railway public database target privately.
2. Create a fresh production backup and restore-test it; check current schema and
   guard state. Do not redeploy Railway PostgreSQL or touch the unused Render service.
3. Apply 007 once transactionally using the reviewed runner. Compare existing
   records and PDF/workbook hashes before/after, and verify both functions.
4. Push/deploy the isolated backend release to Render `smithsons-logistics`.
   Verify Live status, protected routes and read-only saved-month retrieval.
5. Push/deploy the frontend release to `smithsons-logistics-frontend`. Verify
   review controls, source diagnostics and the absence of unexpected errors.
6. An administrator may subsequently select the new cent-policy review for the
   saved month. That saves a draft version only. Truck confirmation and PDF
   creation remain separate deliberate actions, outside deployment smoke tests.

Stop at any failure. A failed migration transaction rolls back both function
changes. Keep the additive 007 guard if application deployment fails. Before any
v4 reports have been saved, reverting to the preceding application commits leaves
old financial data unchanged. Once v4 reports/statements exist, retain v4-compatible
code/guards and use a forward fix; do not roll back to an implementation that cannot
read those snapshots, delete them, or restore an old backup over new financial work.

## September findings

Corrected raw workbook: `SEPTEMBER 2026 GROSS TOTALS (1).xlsx`.
There are 11 affected DIST rows across KAY025L, KBM439P, KBZ339V, KCE864K and
KDL090S. The signed gross difference is +KES 0.09 in total. Originals are retained.
Twelve expense-workbook trucks have no matching transport rows and still require
activity verification. Their expenses remain intact. Negative balances are retained.
The UI no longer offers no-business verification for trucks with existing source rows.

Local tests cover original/negative signed differences, larger and Offloading
rejections, row fee rounding, migration idempotency and atomic rollback, historic
PDF preservation, independent confirmations, whole-month confirmation, correction
audit history and SQL rejection of tampered adjustments.
