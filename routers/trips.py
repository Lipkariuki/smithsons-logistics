from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models import Trip, Vehicle, Order, User, Expense, FuelExpense
from schemas import (
    TripCreate,
    TripOut,
    TripWithExpensesOut,
    FuelExpenseCreate,
    FuelExpenseUpdate,
    FuelExpenseOut,
    TripRevenueUpdate,
    TripRevenueOut,
)
from typing import List
from utils.rate_lookup import get_rate
from routers.auth import require_role

router = APIRouter(prefix="/trips", tags=["Trips"])

@router.post("/", response_model=TripOut)
def create_trip(trip: TripCreate, db: Session = Depends(get_db)):
    vehicle = db.query(Vehicle).filter(Vehicle.id == trip.vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")

    order = db.query(Order).filter(Order.id == trip.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    driver = db.query(User).filter(User.id == trip.driver_id, User.role == "driver").first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")

    rate = get_rate(
        destination=order.destination,
        truck_size=vehicle.size or "",
        product_type=order.product_type or ""
    )

    db_trip = Trip(
        vehicle_id=trip.vehicle_id,
        driver_id=trip.driver_id,
        order_id=trip.order_id,
        dispatch_note=trip.dispatch_note,
        status=trip.status or "started",
        reimbursement_status=trip.reimbursement_status or "unpaid",
        revenue=rate
    )

    db.add(db_trip)
    db.commit()
    db.refresh(db_trip)
    return db_trip

@router.get("/", response_model=List[TripOut])
def list_trips(db: Session = Depends(get_db)):
    trips = db.query(Trip).options(
        joinedload(Trip.driver),
        joinedload(Trip.vehicle),
        joinedload(Trip.order)
    ).all()

    result = []
    for trip in trips:
        result.append({
            "id": trip.id,
            "status": trip.status,
            "reimbursement_status": trip.reimbursement_status,
            "dispatch_note": trip.dispatch_note,
            "vehicle_plate": trip.vehicle.plate_number if trip.vehicle else None,
            "driver_name": trip.driver.name if trip.driver else None,
            "destination": trip.order.destination if trip.order else None,
            "order_number": trip.order.order_number if trip.order else None,  # ✅ added here
            "created_at": trip.created_at,
        })

    return result


def _get_trip_or_404(db: Session, trip_id: int) -> Trip:
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")
    return trip


def _update_trip_revenue_value(
    db: Session, trip_id: int, payload: TripRevenueUpdate
) -> TripRevenueOut:
    trip = _get_trip_or_404(db, trip_id)
    try:
        trip.revenue = float(payload.revenue)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid revenue value")
    db.commit()
    db.refresh(trip)
    return TripRevenueOut(trip_id=trip.id, revenue=trip.revenue)


@router.patch(
    "/{trip_id}/revenue",
    response_model=TripRevenueOut,
    tags=["Trips"],
)
def patch_trip_revenue(
    trip_id: int,
    payload: TripRevenueUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return _update_trip_revenue_value(db, trip_id, payload)


@router.put(
    "/{trip_id}/revenue",
    response_model=TripRevenueOut,
    tags=["Trips"],
)
def put_trip_revenue(
    trip_id: int,
    payload: TripRevenueUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    return _update_trip_revenue_value(db, trip_id, payload)


@router.get(
    "/{trip_id}/fuel",
    response_model=FuelExpenseOut,
    tags=["Trips"],
)
def get_trip_fuel(
    trip_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    _get_trip_or_404(db, trip_id)
    fuel = db.query(FuelExpense).filter(FuelExpense.trip_id == trip_id).first()
    if not fuel:
        raise HTTPException(status_code=404, detail="Fuel expense not found for this trip.")
    return fuel


@router.post(
    "/{trip_id}/fuel",
    response_model=FuelExpenseOut,
    tags=["Trips"],
)
def upsert_trip_fuel(
    trip_id: int,
    payload: FuelExpenseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    _get_trip_or_404(db, trip_id)
    fuel = db.query(FuelExpense).filter(FuelExpense.trip_id == trip_id).first()
    if fuel:
        fuel.fuel_type = payload.fuel_type
        fuel.price_per_litre = payload.price_per_litre
        fuel.amount = payload.amount
        fuel.litres = payload.litres
        fuel.updated_by = current_user.id
    else:
        fuel = FuelExpense(
            trip_id=trip_id,
            fuel_type=payload.fuel_type,
            price_per_litre=payload.price_per_litre,
            amount=payload.amount,
            litres=payload.litres,
            updated_by=current_user.id,
        )
        db.add(fuel)
    db.commit()
    db.refresh(fuel)
    return fuel


@router.put(
    "/{trip_id}/fuel",
    response_model=FuelExpenseOut,
    tags=["Trips"],
)
def update_trip_fuel(
    trip_id: int,
    payload: FuelExpenseUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    _get_trip_or_404(db, trip_id)
    fuel = db.query(FuelExpense).filter(FuelExpense.trip_id == trip_id).first()
    if not fuel:
        raise HTTPException(status_code=404, detail="Fuel expense not found for this trip.")

    if payload.fuel_type is not None:
        fuel.fuel_type = payload.fuel_type
    if payload.price_per_litre is not None:
        fuel.price_per_litre = payload.price_per_litre
    if payload.amount is not None:
        fuel.amount = payload.amount
    if payload.litres is not None:
        fuel.litres = payload.litres
    fuel.updated_by = current_user.id
    db.commit()
    db.refresh(fuel)
    return fuel


@router.delete(
    "/{trip_id}/fuel",
    status_code=204,
    tags=["Trips"],
)
def delete_trip_fuel(
    trip_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    _get_trip_or_404(db, trip_id)
    fuel = db.query(FuelExpense).filter(FuelExpense.trip_id == trip_id).first()
    if not fuel:
        raise HTTPException(status_code=404, detail="Fuel expense not found for this trip.")
    db.delete(fuel)
    db.commit()

@router.get("/{trip_id}/with-expenses", response_model=TripWithExpensesOut)
def get_trip_with_expenses(trip_id: int, db: Session = Depends(get_db)):
    trip = db.query(Trip)\
        .options(
            joinedload(Trip.vehicle),
            joinedload(Trip.driver),
            joinedload(Trip.expenses)
        ).filter(Trip.id == trip_id).first()

    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found.")

    vehicle = trip.vehicle
    driver = trip.driver
    expenses = [exp for exp in trip.expenses if not getattr(exp, "is_deleted", False)]
    total_expense = sum(e.amount for e in expenses)

    return {
        "id": trip.id,
        "status": trip.status,
        "reimbursement_status": trip.reimbursement_status,
        "dispatch_note": trip.dispatch_note,
        "vehicle_id": trip.vehicle_id,
        "driver_id": trip.driver_id,
        "vehicle_plate": vehicle.plate_number if vehicle else None,
        "driver_name": driver.name if driver else None,
        "expenses": expenses,
        "total_expenses": total_expense
    }


@router.get("/expenses-summary")
def get_expenses_summary(db: Session = Depends(get_db)):
    """
    Return a lightweight mapping of trip_id -> total_expenses for all trips,
    computed with a single grouped query. This avoids N per-trip requests.
    """
    rows = (
        db.query(Expense.trip_id, func.coalesce(func.sum(Expense.amount), 0))
        .group_by(Expense.trip_id)
        .all()
    )
    return {int(trip_id): float(total or 0) for trip_id, total in rows}

@router.get("/{trip_id}/profit")
def get_trip_profit(trip_id: int, db: Session = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip or not trip.order:
        raise HTTPException(status_code=404, detail="Trip or order not found.")

    order = trip.order
    expenses = [exp for exp in trip.expenses if not getattr(exp, "is_deleted", False)]
    commission = trip.commission

    total_expenses = sum(e.amount for e in expenses)
    commission_amount = commission.amount_paid if commission else 0.0
    revenue = trip.revenue or 0.0
    fuel = db.query(FuelExpense).filter(FuelExpense.trip_id == trip.id).first()
    fuel_amount = fuel.amount if fuel else 0.0

    net_profit = revenue - total_expenses - commission_amount - fuel_amount

    return {
        "trip_id": trip.id,
        "revenue": revenue,
        "total_expenses": total_expenses,
        "commission_paid": commission_amount,
        "fuel_expense": fuel_amount,
        "net_profit": net_profit
    }
