from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime, date

# =========================
# USER
# =========================

class UserCreate(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    password: str
    role: str = "owner"

class UserOut(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    role: str
    model_config = ConfigDict(from_attributes=True, extra="ignore")

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    id: Optional[int] = None

# =========================
# VEHICLE
# =========================

class VehicleCreate(BaseModel):
    plate_number: str
    owner_id: int
    size: Optional[str] = None

class VehicleOut(VehicleCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)


class VehicleUpdate(BaseModel):
    plate_number: Optional[str] = None
    owner_id: Optional[int] = None
    size: Optional[str] = None

# =========================
# ORDER
# =========================

class OrderCreate(BaseModel):
    order_number: str
    invoice_number: Optional[str] = None
    purchase_order_number: Optional[str] = None
    dispatch_note_number: Optional[str] = None
    date: date  # required
    product_type: Optional[str] = None
    product_description: Optional[str] = None
    truck_plate: Optional[str] = None
    destination: Optional[str] = None
    cases: Optional[int] = 0
    price_per_case: Optional[float] = 0
    fuel_litres: Optional[float] = None
    driver_details: Optional[str] = None
    #total_amount: Optional[float] = 0

class OrderOut(BaseModel):
    id: int
    order_number: Optional[str] = None
    invoice_number: Optional[str] = ""
    purchase_order_number: Optional[str] = ""
    dispatch_note_number: Optional[str] = ""
    date: Optional[datetime] = None
    product_type: Optional[str] = ""
    product_description: Optional[str] = ""
    truck_plate: Optional[str] = ""
    destination: Optional[str] = ""
    cases: Optional[int] = 0
    price_per_case: Optional[float] = 0.0
    total_amount: Optional[float] = 0.0
    fuel_litres: Optional[float] = None
    driver_details: Optional[str] = None
    dispatch_note: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class AdminOrderOut(BaseModel):
    id: int
    order_number: Optional[str] = None
    invoice_number: Optional[str] = ""
    # include order date for filtering/sorting on frontend
    date: Optional[datetime] = None
    product_description: Optional[str] = ""
    destination: str
    driver_name: str
    # ids used by filters on frontend
    driver_id: Optional[int] = None
    owner_id: Optional[int] = None
    total_amount: float
    expenses: float
    commission: float
    revenue: float
    trip_id: Optional[int] = None
    truck_plate: Optional[str] = None
    fuel_litres: Optional[float] = None
    driver_details: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

# =========================
# TRIP
# =========================

class TripCreate(BaseModel):
    vehicle_id: Optional[int] = None
    driver_id: Optional[int] = None
    order_id: int
    status: Optional[str] = "started"
    reimbursement_status: Optional[str] = "unpaid"
    dispatch_note: Optional[str] = None

class TripOut(BaseModel):
    id: int
    status: str
    reimbursement_status: str
    dispatch_note: Optional[str]
    vehicle_plate: Optional[str]
    driver_name: Optional[str]
    destination: Optional[str]
    created_at: datetime
    revenue: Optional[float] = 0.0
    order_number: Optional[str] = None  
    model_config = ConfigDict(from_attributes=True)

class TripMinimalOut(BaseModel):
    id: int
    vehicle_plate: Optional[str]
    driver_name: Optional[str]
    destination: Optional[str]
    model_config = ConfigDict(from_attributes=True)

class TripWithDriverVehicleOut(BaseModel):
    id: int
    status: str
    reimbursement_status: str
    dispatch_note: Optional[str] = None
    vehicle_id: Optional[int] = None
    driver_id: Optional[int] = None
    vehicle_plate: Optional[str] = None
    driver_name: Optional[str] = None
    revenue: Optional[float] = 0.0
    model_config = ConfigDict(from_attributes=True)

class OrderWithTripAndDriverOut(BaseModel):
    id: int
    order_number: Optional[str] = None
    invoice_number: str
    purchase_order_number: str
    dispatch_note_number: str
    date: datetime
    product_type: str
    product_description: Optional[str] = None
    vehicle_id: Optional[int] = None
    destination: str
    cases: int
    price_per_case: float
    total_amount: float
    fuel_litres: Optional[float] = None
    driver_details: Optional[str] = None
    dispatch_note: Optional[str] = None
    trip: Optional[TripWithDriverVehicleOut]
    expenses: float = 0
    commission: float = 0
    model_config = ConfigDict(from_attributes=True)

# =========================
# EXPENSE
# =========================

class ExpenseCreate(BaseModel):
    trip_id: Optional[int] = None
    order_number: Optional[str] = None
    amount: float
    description: Optional[str] = None

class ExpenseOut(BaseModel):
    id: int
    amount: float
    description: Optional[str]
    timestamp: datetime
    trip_id: int
    model_config = ConfigDict(from_attributes=True)


class ExpenseListItem(BaseModel):
    id: int
    trip_id: Optional[int] = None
    order_number: Optional[str] = None
    vehicle_plate: Optional[str] = None
    destination: Optional[str] = None
    amount: float
    description: Optional[str] = None
    timestamp: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class ExpenseListResponse(BaseModel):
    items: list[ExpenseListItem]
    total: int
    page: int
    per_page: int
    total_amount: float

class SimpleExpenseOut(BaseModel):
    id: int
    amount: float
    description: Optional[str]
    timestamp: datetime
    trip_id: int
    model_config = ConfigDict(from_attributes=True)

# =========================
# COMMISSION
# =========================

class CommissionCreate(BaseModel):
    trip_id: int
    rate_percent: float = 7.0

class CommissionOut(BaseModel):
    id: int
    trip_id: int
    rate_percent: float
    amount_paid: float
    status: str
    model_config = ConfigDict(from_attributes=True)

# =========================
# COMPOSITE TRIP RESPONSE
# =========================

class TripWithExpensesOut(BaseModel):
    id: int
    status: str
    reimbursement_status: str
    dispatch_note: Optional[str] = None
    vehicle_id: Optional[int] = None
    driver_id: Optional[int] = None
    vehicle_plate: Optional[str] = None
    driver_name: Optional[str] = None
    expenses: List[SimpleExpenseOut] = []
    total_expenses: float
    model_config = ConfigDict(from_attributes=True)

class TripWithOrderOut(BaseModel):
    trip_id: int
    status: str
    order_id: Optional[int] = None
    order_number: Optional[str] = None
    invoice_number: Optional[str] = None
    product_description: Optional[str] = None
    destination: Optional[str] = None
    total_amount: Optional[float] = None
    vehicle_plate: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

# =========================
# OWNER RECONCILIATION & REPORTS
# =========================


class OwnerReconciliationCreate(BaseModel):
    vehicle_plate: str
    period_start: date
    period_end: date
    fuel_cost: float | None = 0.0
    extra_expenses: float | None = 0.0
    commission_adjustment: float | None = 0.0
    actual_payment: float | None = None
    notes: Optional[str] = None


class OwnerReconciliationOut(BaseModel):
    id: int
    vehicle_id: int
    vehicle_plate: str
    period_start: date
    period_end: date
    fuel_cost: float
    extra_expenses: float
    commission_adjustment: float
    actual_payment: Optional[float]
    notes: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class VehicleReportOut(BaseModel):
    vehicle_id: int
    plate_number: str
    owner_id: Optional[int] = None
    owner_name: str
    owner_phone: Optional[str]
    trip_count: int
    gross_revenue: float
    fuel_cost: float
    other_expenses: float
    extra_expenses: float
    commission: float
    net_profit: float
    actual_payment: Optional[float] = None
    variance: Optional[float] = None
    notes: Optional[str] = None
