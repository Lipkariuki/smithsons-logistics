from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models import Order, Trip, Vehicle
from schemas import OrderOut

router = APIRouter(prefix="/partner", tags=["Partner Orders"])

@router.get("/orders", response_model=List[OrderOut])
def get_partner_orders_by_owner_id(
    owner_id: int = Query(..., description="TEMP: Pass owner ID manually"),
    db: Session = Depends(get_db)
):
    """
    TEMPORARY PUBLIC ROUTE:
    Return all orders where the vehicle belongs to the specified owner.
    """
    orders = (
        db.query(Order)
        .join(Trip, Trip.order_id == Order.id)
        .join(Vehicle, Trip.vehicle_id == Vehicle.id)
        .filter(Vehicle.owner_id == owner_id)
        .all()
    )
    return orders
