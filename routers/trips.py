from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.orm import Session, joinedload
from database import get_db
from models import Trip, Vehicle, Order, User
from schemas import TripCreate, TripOut, TripWithExpensesOut
from typing import List
from utils.rate_lookup import get_rate

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

    # ✅ Get rate based on destination, truck size, product type
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
        revenue=rate  # ✅ amount to be paid to truck owner
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
            "created_at": trip.created_at,
        })

    return result


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
    expenses = trip.expenses
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


@router.get("/{trip_id}/profit")
def get_trip_profit(trip_id: int, db: Session = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip or not trip.order:
        raise HTTPException(status_code=404, detail="Trip or order not found.")

    order = trip.order
    expenses = trip.expenses
    commission = trip.commission

    total_expenses = sum(e.amount for e in expenses)
    commission_amount = commission.amount_paid if commission else 0.0
    revenue = trip.revenue or 0.0  # ✅ use actual revenue saved in trip

    net_profit = revenue - total_expenses - commission_amount

    return {
        "trip_id": trip.id,
        "revenue": revenue,
        "total_expenses": total_expenses,
        "commission_paid": commission_amount,
        "net_profit": net_profit
    }
