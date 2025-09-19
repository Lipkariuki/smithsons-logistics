from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from database import Base, engine
from sqlalchemy import text
from routers import (
    auth,
    users,
    vehicles,
    orders,
    trips,
    expenses,
    commissions,
    admin,
    driver_trips,
    partner_dashboard,
    partner_orders,
    driver_expense,
    rates,
    metadata
)
from dotenv import load_dotenv
import os
import re

# ✅ Load environment variables
load_dotenv()

app = FastAPI()

# ✅ CORS setup — configurable via env, with safe defaults
# - CORS_ORIGINS: comma-separated list (exact origins)
# - CORS_ORIGIN_REGEX: optional regex to allow a domain family (e.g., subdomains)
default_origins = [
    "http://localhost:5173",
    "https://smithsons-logistics-frontend.onrender.com",
    "https://www.smithsons.co.ke",
    "https://smithsons.co.ke",
]
env_origins = os.getenv("CORS_ORIGINS", "").strip()
allow_origins = [o.strip() for o in env_origins.split(",") if o.strip()] or default_origins

allow_origin_regex = os.getenv(
    "CORS_ORIGIN_REGEX",
    r"^https?:\/\/([a-z0-9-]+\.)*smithsons\.co\.ke$",
).strip()

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_origin_regex=allow_origin_regex if allow_origin_regex else None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Include all routers BEFORE static files
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(vehicles.router)
app.include_router(orders.router)
app.include_router(trips.router)
app.include_router(expenses.router)
app.include_router(commissions.router)
app.include_router(admin.router)
app.include_router(partner_dashboard.router)
app.include_router(partner_orders.router)
app.include_router(driver_trips.router)
app.include_router(rates.router, tags=["Rates"])
app.include_router(driver_expense.router)
app.include_router(metadata.router)

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    # One-time normalization: convert blank optional fields to NULL
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE orders
                SET invoice_number = NULL
                WHERE invoice_number IS NOT NULL AND TRIM(invoice_number) = '';
            """))
            conn.execute(text("""
                UPDATE orders
                SET purchase_order_number = NULL
                WHERE purchase_order_number IS NOT NULL AND TRIM(purchase_order_number) = '';
            """))
            conn.execute(text("""
                UPDATE orders
                SET dispatch_note_number = NULL
                WHERE dispatch_note_number IS NOT NULL AND TRIM(dispatch_note_number) = '';
            """))
            conn.execute(text("""
                UPDATE orders
                SET order_number = 'ORD-' || id
                WHERE TRIM(order_number) = ''
            """))
    except Exception:
        # Avoid blocking app startup if cleanup fails; logs are visible in platform
        pass

# ✅ Mount static files AFTER routers — prevents catch-all from hijacking API
if os.path.exists("dist"):
    app.mount("/", StaticFiles(directory="dist", html=True), name="static")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        return FileResponse("dist/index.html")
