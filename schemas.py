from typing import Optional
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, Union


class OrderCreate(BaseModel):
    invoice_number: str
    purchase_order_number: str
    dispatch_note_number: str
    date: datetime
    product_type: str
    product_description: Optional[str] = ""
    truck_plate: str
    destination: str
    cases: int
    price_per_case: float
    total_amount: float
    millage_fee: Optional[float] = 0.0
    dispatch_note: Optional[str] = ""


class OrderOut(BaseModel):
    id: int
    invoice_number: str
    purchase_order_number: str
    dispatch_note_number: str
    date: datetime
    product_type: str
    product_description: Optional[str] = ""
    truck_plate: str
    destination: str
    cases: int
    price_per_case: float
    total_amount: float
    millage_fee: Optional[float] = 0.0
    dispatch_note: Optional[str] = ""


class ExpenseCreate(BaseModel):
    trip_id: int
    type: str
    amount: float
    description: Optional[str] = None


class ExpenseOut(ExpenseCreate):
    id: int
    created_at: datetime


class TripCreate(BaseModel):
    vehicle_id: int
    driver_id: int
    order_id: int
    status: str = "started"  # started, completed, cancelled
    reimbursement_status: str = "unpaid"  # paid, unpaid
    dispatch_note: str = ""


class TripOut(TripCreate):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class TripMinimalOut(BaseModel):
    id: int
    status: str
    reimbursement_status: str
    dispatch_note: Optional[str] = None

    class Config:
        from_attributes = True


class TripWithDriverVehicleOut(BaseModel):
    id: int
    status: str
    reimbursement_status: str
    dispatch_note: Optional[str]
    vehicle_id: Optional[int]
    driver_id: Optional[int]
    vehicle_plate: Optional[str]
    driver_name: Optional[str]

    class Config:
        from_attributes = True

# ✅ Then define this


class OrderWithTripAndDriverOut(OrderOut):
    trip: Optional[TripWithDriverVehicleOut]

from typing import List

class ExpenseOut(BaseModel):
    id: int
    trip_id: int
    type: str
    amount: float
    description: str
    created_at: datetime

    class Config:
        from_attributes = True


class TripWithExpensesOut(BaseModel):
    id: int
    status: str
    reimbursement_status: str
    dispatch_note: Optional[str]
    vehicle_id: Optional[int]
    driver_id: Optional[int]
    vehicle_plate: Optional[str]
    driver_name: Optional[str]
    expenses: List[ExpenseOut] = []
    total_expenses: float

    class Config:
        from_attributes = True
class ExpenseOut(BaseModel):
    id: int
    trip_id: int
    type: str
    amount: float
    description: str
    created_at: datetime

    class Config:
        from_attributes = True


class TripWithExpensesOut(BaseModel):
    id: int
    status: str
    reimbursement_status: str
    dispatch_note: Optional[str]
    vehicle_id: Optional[int]
    driver_id: Optional[int]
    vehicle_plate: Optional[str]
    driver_name: Optional[str]
    expenses: List[ExpenseOut] = []
    total_expenses: float

    class Config:
        from_attributes = True

class CommissionCreate(BaseModel):
    trip_id: int
    rate_percent: float = 7.0  # default to 7%


class CommissionOut(BaseModel):
    id: int
    trip_id: int
    rate_percent: float
    amount_paid: float
    status: str

    class Config:
        from_attributes = True

