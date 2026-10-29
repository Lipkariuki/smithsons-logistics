from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import Expense, User
from schemas import ExpenseCreate, ExpenseOut
from routers.auth import get_current_user
from routers.driver_trips import add_driver_expense

router = APIRouter(prefix="/driver/expenses", tags=["Driver Expenses"])

@router.post("/", response_model=ExpenseOut)
def create_expense_as_driver(
    expense: ExpenseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Both URL spellings enforce the same driver and trip-ownership checks.
    return add_driver_expense(expense=expense, db=db, current_user=current_user)
