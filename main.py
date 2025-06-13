# backend/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
    partner_dashboard,
    partner_orders,
)
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

# CORS settings
origins = [
    "http://localhost:5173",  # for local frontend dev
    "https://smithsons-logistics-frontend-production.up.railway.app",  # deployed frontend
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
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

# Create all tables
@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
