from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Enum, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from database import Base

# ✅ User (admin, owner, driver)
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=True, index=True)
    phone = Column(String, unique=True, nullable=True, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(Enum("admin", "owner", "driver", name="user_roles"), default="owner")

    vehicles = relationship("Vehicle", back_populates="owner")
    trips = relationship("Trip", back_populates="driver")


# ✅ Vehicle
class Vehicle(Base):
    __tablename__ = "vehicles"

    id = Column(Integer, primary_key=True, index=True)
    plate_number = Column(String, unique=True)
    owner_id = Column(Integer, ForeignKey("users.id"))

    owner = relationship("User", back_populates="vehicles")
    trips = relationship("Trip", back_populates="vehicle")


# ✅ Order
class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(String, unique=True, nullable=False)
    invoice_number = Column(String, unique=True, index=True)
    purchase_order_number = Column(String, nullable=True)
    dispatch_note_number = Column(String, nullable=True)
    date = Column(DateTime, default=datetime.utcnow)
    

    # ✅ Product fields
    product_type = Column(String)
    product_description = Column(Text, nullable=True)

    truck_plate = Column(String)
    destination = Column(String)
    cases = Column(Integer)
    price_per_case = Column(Float)
    total_amount = Column(Float)
    dispatch_note = Column(Text, nullable=True)

    trip = relationship("Trip", back_populates="order", uselist=False)
    driver_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    driver = relationship("User")


# ✅ Trip
class Trip(Base):
    __tablename__ = "trips"

    id = Column(Integer, primary_key=True, index=True)
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"))
    driver_id = Column(Integer, ForeignKey("users.id"))
    order_id = Column(Integer, ForeignKey("orders.id"))
    status = Column(Enum("started", "completed", "cancelled", name="trip_status"), default="started")
    reimbursement_status = Column(Enum("paid", "unpaid", name="reimbursement_status"), default="unpaid")
    dispatch_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    vehicle = relationship("Vehicle", back_populates="trips")
    driver = relationship("User", back_populates="trips")
    order = relationship("Order", back_populates="trip")
    expenses = relationship("Expense", back_populates="trip")
    commission = relationship("Commission", back_populates="trip", uselist=False)


# ✅ Expense
class Expense(Base):
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    amount = Column(Float)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    timestamp = Column(DateTime, default=datetime.utcnow)

    trip = relationship("Trip", back_populates="expenses")


# ✅ Commission
class Commission(Base):
    __tablename__ = "commissions"

    id = Column(Integer, primary_key=True)
    trip_id = Column(Integer, ForeignKey("trips.id"))
    rate_percent = Column(Float)
    amount_paid = Column(Float)
    status = Column(Enum("pending", "paid", name="commission_status"), default="pending")

    trip = relationship("Trip", back_populates="commission")
