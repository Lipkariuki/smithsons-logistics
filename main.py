from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from database import Base, engine, SessionLocal
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

# ✅ Load environment variables
load_dotenv()

app = FastAPI()

# ✅ CORS setup — allow local + deployed frontend
origins = [
    "http://localhost:5173",
    "https://smithsons-logistics-frontend.onrender.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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

def _maybe_auto_migrate_and_normalize():
    do_migrate = os.getenv("AUTO_MIGRATE", "false").lower() in ("1", "true", "yes")
    if not do_migrate:
        return
    Base.metadata.create_all(bind=engine)
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


@app.on_event("startup")
def startup():
    # Try DB up to N times in case of cold start or brief outages
    retries = int(os.getenv("DB_CONNECT_RETRIES", "5"))
    delay = float(os.getenv("DB_CONNECT_BACKOFF", "1.5"))
    import time
    for i in range(retries):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            break
        except Exception as e:
            if i == retries - 1:
                # Re-raise on final attempt so platform logs show startup failure
                raise
            time.sleep(delay * (i + 1))
    try:
        _maybe_auto_migrate_and_normalize()
    except Exception:
        # Avoid blocking app if optional migration fails; logs visible in platform
        pass


@app.get("/healthz")
def healthz():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        from fastapi import Response
        return Response(content=f"db error: {e}", status_code=503)

# ✅ Mount static files AFTER routers — prevents catch-all from hijacking API
if os.path.exists("dist"):
    app.mount("/", StaticFiles(directory="dist", html=True), name="static")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        return FileResponse("dist/index.html")
