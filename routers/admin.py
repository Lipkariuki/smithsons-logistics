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
    db: Session = Depends(get_db)
):
    query = (
        db.query(
            Order.id,
            Order.order_number,  # ✅
            Order.invoice_number,
            Order.product_description,
            Order.destination,
            User.name.label("driver_name"),
            Order.total_amount,
            func.coalesce(func.sum(Expense.amount), 0).label("expenses"),
            func.coalesce(Commission.amount_paid, 0).label("commission"),
            Trip.id.label("trip_id"),
            Trip.vehicle_id,
            Vehicle.plate_number.label("truck_plate")
        )
        .outerjoin(Trip, Trip.order_id == Order.id)
        .outerjoin(User, User.id == Trip.driver_id)
        .outerjoin(Expense, Expense.trip_id == Trip.id)
        .outerjoin(Commission, Commission.trip_id == Trip.id)
        .outerjoin(Vehicle, Vehicle.id == Trip.vehicle_id)
    )

    if month:
        query = query.filter(func.extract("month", Order.date) == month)

    results = query.group_by(
        Order.id,
        Order.order_number,  # ✅
        Order.invoice_number,
        Order.product_description,
        Order.destination,
        Order.total_amount,
        User.name,
        Commission.amount_paid,
        Trip.id,
        Trip.vehicle_id,
        Vehicle.plate_number
    ).all()

    admin_orders = []
    for row in results:
        revenue = row.total_amount - (row.expenses + row.commission)
        admin_orders.append(AdminOrderOut(
            id=row.id,
            order_number=row.order_number,  # ✅
            invoice_number=row.invoice_number,
            product_description=row.product_description,
            destination=row.destination,
            driver_name=row.driver_name or "Unassigned",
            total_amount=row.total_amount,
            expenses=row.expenses,
            commission=row.commission,
            revenue=revenue,
            trip_id=row.trip_id,
            truck_plate=row.truck_plate,
        ))

    return admin_orders
