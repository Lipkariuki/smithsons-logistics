from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.orm import Session
from database import get_db
from models import Commission, Trip, Order
from schemas import CommissionCreate, CommissionOut
from typing import List
from sqlalchemy import func
from pydantic import BaseModel

router = APIRouter(prefix="/commissions", tags=["Commissions"])


@router.post("/", response_model=CommissionOut)
def create_commission(commission: CommissionCreate, db: Session = Depends(get_db)):
    trip = db.query(Trip).filter(Trip.id == commission.trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    order = db.query(Order).filter(Order.id == trip.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found for this trip")

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


@router.get("/", response_model=List[CommissionOut])
def list_commissions(db: Session = Depends(get_db)):
    return db.query(Commission).all()


class CommissionStatusUpdate(BaseModel):
    status: str  # "paid" or "pending"


@router.patch("/{commission_id}/status", response_model=CommissionOut)
def update_commission_status(
    commission_id: int = Path(..., description="ID of the commission"),
    status_update: CommissionStatusUpdate = Depends(),
    db: Session = Depends(get_db)
):
    commission = db.query(Commission).filter(Commission.id == commission_id).first()
    if not commission:
        raise HTTPException(status_code=404, detail="Commission not found")

    commission.status = status_update.status
    db.commit()
    db.refresh(commission)
    return commission


@router.put("/{trip_id}", response_model=CommissionOut)
def update_or_create_commission(
    trip_id: int,
    rate_percent: float = Query(..., ge=0.0, le=100.0),
    db: Session = Depends(get_db)
):
    trip = db.query(Trip).filter(Trip.id == trip_id).first()
    if not trip:
        raise HTTPException(status_code=404, detail="Trip not found")

    order = db.query(Order).filter(Order.id == trip.order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found for this trip")

    amount_paid = (rate_percent / 100) * order.total_amount

    commission = db.query(Commission).filter(Commission.trip_id == trip_id).first()

    if commission:
        commission.rate_percent = rate_percent
        commission.amount_paid = amount_paid
    else:
        commission = Commission(
            trip_id=trip_id,
            rate_percent=rate_percent,
            amount_paid=amount_paid,
            status="pending"
        )
        db.add(commission)

    db.commit()
    db.refresh(commission)
    return commission
