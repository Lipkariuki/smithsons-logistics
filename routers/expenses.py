from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import Expense
from schemas import ExpenseCreate, ExpenseOut

router = APIRouter(prefix="/expenses", tags=["Expenses"])

@router.post("/", response_model=ExpenseOut)
def create_expense(expense: ExpenseCreate, db: Session = Depends(get_db)):
    db_expense = Expense(**expense.dict())
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

        results.append({
            "id": exp.id,
            "trip_id": exp.trip_id,
            "vehicle_plate": vehicle_plate,
            "destination": destination,
            "amount": exp.amount,
            "description": exp.description,
            "timestamp": exp.timestamp.isoformat() if exp.timestamp else None,
        })

    return results
