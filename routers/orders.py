from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from database import get_db
from models import Order, Trip, Vehicle, User, Expense, Commission
from schemas import (
    OrderCreate,
    OrderOut,
    OrderWithTripAndDriverOut,
    TripWithDriverVehicleOut
)

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("/", response_model=OrderOut)
def create_order(order: OrderCreate, db: Session = Depends(get_db)):
    db_order = Order(
        order_number=order.order_number,
        invoice_number=order.invoice_number,
        purchase_order_number=order.purchase_order_number,
        dispatch_note_number=order.dispatch_note_number,
        date=order.date,
        product_type=order.product_type,
        product_description=order.product_description,
        truck_plate=order.truck_plate,
        destination=order.destination,
        cases=order.cases,
        price_per_case=order.price_per_case,
        total_amount=order.total_amount,
        dispatch_note=order.dispatch_note
    )
    db.add(db_order)
    db.commit()
    db.refresh(db_order)

    vehicle = db.query(Vehicle).filter(Vehicle.plate_number == order.truck_plate).first()

    db_trip = Trip(
        order_id=db_order.id,
        driver_id=None,
        vehicle_id=vehicle.id if vehicle else None,
        status="started",
        reimbursement_status="unpaid"
    )
    db.add(db_trip)
    db.commit()

    return db_order


@router.put("/{order_id}/assign-driver", response_model=OrderOut)
def assign_driver(order_id: int, driver_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    trip = db.query(Trip).filter(Trip.order_id == order_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    trip.driver_id = driver_id
    db.commit()
    db.refresh(order)
    return order


@router.put("/{order_id}/assign-vehicle")
def assign_vehicle(order_id: int, vehicle_id: int, db: Session = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.order_id == order_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    trip.vehicle_id = vehicle_id
    db.commit()
    return {"message": "Vehicle assigned successfully"}


@router.get("/", response_model=list[OrderWithTripAndDriverOut])
def get_orders(month: int = Query(None, ge=1, le=12), db: Session = Depends(get_db)):
    query = db.query(Order)

    if month:
        current_year = datetime.utcnow().year
        query = query.filter(
            func.extract("month", Order.date) == month,
            func.extract("year", Order.date) == current_year
        )

    orders = query.all()
    results = []

    for order in orders:
        trip = order.trip
        if trip:
            vehicle = trip.vehicle
            driver = trip.driver

            expenses_total = db.query(func.sum(Expense.amount)) \
                .filter(Expense.trip_id == trip.id).scalar() or 0

            commission_row = db.query(Commission).filter(Commission.trip_id == trip.id).first()
            commission_amount = commission_row.amount_paid if commission_row else 0

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
            expenses_total = 0
            commission_amount = 0
            enriched_trip = None

        results.append(OrderWithTripAndDriverOut(
            id=order.id,
            order_number=order.order_number,
            invoice_number=order.invoice_number,
            purchase_order_number=order.purchase_order_number,
            dispatch_note_number=order.dispatch_note_number,
            date=order.date,
            product_type=order.product_type,
            product_description=order.product_description,
            vehicle_id=None,
            destination=order.destination,
            cases=order.cases,
            price_per_case=order.price_per_case,
            total_amount=order.total_amount,
            dispatch_note=order.dispatch_note,
            trip=enriched_trip,
            expenses=expenses_total,
            commission=commission_amount
        ))

    return results
