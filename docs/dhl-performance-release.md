# DHL transfer and reporting performance — 26 November 2026

## Measured causes

The baseline is backend `b603fa8` and frontend `bc834c1`. Measurements used the actual supplied August/September workbooks, isolated PostgreSQL schemas, real local FastAPI HTTP and Chromium. Production financial records were not uploaded, changed or approved. The reference workbooks are untracked and excluded from release.

September has 508 charge rows. Its raw workbook is 80,597 bytes and its expense workbook 12,600 bytes; August's supplied raw workbook is 94,711 bytes with 647 dated charges. These are the largest supplied monthly cases, not a benchmark of the theoretical 20 MB limit.

Repeated workbook reads, full-month validation and large responses were the main local bottlenecks. An expense operation opened workbooks 361 times before optimization, versus 10 distinct reads after request-local reuse. Separate cached-value/formula and compatibility reads remain intentionally validated; no mutable openpyxl workbook is globally cached.

The previous monthly request ran 49 SQL queries and sent 363,371 bytes. The new normal overview ran 10 queries and sent 30,995 bytes. First PDF rendering was already fast (~0.11 s); the apparent long first-download delay was chiefly the preceding confirmation validation.

## Timings

Warm local disposable PostgreSQL service benchmark, same actual September source:

| Operation | Before | After |
|---|---:|---:|
| DHL source parse | 0.147 s | 0.182 s |
| Net Summary parse | 0.021 s | 0.020 s |
| Standalone source reconciliation | 1.345 s | 1.278 s |
| Raw archive persistence, including validation | 0.145 s | 0.146 s |
| Expense save/calculation | 43.003 s | 1.357 s |
| Monthly data API | 2.802 s | 0.032 s overview |
| Individual truck detail API | included in full response | 0.797 s unconfirmed |
| Truck confirmation | 47.932 s | 0.813 s |
| First PDF creation | 0.112 s | 0.113 s |
| Existing PDF prepare operation | 0.0065 s / 7 queries | 0.0046 s / 1 query |
| Stored PDF lookup | 0.0012 s | 0.0017 s |
| Local PDF HTTP transfer | 0.020 s | 0.007 s |

Real Chromium end-to-end measurements include rendering and browser automation overhead:

| Action | Before | Optimized release check |
|---|---:|---:|
| Raw upload/save action | 2.73 s | 2.56 s |
| Expense upload/save action | 50.47 s | 2.18 s |
| Reopen saved month, including page reload | 3.64 s | 0.31 s |
| Switch back to saved month | 2.80 s | 0.027 s within the 15-second display cache |
| First unconfirmed truck click | 0.14 s, details already prefetched | 1.40 s, fetched and revalidated on demand |
| Confirm plus first PDF download | 42.65 s | 1.98 s (1.07 s in an earlier run) |
| Existing PDF download action | 0.086 s | 0.087 s |

Optimized browser transfer tests deliberately added 0.6 s server delay on uploads to expose the processing state. A native XHR measurement reported the raw multipart transfer complete at 0.112 s (80,895 bytes including multipart framing), response complete at 1.297 s. The expense transfer reported complete at 0.107 s (13,010 bytes including framing), response complete at 1.603 s. These local transfer measurements are not claims about production bandwidth. SQL execution instrumentation in representative requests measured ~44 ms raw/~93 ms expense; parsing, reconciliation and persistence phase timings overlap and must not be added together.

## Changes

