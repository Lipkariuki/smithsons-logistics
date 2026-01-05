# AI Assistant Guidance for Smithsons Logistics

This repository is a Python FastAPI backend serving a single-page frontend (if built into `dist`). The guidance below highlights architecture, conventions, and practical examples to help AI coding agents be immediately productive.

1. Quick architecture overview
- **Framework:** FastAPI app defined in `main.py` (routers registered, CORS configured, static SPA mounted if `dist/` exists).
- **DB:** SQLAlchemy ORM in `database.py` with `Base`, `engine`, and `get_db()` session factory. The repo currently contains a hard-coded Railway Postgres URL in `database.py` (check before edits).
- **Models & Schemas:** Domain models live in `models.py` (SQLAlchemy); API shapes in `schemas.py` (Pydantic v2 with `ConfigDict(from_attributes=True)`).
- **Routers:** Each route group is a module in `routers/` (e.g., `routers/orders.py`). Routers are included in `main.py` before static file mounting.
- **Utilities & Services:** `utils/` holds helpers (e.g., `utils/rate_lookup.py`, `utils/sms.py`) and `services/` contains third-party client initialization (e.g., `services/africastalking_client.py`).

2. Important runtime & deployment patterns
- Start locally: `./start.sh` (runs `uvicorn main:app --host=0.0.0.0 --port=10000`). The `Procfile` expects `uvicorn main:app --host 0.0.0.0 --port 8000` for platform deploys.
- Environment: `python-dotenv` is used in `main.py` to load `.env`. Check `CORS_ORIGINS` and `CORS_ORIGIN_REGEX` env vars for CORS behavior.
- DB schema management: There is no Alembic; schema is created via `Base.metadata.create_all(bind=engine)` on startup. There are also idempotent SQL normalization steps executed at startup—avoid removing them.
- Static SPA: `dist/` is mounted after routers; ensure API routes are registered before mounting to avoid routing conflicts.

3. Project-specific conventions and gotchas (do not change lightly)
- Empty-string normalization: The code consistently maps empty strings to `NULL` (see startup SQL in `main.py` and `routers/orders.py` normalization helpers). Preserve this behavior when editing APIs or migrations.
- Billing semantics in `orders`: `cases` is used as Offloading Charges (KES) and `price_per_case` as Mileage Charge (KES) — these are domain semantics common across `routers/orders.py` and frontend expectations.
- Auto-trip creation: Creating an `Order` auto-creates a `Trip` (see `routers/orders.py`). Changing this flow affects many downstream calculations.
- Rate lookup: `utils/rate_lookup.py` reads `data/rate_card.csv` and expects specific column renaming and uppercase/trimming. Lookups require exact `DESTINATION` + `TRUCK SIZE` match; handle missing-rates gracefully.
- SMS flow: SMS is sent via `utils.sms.send_sms` which uses `services/africastalking_client.py`. Credentials are present in the repo; treat them as sensitive and avoid leaking or committing changes that expose keys.

4. Where to look for common tasks (examples)
- To add a new API: add a router in `routers/`, import and `app.include_router(...)` in `main.py`.
- To change DB connection: update `database.py` (prefer using an env var instead of the hard-coded URL).
- To debug rate lookups: inspect `utils/rate_lookup.py` and `data/rate_card.csv`; logs in the function print current lookup inputs and columns.
- To trace SMS issues: check `routers/orders.py` message construction, `utils/sms.py`, and `services/africastalking_client.py`.

5. Testing / running notes
- No test suite is present. For manual checks run the server and use curl/Postman against endpoints in `routers/` (e.g., `POST /orders/`).
- Local run (dev):
  - `./start.sh` (uses port 10000)
  - or `uvicorn main:app --reload --host 0.0.0.0 --port 10000`
- Deployment: platform uses `Procfile` entry `web: uvicorn main:app --host 0.0.0.0 --port 8000`.

6. Security & maintenance flags (discovered)
- `services/africastalking_client.py` and `database.py` contain plaintext credentials/connection strings in the repository — treat as sensitive. Prefer moving to env vars and updating references in code.
- `engine = create_engine(..., echo=True)` in `database.py` enables SQL logging; it's useful for debugging but noisy in production.

7. Helpful code pointers (quick links)
- App entry: `main.py` — CORS, routers, startup SQL, static mounting
- DB layer: `database.py` — engine, SessionLocal, `get_db()`
- Domain models: `models.py` — SQLAlchemy models and relationships
- API schemas: `schemas.py` — Pydantic models used for response validation
- Orders flow: `routers/orders.py` — normalization, rate lookup, trip creation, SMS
- Rate logic: `utils/rate_lookup.py` and `data/rate_card.csv`
- SMS client: `services/africastalking_client.py`

If any part is unclear or you want the instructions to emphasize additional workflows (e.g., running migrations locally, adding tests, or frontend build steps), tell me which areas to expand and I will iterate.
