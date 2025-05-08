from models import Order
from sqlalchemy import select
from fastapi import Path
from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from database import SessionLocal
from models import User, Vehicle, Order, Trip, Expense, Commission
from pydantic import BaseModel
from typing import List
from datetime import datetime
from sqlalchemy import func
from schemas import OrderOut
from typing import Optional, Union
from schemas import TripWithExpensesOut
from schemas import OrderWithTripAndDriverOut
from schemas import TripWithDriverVehicleOut
from schemas import TripWithExpensesOut
from schemas import CommissionCreate
from schemas import CommissionOut
app = FastAPI()

# ✅ DB Dependency


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ------------------ USERS ------------------

class UserCreate(BaseModel):
    name: str
    phone: str
    role: str = "owner"
    password: str


class UserOut(UserCreate):
    id: int
    model_config = {"from_attributes": True}


@app.post("/users/", response_model=UserOut)
def create_user(user: UserCreate, db: Session = Depends(get_db)):
    db_user = User(**user.dict())
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


# ------------------ VEHICLES ------------------

class VehicleCreate(BaseModel):
    plate_number: str
    owner_id: int


class VehicleOut(VehicleCreate):
    id: int
    model_config = {"from_attributes": True}


@app.post("/vehicles/", response_model=VehicleOut)
def create_vehicle(vehicle: VehicleCreate, db: Session = Depends(get_db)):
    db_vehicle = Vehicle(**vehicle.dict())
    db.add(db_vehicle)
    db.commit()
    db.refresh(db_vehicle)
    return db_vehicle


# ------------------ ORDERS ------------------

class OrderCreate(BaseModel):
    invoice_number: str
    purchase_order_number: str
    dispatch_note_number: str
    date: datetime
    truck_plate: str
    product_type: str
    destination: str
    cases: int
    price_per_case: float
    total_amount: float
    millage_fee: Optional[float] = 0.0
    dispatch_note: Optional[str] = ""


class OrderOut(OrderCreate):
    id: int
    model_config = {"from_attributes": True}


@app.post("/orders/", response_model=OrderOut)
def create_order(order: OrderCreate, db: Session = Depends(get_db)):
    # ✅ Step 1: Create the order
    db_order = Order(**order.dict())
    db.add(db_order)
    db.commit()
    db.refresh(db_order)

    # ✅ Step 2: Auto-create linked trip
    db_trip = Trip(
        order_id=db_order.id,
        status="started",
        reimbursement_status="unpaid"
    )
    db.add(db_trip)
    db.commit()

    return db_order


@app.get("/orders/", response_model=List[OrderOut])
def get_orders(db: Session = Depends(get_db)):
    results = db.query(
        Order.id,
        Order.invoice_number,
        Order.purchase_order_number,
        Order.dispatch_note_number,
        Order.date,
        Order.truck_plate,
        Order.product_type,
        Order.destination,
        Order.cases,
        Order.price_per_case,
        Order.total_amount,
    ).all()
    return results


@app.get("/orders/{order_id}", response_model=OrderWithTripAndDriverOut)
def get_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    trip = order.trip
    if trip:
        vehicle = trip.vehicle
        driver = trip.driver

        enriched_trip = TripWithDriverVehicleOut(
            id=trip.id,
            status=trip.status,
            reimbursement_status=trip.reimbursement_status,
            dispatch_note=trip.dispatch_note,
            vehicle_id=trip.vehicle_id,
            driver_id=trip.driver_id,
            vehicle_plate=vehicle.plate_number if vehicle else None,
            driver_name=driver.name if driver else None,
        )
    else:
        enriched_trip = None

    return {
        **order.__dict__,
        "trip": enriched_trip
    }


# ------------------ TRIPS ------------------

class TripCreate(BaseModel):
    vehicle_id: int
    driver_id: int
    order_id: int
    status: str = "started"
    reimbursement_status: str = "unpaid"
    dispatch_note: str = None


class TripOut(TripCreate):
    id: int
    created_at: datetime
    model_config = {"from_attributes": True}


@app.post("/trips/", response_model=TripOut)
def create_trip(trip: TripCreate, db: Session = Depends(get_db)):
    db_trip = Trip(**trip.dict())
    db.add(db_trip)
    db.commit()
    db.refresh(db_trip)
    return db_trip


@app.get("/trips/", response_model=List[TripOut])
def list_trips(db: Session = Depends(get_db)):
    return db.query(Trip).all()


# ------------------ EXPENSES ------------------

class ExpenseCreate(BaseModel):
    trip_id: int
    type: str
    amount: float
    description: str = None


class ExpenseOut(ExpenseCreate):
    id: int
    created_at: datetime
    model_config = {"from_attributes": True}


@app.post("/expenses/", response_model=ExpenseOut)
def create_expense(expense: ExpenseCreate, db: Session = Depends(get_db)):
    db_exp = Expense(**expense.dict())
    db.add(db_exp)
    db.commit()
    db.refresh(db_exp)
    return db_exp


@app.get("/expenses/", response_model=List[ExpenseOut])
def list_expenses(db: Session = Depends(get_db)):
    return db.query(Expense).all()





