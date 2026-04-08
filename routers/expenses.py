from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List
from database import get_db
from models import Expense, Trip, Order, Vehicle, FuelExpense
from schemas import ExpenseCreate, ExpenseOut, ExpenseListResponse, ExpenseListItem
from datetime import date, datetime, time, timedelta

router = APIRouter(prefix="/expenses", tags=["Expenses"])


def _looks_like_fuel(description: str | None) -> bool:
    if not description:
        return False
    lowered = description.lower()
    return "fuel" in lowered or "diesel" in lowered or "petrol" in lowered

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
    exp = (
        db.query(Expense)
        .filter(Expense.id == expense_id, Expense.is_deleted.is_(False))
        .first()
    )
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
    exp = (
        db.query(Expense)
        .filter(Expense.id == expense_id, Expense.is_deleted.is_(False))
        .first()
    )
    if not exp:
        raise HTTPException(status_code=404, detail="Expense not found")
    exp.is_deleted = True
    db.commit()
    return {"status": "deleted"}


@router.get("/", response_model=ExpenseListResponse)
def get_expenses(
    page: int = 1,
    per_page: int = 25,
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    kind: str = Query("all", pattern="^(all|fuel|other)$"),
    db: Session = Depends(get_db),
):
    if page < 1:
        page = 1
    per_page = max(1, min(per_page, 100))
    offset = (page - 1) * per_page

    expense_rows = (
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
        .filter(Expense.is_deleted.is_(False))
        .all()
    )

    fuel_rows = (
        db.query(
            FuelExpense.id,
            FuelExpense.trip_id,
            FuelExpense.amount,
            FuelExpense.litres,
            FuelExpense.price_per_litre,
            FuelExpense.fuel_type,
            FuelExpense.updated_at,
            Trip.order_id,
            Vehicle.plate_number.label("vehicle_plate"),
            Order.order_number,
            Order.invoice_number,
            Order.destination,
            Trip.created_at.label("trip_created"),
            Order.date.label("order_date"),
        )
        .join(Trip, FuelExpense.trip_id == Trip.id)
        .outerjoin(Vehicle, Trip.vehicle_id == Vehicle.id)
        .outerjoin(Order, Trip.order_id == Order.id)
        .all()
    )

    combined = []
    trip_ids_with_fuel_records = {row.trip_id for row in fuel_rows if row.trip_id is not None}
    for row in expense_rows:
        if row.order_number:
            order_number = row.order_number
        elif row.invoice_number:
            order_number = row.invoice_number
        elif row.order_id:
            order_number = f"ORD-{row.order_id}"
        else:
            order_number = None

        looks_like_fuel = _looks_like_fuel(row.description)
        if looks_like_fuel and row.trip_id in trip_ids_with_fuel_records:
            continue

        combined.append({
            "id": row.id,
            "trip_id": row.trip_id,
            "amount": row.amount or 0.0,
            "description": row.description,
            "timestamp": row.timestamp,
            "order_number": order_number,
            "vehicle_plate": row.vehicle_plate,
            "destination": row.destination,
            "kind": "fuel" if looks_like_fuel else "other",
        })

    for row in fuel_rows:
        if row.order_number:
            order_number = row.order_number
        elif row.invoice_number:
            order_number = row.invoice_number
        elif row.order_id:
            order_number = f"ORD-{row.order_id}"
        else:
            order_number = None

        litres = float(row.litres or 0.0)
        price = float(row.price_per_litre or 0.0)
        fuel_type = (row.fuel_type or "").upper()
        description = f"Fuel expense: {litres:.2f} L @ {price:.2f}/L"
        if fuel_type:
            description += f" ({fuel_type})"

        timestamp = row.updated_at or row.order_date or row.trip_created or datetime.utcnow()

        combined.append({
            "id": row.id,
            "trip_id": row.trip_id,
            "amount": row.amount or 0.0,
            "description": description,
            "timestamp": timestamp,
            "order_number": order_number,
            "vehicle_plate": row.vehicle_plate,
            "destination": row.destination,
            "kind": "fuel",
        })

    if start_date or end_date:
        start_dt = datetime.combine(start_date or date.min, time.min)
        end_dt = datetime.combine((end_date or date.max) + timedelta(days=1), time.min)
        combined = [
            row for row in combined
            if row["timestamp"] and start_dt <= row["timestamp"] < end_dt
        ]

    if kind != "all":
        combined = [row for row in combined if row["kind"] == kind]

    combined.sort(key=lambda r: (r["timestamp"] or datetime.min, r["id"]), reverse=True)

    total = len(combined)
    if total == 0:
        return ExpenseListResponse(
            items=[],
            total=0,
            page=page,
            per_page=per_page,
            total_amount=0.0,
        )

    sum_amount = sum(float(row["amount"] or 0.0) for row in combined)

    paged_rows = combined[offset: offset + per_page]

    items: list[ExpenseListItem] = []
    for row in paged_rows:
        item = ExpenseListItem(
            id=row["id"],
            trip_id=row["trip_id"],
            order_number=row["order_number"],
            vehicle_plate=row["vehicle_plate"],
            destination=row["destination"],
            amount=row["amount"],
            description=row["description"],
            timestamp=row["timestamp"],
        )
        items.append(item)

    return ExpenseListResponse(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        total_amount=float(sum_amount),
    )
