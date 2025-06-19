# routers/driver_trips.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List

from database import get_db
from models import Trip, Expense, User
from schemas import TripOut, ExpenseOut, ExpenseCreate
from routers.auth import get_current_user

router = APIRouter(prefix="/driver", tags=["Driver Trips"])


@router.get("/trips", response_model=List[TripOut])
def get_my_trips(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "driver":
        raise HTTPException(status_code=403, detail="Only drivers can access this route.")

    trips = (
        db.query(Trip)
        .filter(Trip.driver_id == current_user.id)
        .options(
            joinedload(Trip.vehicle),
            joinedload(Trip.order)
        )
        .all()
    )

    return [{
        "id": trip.id,
        "status": trip.status,
        "reimbursement_status": trip.reimbursement_status,
        "dispatch_note": trip.dispatch_note,
        "vehicle_plate": trip.vehicle.plate_number if trip.vehicle else None,
        "driver_name": current_user.name,
        "destination": trip.order.destination if trip.order else None,
        "created_at": trip.created_at,
    } for trip in trips]

@router.get("/expenses", response_model=List[ExpenseOut])
def get_driver_expenses(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "driver":
        raise HTTPException(status_code=403, detail="Only drivers can access this route.")

    expenses = (
        db.query(Expense)
        .join(Trip)
        .options(
            joinedload(Expense.trip).joinedload(Trip.vehicle),
            joinedload(Expense.trip).joinedload(Trip.order),
        )
        .filter(Trip.driver_id == current_user.id)
        .all()
    )

    # Manually attach computed trip data
    for exp in expenses:
        if exp.trip:
            exp.trip.vehicle_plate = exp.trip.vehicle.plate_number if exp.trip.vehicle else None
            exp.trip.driver_name = current_user.name
            exp.trip.destination = exp.trip.order.destination if exp.trip.order else None

    return expenses



@router.post("/expenses", response_model=ExpenseOut)
def add_driver_expense(
    expense: ExpenseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "driver":
        raise HTTPException(status_code=403, detail="Only drivers can submit expenses.")

    # Check trip exists and belongs to driver
    trip = (
        db.query(Trip)
        .filter(Trip.id == expense.trip_id, Trip.driver_id == current_user.id)
        .first()
    )
    if not trip:
        raise HTTPException(status_code=400, detail="Trip not found or not assigned to this driver.")

    db_expense = Expense(**expense.dict())
    db.add(db_expense)
    db.commit()
    db.refresh(db_expense)
    return db_expense
