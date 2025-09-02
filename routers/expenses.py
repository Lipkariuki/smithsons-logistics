from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import Expense, Trip, Order
from schemas import ExpenseCreate, ExpenseOut

router = APIRouter(prefix="/expenses", tags=["Expenses"])

@router.post("/", response_model=ExpenseOut)
def create_expense(expense: ExpenseCreate, db: Session = Depends(get_db)):
    # Accept either trip_id or order_number; require at least one
    trip_id = expense.trip_id

    if not trip_id and expense.order_number:
        order = db.query(Order).filter(Order.order_number == expense.order_number).first()
        if not order:
            raise HTTPException(status_code=404, detail="Order not found for given order_number")
        trip = db.query(Trip).filter(Trip.order_id == order.id).first()
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found for the given order")
        trip_id = trip.id

    if not trip_id:
        raise HTTPException(status_code=400, detail="Provide trip_id or order_number")

    db_expense = Expense(trip_id=trip_id, amount=expense.amount, description=expense.description)
    db.add(db_expense)
    db.commit()
    db.refresh(db_expense)
    return db_expense

@router.get("/")
def get_expenses(db: Session = Depends(get_db)):
    expenses = db.query(Expense).all()
    results = []

    for exp in expenses:
        trip = exp.trip
        vehicle_plate = trip.vehicle.plate_number if trip and trip.vehicle else None
        destination = trip.order.destination if trip and trip.order else None
        if trip and trip.order:
            # Prefer explicit order_number; fall back to invoice or ORD-{id}
            order_number = trip.order.order_number or trip.order.invoice_number or f"ORD-{trip.order.id}"
        else:
            order_number = None

        results.append({
            "id": exp.id,
            "trip_id": exp.trip_id,
            "order_number": order_number,
            "vehicle_plate": vehicle_plate,
            "destination": destination,
            "amount": exp.amount,
            "description": exp.description,
            "timestamp": exp.timestamp.isoformat() if exp.timestamp else None,
        })

    return results
