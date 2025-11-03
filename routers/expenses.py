from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func, select, literal, union_all, desc, String, Float
from typing import List
from database import get_db
from models import Expense, Trip, Order, Vehicle, FuelExpense
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
    db: Session = Depends(get_db),
):
    if page < 1:
        page = 1
    per_page = max(1, min(per_page, 100))
    offset = (page - 1) * per_page

    expense_select = (
        select(
            Expense.id.label("id"),
            Expense.trip_id.label("trip_id"),
            Expense.amount.label("amount"),
            Expense.description.label("description"),
            Expense.timestamp.label("timestamp"),
            Trip.order_id.label("order_id"),
            Vehicle.plate_number.label("vehicle_plate"),
            Order.order_number.label("order_number"),
            Order.invoice_number.label("invoice_number"),
            Order.destination.label("destination"),
            literal(None, type_=Float).label("fuel_litres"),
            literal(None, type_=Float).label("fuel_price_per_litre"),
            literal(None, type_=String).label("fuel_type"),
            literal("expense", type_=String).label("kind"),
        )
        .select_from(Expense)
        .outerjoin(Trip, Expense.trip_id == Trip.id)
        .outerjoin(Vehicle, Trip.vehicle_id == Vehicle.id)
        .outerjoin(Order, Trip.order_id == Order.id)
        .where(Expense.is_deleted.is_(False))
    )

    fuel_select = (
        select(
            FuelExpense.id.label("id"),
            FuelExpense.trip_id.label("trip_id"),
            FuelExpense.amount.label("amount"),
            literal(None, type_=String).label("description"),
            FuelExpense.updated_at.label("timestamp"),
            Trip.order_id.label("order_id"),
            Vehicle.plate_number.label("vehicle_plate"),
            Order.order_number.label("order_number"),
            Order.invoice_number.label("invoice_number"),
            Order.destination.label("destination"),
            FuelExpense.litres.label("fuel_litres"),
            FuelExpense.price_per_litre.label("fuel_price_per_litre"),
            FuelExpense.fuel_type.label("fuel_type"),
            literal("fuel", type_=String).label("kind"),
        )
        .select_from(FuelExpense)
        .join(Trip, FuelExpense.trip_id == Trip.id)
        .outerjoin(Vehicle, Trip.vehicle_id == Vehicle.id)
        .outerjoin(Order, Trip.order_id == Order.id)
    )

    combined_subquery = union_all(expense_select, fuel_select).subquery()

    total = db.execute(select(func.count()).select_from(combined_subquery)).scalar() or 0
    if total == 0:
        return ExpenseListResponse(
            items=[],
            total=0,
            page=page,
            per_page=per_page,
            total_amount=0.0,
        )

    sum_amount = (
        db.execute(select(func.coalesce(func.sum(combined_subquery.c.amount), 0.0))).scalar() or 0.0
    )

    rows = (
        db.execute(
            select(combined_subquery)
            .order_by(desc(combined_subquery.c.timestamp), desc(combined_subquery.c.id))
            .offset(offset)
            .limit(per_page)
        ).mappings().all()
    )

    items: list[ExpenseListItem] = []
    for row in rows:
        if row["order_number"]:
            order_number = row["order_number"]
        elif row["invoice_number"]:
            order_number = row["invoice_number"]
        elif row["order_id"]:
            order_number = f"ORD-{row['order_id']}"
        else:
            order_number = None

        if row["kind"] == "fuel":
            litres = row["fuel_litres"] or 0.0
            price = row["fuel_price_per_litre"] or 0.0
            fuel_type = (row["fuel_type"] or "").upper()
            description = (
                f"Fuel expense: {litres:.2f} L @ {price:.2f}/L"
                + (f" ({fuel_type})" if fuel_type else "")
            )
        else:
            description = row["description"]

        item = ExpenseListItem(
            id=row["id"],
            trip_id=row["trip_id"],
            order_number=order_number,
            vehicle_plate=row["vehicle_plate"],
            destination=row["destination"],
            amount=row["amount"],
            description=description,
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
