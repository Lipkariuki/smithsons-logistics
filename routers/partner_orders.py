from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from typing import List

from database import get_db
from models import Order, Trip, Vehicle, User
from schemas import OrderOut
from routers.auth import get_current_user

router = APIRouter(prefix="/partner", tags=["Partner Orders"])

@router.get("/orders", response_model=List[OrderOut])
def get_partner_orders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "owner":
        raise HTTPException(status_code=403, detail="Only partners can view their orders.")

    orders = (
        db.query(Order)
        .join(Trip, Trip.order_id == Order.id)
        .join(Vehicle, Trip.vehicle_id == Vehicle.id)
        .filter(Vehicle.owner_id == current_user.id)
        .options(joinedload(Order.trip))  # Optional: eager load trip data
        .all()
    )
    return orders
