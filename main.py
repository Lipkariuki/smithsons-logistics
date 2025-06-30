# backend/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from database import Base, engine
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
    allow_origins=origins,  # 👈 frontend URLs allowed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Include all routers
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

# ✅ Create tables on startup
@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

# ✅ Serve frontend from dist/
if os.path.exists("dist"):
    app.mount("/", StaticFiles(directory="dist", html=True), name="static")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        return FileResponse("dist/index.html")