- Reuse pure parsed results only within one operation/request. Revalidate on new requests; mutation operations do not cache live financial decisions globally.
- Scope upload and confirmation processing so the same retained source is not reopened for every truck. Target confirmation validation to the selected truck while preserving complete header/date/duplicate validation and the same Decimal calculator.
- Add a small overview API, with expense detail/audit data fetched on truck review. Each overview checks live source fingerprints and versions. Changed or unresolved inputs use the authoritative existing preview path. Preview fallback reads only the latest file versions; historical APIs remain available.
- Client display cache is limited to 15 seconds/six months per mounted page, never shared between users. Uploads, category changes, corrections and confirmations invalidate it. Truck review is always a fresh server request; confirmation remains transactional and authoritative.
- Prevent duplicate clicks; identify identical current workbooks by SHA-256 before reupload, with a fresh overview check. For new DHL imports, reference the already-saved original rather than transferring its bytes a second time. Existing date/month checks and HTTP 409 manual-payslip protection remain in the guarded importer.
- Existing PDFs return directly from the immutable document row after SHA verification, without month locks, source workbooks or unrelated trucks. New PDFs use one truck's frozen snapshot, with existing concurrent generation guards. Stored response bytes, design and financial figures are unchanged.
- Real byte-based progress uses native upload/download counts. Transfer 100% changes to “Processing workbook…” until the server acknowledges saving. Preparing payslip and indeterminate states do not invent percentages. Controls recover after errors/cancellation, and cancellation explicitly warns that server processing may already have finished. First generation invalidates document metadata; stored downloads avoid the extra generation POST.
- Memoize the truck table so progress frames do not rerender every row. Cancel stale month/detail requests and show loading placeholders.
- Add parameter-free timing logs, request identifiers, SQL counts and Server-Timing. Failures display a safe correlation ID. Database failures log SQLSTATE/type, never SQL parameters, passwords, JWTs, workbook data or API keys. A repeated 503 must be correlated with those logs; it is not automatically attributed to another download.

## Tests and safety

All financial formulas and approved 0.01/0.05/0.25 evidence limits are unchanged. August KAV086M remains KES 190,320.09 net and September KAY025L remains KES 101,630.52. Real local browser tests uploaded/reopened both months and downloaded accurate PDFs; August's error-marked KDA267N remains unconfirmed.

Real slow-network tests observed actual download progress (5%), cancelled a PDF transfer, interrupted a multipart upload without storing a partial workbook, generated one PDF under two simultaneous requests and downloaded identical bytes concurrently. Another API read completed in 0.10–0.18 s while processing was still in flight. Final regression/build counts are recorded in the delivery report.

No production migration, financial write, deletion, SMS, credential update, dependency upgrade or Railway redeployment is part of this release. Authentication/origin rules are unchanged; CORS exposes only additional diagnostic/length headers needed by the browser.

## Limits and release verification

The first unconfirmed detail did not consistently meet the one-second end-to-end target (0.80–0.86 s server, ~1.40 s browser action). Strict source validation is retained. Already-confirmed details measured ~0.03 s server without workbook reads. Cold starts, actual Render compute allocation and authenticated production performance/logs were not directly accessible. A read-only SELECT 1 from this local machine to Railway measured ~298 ms median, plus ~2.76 s initial connection; that is not Render-to-Railway latency. No pool, worker count, region or timeout workaround was applied without evidence. The existing large frontend chunk warning remains.

Render supplies a public Git commit identifier at build/runtime ([official default variables](https://render.com/docs/environment-variables)). A validated SHA is returned in diagnostic response headers and frontend HTML metadata, allowing exact deployment checks without exposing credentials or adding a service.

Deploy backend first; verify the exact public release header, root/OpenAPI health and protected overview/detail/PDF endpoints. Then push frontend and verify its exact HTML release marker and asset response. Authenticated production admin workflow/log review remains operator-only if no session/management access is available. No financial write is a production smoke test.

Rollback application commits to backend `b603fa8` and frontend `bc834c1` if necessary. There is no migration to reverse, no data reset and no automatic database restore. Retain all saved financial history.

Reproduce current local service measurements with `MONTHLY_EXPENSE_TEST_URL` privately set to a disposable loopback `_test` database, then run `venv/bin/python scripts/benchmark_dhl_performance.py current`. Outputs stay private under `/private/tmp`.

Final checks: 257 backend tests executed, 243 passed and 14 optional-fixture tests skipped; no failures. The focused request-ID/SQLSTATE secrecy diagnostics also passed after the final logging adjustment. Frontend: 25 unit tests, 23 browser tests and production build passed. Both actual monthly workflows and native throttled-transfer/concurrency checks passed. The generated production HTML release marker was verified with a controlled test SHA.
