# from fastapi import APIRouter, Depends, HTTPException, Query
# from sqlalchemy.orm import Session
# from typing import List

# from database import get_db
# from models import Trip, Expense
# from schemas import TripOut, ExpenseOut, ExpenseCreate

# router = APIRouter(prefix="/driver", tags=["Driver Dashboard"])

# # 🚚 Get all trips for a driver
# @router.get("/trips", response_model=List[TripOut])
# def get_trips_for_driver(
#     driver_id: int = Query(..., description="TEMP: Provide driver ID"),
#     db: Session = Depends(get_db)
# ):
#     trips = db.query(Trip).filter(Trip.driver_id == driver_id).all()
#     return trips

# # 💸 Get all expenses made by a driver
# @router.get("/expenses", response_model=List[ExpenseOut])
# def get_expenses_for_driver(
#     driver_id: int = Query(..., description="TEMP: Provide driver ID"),
#     db: Session = Depends(get_db)
# ):
#     expenses = (
#         db.query(Expense)
#         .join(Trip)
#         .filter(Trip.driver_id == driver_id)
#         .all()
#     )
#     return expenses

# # ➕ Post a new expense for a trip the driver owns
# @router.post("/expenses", response_model=ExpenseOut)
# def create_driver_expense(
#     expense: ExpenseCreate,
#     driver_id: int = Query(..., description="TEMP: Provide driver ID"),
#     db: Session = Depends(get_db)
# ):
#     # ✅ Validate the trip is owned by this driver
#     trip = db.query(Trip).filter(Trip.id == expense.trip_id, Trip.driver_id == driver_id).first()
#     if not trip:
#         raise HTTPException(status_code=400, detail="Trip not found or not assigned to this driver")

#     db_expense = Expense(**expense.dict())
#     db.add(db_expense)
#     db.commit()
#     db.refresh(db_expense)
#     return db_expense
