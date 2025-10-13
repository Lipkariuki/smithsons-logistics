# Updated FastAPI Admin Route to Use Trip.revenue Instead of Order.total_amount
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from database import get_db
from models import Order, Trip, User, Expense, Commission, Vehicle
from schemas import AdminOrderOut
from typing import Optional, List

router = APIRouter(prefix="/admin", tags=["Admin"])

@router.get("/orders", response_model=List[AdminOrderOut])
def get_admin_orders(
    month: Optional[int] = Query(None),
    search: Optional[str] = Query(None, description="Filter by order_number, invoice_number, or destination (ILIKE)"),
    limit: Optional[int] = Query(50, ge=1, le=200, description="Max results when using search"),
    db: Session = Depends(get_db)
):
    # Subqueries to avoid row-multiplication when joining expenses and commission
    expenses_sq = (
        db.query(Expense.trip_id.label("trip_id"), func.coalesce(func.sum(Expense.amount), 0).label("expenses_sum"))
        .group_by(Expense.trip_id)
        .subquery()
    )
    commissions_sq = (
        db.query(Commission.trip_id.label("trip_id"), func.coalesce(func.sum(Commission.amount_paid), 0).label("commission_sum"))
        .group_by(Commission.trip_id)
        .subquery()
    )

    query = (
        db.query(
            Order.id,
            Order.order_number,
            Order.invoice_number,
            Order.date,
            Order.product_description,
            Order.destination,
            Order.fuel_litres,
            Order.driver_details,
            User.name.label("driver_name"),
            Trip.driver_id,
            Trip.revenue.label("trip_revenue"),
            func.coalesce(expenses_sq.c.expenses_sum, 0).label("expenses"),
            func.coalesce(commissions_sq.c.commission_sum, 0).label("commission"),
            Trip.id.label("trip_id"),
            Trip.vehicle_id,
            Vehicle.plate_number.label("truck_plate"),
            Vehicle.owner_id,
        )
        .outerjoin(Trip, Trip.order_id == Order.id)
        .outerjoin(User, User.id == Trip.driver_id)
        .outerjoin(expenses_sq, expenses_sq.c.trip_id == Trip.id)
        .outerjoin(commissions_sq, commissions_sq.c.trip_id == Trip.id)
        .outerjoin(Vehicle, Vehicle.id == Trip.vehicle_id)
    )

    if month:
        query = query.filter(func.extract("month", Order.date) == month)

    if search:
        pattern = f"%{search}%"
        query = query.filter(
            (Order.order_number.ilike(pattern)) |
            (Order.invoice_number.ilike(pattern)) |
            (Order.destination.ilike(pattern))
        )

    query = query.group_by(
        Order.id,
        Order.order_number,
        Order.invoice_number,
        Order.date,
        Order.product_description,
        Order.destination,
        Order.fuel_litres,
        Order.driver_details,
        Trip.revenue,
        User.name,
        Trip.driver_id,
        Trip.id,
        Trip.vehicle_id,
        Vehicle.plate_number,
        Vehicle.owner_id,
        expenses_sq.c.expenses_sum,
        commissions_sq.c.commission_sum,
    )

    if search:
        query = query.order_by(Order.date.desc()).limit(limit)

    results = query.all()

    admin_orders = []
    for row in results:
        revenue = (row.trip_revenue or 0) - (row.expenses + row.commission)
        admin_orders.append(AdminOrderOut(
            id=row.id,
            order_number=row.order_number,
            invoice_number=row.invoice_number,
            date=row.date,
            product_description=row.product_description,
            destination=row.destination,
            driver_name=row.driver_name or "Unassigned",
            driver_id=row.driver_id,
            owner_id=row.owner_id,
            total_amount=row.trip_revenue or 0,
            expenses=row.expenses,
            commission=row.commission,
            revenue=revenue,
            trip_id=row.trip_id,
            truck_plate=row.truck_plate,
            fuel_litres=row.fuel_litres,
            driver_details=row.driver_details,
        ))

    return admin_orders
