from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import Expense, User
from schemas import ExpenseCreate, ExpenseOut
from auth import get_current_user

router = APIRouter(prefix="/driver/expenses", tags=["Driver Expenses"])

@router.post("/", response_model=ExpenseOut)
def create_expense_as_driver(
    expense: ExpenseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != "driver":
        raise HTTPException(status_code=403, detail="Only drivers can post expenses")

    db_expense = Expense(**expense.dict())
    db.add(db_expense)
    db.commit()
    db.refresh(db_expense)
    return db_expense
