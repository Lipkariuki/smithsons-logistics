from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from database import get_db
from models import Expense, Trip, Order, Vehicle
from schemas import ExpenseCreate, ExpenseOut, ExpenseListResponse, ExpenseListItem

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


@router.patch("/{expense_id}", response_model=ExpenseOut)
def update_expense(expense_id: int, payload: dict, db: Session = Depends(get_db)):
    exp = db.query(Expense).filter(Expense.id == expense_id).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Expense not found")
    # Allowed fields: amount, description
    if "amount" in payload:
        try:
            exp.amount = float(payload["amount"]) if payload["amount"] is not None else exp.amount
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid amount")
    if "description" in payload:
        exp.description = payload["description"]
    db.commit()
    db.refresh(exp)
    return exp


@router.delete("/{expense_id}")
def delete_expense(expense_id: int, db: Session = Depends(get_db)):
    exp = db.query(Expense).filter(Expense.id == expense_id).first()
    if not exp:
        raise HTTPException(status_code=404, detail="Expense not found")
    db.delete(exp)
    db.commit()
    return {"status": "deleted"}

@router.get("/", response_model=ExpenseListResponse)
def get_expenses(
    page: int = 1,
    per_page: int = 25,
    db: Session = Depends(get_db),
):
    if page < 1:
        page = 1
    per_page = max(1, min(per_page, 100))
    offset = (page - 1) * per_page

    total = db.query(func.count(Expense.id)).scalar() or 0
    if total == 0:
        return ExpenseListResponse(
            items=[],
            total=0,
            page=page,
            per_page=per_page,
            total_amount=0.0,
        )

    sum_amount = db.query(func.coalesce(func.sum(Expense.amount), 0)).scalar() or 0.0

    query = (
        db.query(
            Expense.id,
            Expense.trip_id,
            Expense.amount,
            Expense.description,
            Expense.timestamp,
            Trip.order_id,
            Vehicle.plate_number.label("vehicle_plate"),
            Order.order_number,
            Order.invoice_number,
            Order.destination,
        )
        .outerjoin(Trip, Expense.trip_id == Trip.id)
        .outerjoin(Vehicle, Trip.vehicle_id == Vehicle.id)
        .outerjoin(Order, Trip.order_id == Order.id)
        .order_by(Expense.timestamp.desc(), Expense.id.desc())
        .offset(offset)
        .limit(per_page)
    )

    rows = query.all()

    items: list[ExpenseListItem] = []
    for row in rows:
        if row.order_number:
            order_number = row.order_number
        elif row.invoice_number:
            order_number = row.invoice_number
        elif row.order_id:
            order_number = f"ORD-{row.order_id}"
        else:
            order_number = None

        item = ExpenseListItem(
            id=row.id,
            trip_id=row.trip_id,
            order_number=order_number,
            vehicle_plate=row.vehicle_plate,
            destination=row.destination,
            amount=row.amount,
            description=row.description,
            timestamp=row.timestamp,
        )
        items.append(item)

    return ExpenseListResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_amount=float(sum_amount),
    )
