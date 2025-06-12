from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from datetime import datetime
from database import get_db
from models import User, Trip, Vehicle, Order, Expense, Commission
from routers.auth import get_current_user  # ✅ import auth helper

router = APIRouter(prefix="/partner-dashboard", tags=["Partner Dashboard"])

@router.get("/")
def get_partner_dashboard_data(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),  # ✅ extract UID from token
):
    owner_id = current_user.id

    total_revenue = db.query(func.sum(Order.total_amount))\
        .join(Trip).join(Vehicle)\
        .filter(Vehicle.owner_id == owner_id).scalar() or 0

    now = datetime.now()
    month_revenue = db.query(func.sum(Order.total_amount))\
        .join(Trip).join(Vehicle)\
        .filter(Vehicle.owner_id == owner_id)\
        .filter(extract("month", Order.date) == now.month).scalar() or 0

    pending = db.query(func.sum(Order.total_amount))\
        .join(Trip).join(Vehicle)\
        .filter(Vehicle.owner_id == owner_id)\
        .filter(Order.dispatch_note == None).scalar() or 0

    expenses_total = db.query(func.sum(Expense.amount))\
        .join(Trip).join(Vehicle)\
        .filter(Vehicle.owner_id == owner_id).scalar() or 0

    commission_total = db.query(func.sum(Commission.amount_paid))\
        .join(Trip).join(Vehicle)\
        .filter(Vehicle.owner_id == owner_id).scalar() or 0

    net_earnings = total_revenue - expenses_total - commission_total

    trips_completed = db.query(Trip).join(Vehicle)\
        .filter(Vehicle.owner_id == owner_id, Trip.status == "completed").count()

    trips_ongoing = db.query(Trip).join(Vehicle)\
        .filter(Vehicle.owner_id == owner_id, Trip.status == "started").count()

    idle_vehicles = db.query(Vehicle).filter(
        Vehicle.owner_id == owner_id
    ).filter(~Vehicle.trips.any(Trip.status == "started")).count()

    revenue_trend = db.query(
        extract("month", Order.date).label("month"),
        func.sum(Order.total_amount).label("revenue")
    ).join(Trip).join(Vehicle)\
    .filter(Vehicle.owner_id == owner_id)\
    .group_by("month").order_by("month").all()

    trend = [
        {"month": f"{int(month):02d}", "revenue": int(revenue)}
        for month, revenue in revenue_trend
    ]

    drivers = db.query(User.id, User.name, func.count(Trip.id).label("trips"))\
        .join(Trip, Trip.driver_id == User.id)\
        .join(Vehicle, Trip.vehicle_id == Vehicle.id)\
        .filter(Vehicle.owner_id == owner_id)\
        .group_by(User.id, User.name).all()

    driver_data = [
        {"id": d.id, "name": d.name, "trips": d.trips}
        for d in drivers
    ]

    return {
        "totalRevenue": int(total_revenue),
        "monthRevenue": int(month_revenue),
        "pending": int(pending),
        "netEarnings": int(net_earnings),
        "expensesTotal": int(expenses_total),
        "commissionTotal": int(commission_total),
        "tripsCompleted": trips_completed,
        "tripsOngoing": trips_ongoing,
        "idleVehicles": idle_vehicles,
        "revenueTrend": trend,
        "drivers": driver_data
    }