@app.post("/commissions/", response_model=CommissionOut)
def create_commission(commission: CommissionCreate, db: Session = Depends(get_db)):
    # Fetch trip and related order
    trip = db.query(Trip).filter(Trip.id == commission.trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    order = db.query(Order).filter(Order.id == trip.order_id).first()
    if not order:
        raise HTTPException(
            status_code=404, detail="Order not found for this trip")

    # Calculate commission amount
    amount_paid = (commission.rate_percent / 100) * order.total_amount

    db_commission = Commission(
        trip_id=commission.trip_id,
        rate_percent=commission.rate_percent,
        amount_paid=amount_paid,
        status="pending"
    )

    db.add(db_commission)
    db.commit()
    db.refresh(db_commission)
    return db_commission


@app.get("/commissions/", response_model=List[CommissionOut])
def list_commissions(db: Session = Depends(get_db)):
    return db.query(Commission).all()


# Update commission status (e.g., mark as paid)


class CommissionStatusUpdate(BaseModel):
    status: str  # "paid" or "pending"


@app.patch("/commissions/{commission_id}/status", response_model=CommissionOut)
def update_commission_status(
    commission_id: int = Path(..., description="ID of the commission"),
    status_update: CommissionStatusUpdate = Depends(),
    db: Session = Depends(get_db)
):
    commission = db.query(Commission).filter(
        Commission.id == commission_id).first()
    if not commission:
        raise HTTPException(status_code=404, detail="Commission not found")

    commission.status = status_update.status
    db.commit()
    db.refresh(commission)
    return commission


@app.get("/dashboard/summary")
def get_dashboard_summary(db: Session = Depends(get_db)):
    total_trips = db.query(Trip).count()
    total_expenses = db.query(Expense).with_entities(
        func.sum(Expense.amount)).scalar() or 0
    total_commission = db.query(Commission).with_entities(
        func.sum(Commission.amount_paid)).scalar() or 0
    unpaid_commissions = db.query(Commission).filter(
        Commission.status == "pending").count()

    # Estimate profit: total revenue from orders - expenses - commissions
    total_revenue = db.query(Order).with_entities(
        func.sum(Order.total_amount)).scalar() or 0
    estimated_profit = total_revenue - total_expenses - total_commission

    return {
        "total_trips": total_trips,
        "total_expenses": total_expenses,
        "total_commission_paid_or_due": total_commission,
        "unpaid_commissions": unpaid_commissions,
        "total_revenue": total_revenue,
        "estimated_profit": estimated_profit
    }


@app.post("/expenses/", response_model=ExpenseOut)
def create_expense(expense: ExpenseCreate, db: Session = Depends(get_db)):
    db_expense = Expense(**expense.dict())
    db.add(db_expense)
    db.commit()
    db.refresh(db_expense)
    return db_expense


@app.get("/expenses/", response_model=List[ExpenseOut])
def list_expenses(db: Session = Depends(get_db)):
    return db.query(Expense).all()


@app.post("/trips/", response_model=TripOut)
def create_trip(trip: TripCreate, db: Session = Depends(get_db)):
    # ✅ Validate vehicle exists
    vehicle = db.query(Vehicle).filter(Vehicle.id == trip.vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")

    # ✅ Validate order exists
    order = db.query(Order).filter(Order.id == trip.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")

    # ✅ Validate driver exists
    driver = db.query(User).filter(User.id == trip.driver_id,
                                   User.role == "driver").first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")

    db_trip = Trip(
        vehicle_id=trip.vehicle_id,
        driver_id=trip.driver_id,
        order_id=trip.order_id,
        dispatch_note=trip.dispatch_note,
        status=trip.status or "started",  # defaults to started
        reimbursement_status=trip.reimbursement_status or "unpaid"
    )
    db.add(db_trip)
    db.commit()
    db.refresh(db_trip)
    return db_trip


@app.patch("/trips/{trip_id}", response_model=TripOut)
def update_trip(trip_id: int, updates: TripCreate, db: Session = Depends(get_db)):
    db_trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not db_trip:
        raise HTTPException(status_code=404, detail="Trip not found.")

    # Update only provided fields
    if updates.vehicle_id is not None:
        db_trip.vehicle_id = updates.vehicle_id
    if updates.driver_id is not None:
        db_trip.driver_id = updates.driver_id
    if updates.dispatch_note is not None:
        db_trip.dispatch_note = updates.dispatch_note
    if updates.status is not None:
        db_trip.status = updates.status
    if updates.reimbursement_status is not None:
        db_trip.reimbursement_status = updates.reimbursement_status

    db.commit()
    db.refresh(db_trip)
    return db_trip


@app.get("/trips/{trip_id}/with-expenses", response_model=TripWithExpensesOut)
def get_trip_with_expenses(trip_id: int, db: Session = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
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


@app.get("/trips/{trip_id}/profit")
def get_trip_profit(trip_id: int, db: Session = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip or not trip.order:
        raise HTTPException(status_code=404, detail="Trip or order not found.")

    order = trip.order
    expenses = trip.expenses
    commission = trip.commission  # May be None

    total_expenses = sum(e.amount for e in expenses)
    commission_amount = commission.amount_paid if commission else 0.0
    revenue = order.total_amount or 0.0

    net_profit = revenue - total_expenses - commission_amount

    return {
        "trip_id": trip.id,
        "revenue": revenue,
        "total_expenses": total_expenses,
        "commission_paid": commission_amount,
        "net_profit": net_profit
    }



