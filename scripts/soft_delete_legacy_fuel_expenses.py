"""
Soft-delete legacy fuel expenses that do not have corresponding fuel litre data.
This script marks any expense whose description references fuel but whose trip
does not have a FuelExpense record (i.e., no tracked litres) as deleted.
"""

from sqlalchemy import or_

from typing import Optional

from database import SessionLocal
from models import Expense, FuelExpense


FUEL_KEYWORDS = ("fuel", "diesel", "petrol")


def should_flag(description: Optional[str]) -> bool:
    if not description:
        return False
    desc = description.lower()
    return any(keyword in desc for keyword in FUEL_KEYWORDS)


def soft_delete_legacy_fuel_expenses() -> int:
    session = SessionLocal()
    try:
        fuel_exists = (
            session.query(FuelExpense.id)
            .filter(FuelExpense.trip_id == Expense.trip_id)
        )

        candidates = session.query(Expense).filter(
            Expense.is_deleted.is_(False),
            or_(*[Expense.description.ilike(f"%{kw}%") for kw in FUEL_KEYWORDS]),
            ~fuel_exists.exists(),
        ).all()

        affected = 0
        for expense in candidates:
            if should_flag(expense.description):
                expense.is_deleted = True
                affected += 1

        if affected:
            session.commit()
        else:
            session.rollback()
        return affected
    finally:
        session.close()


if __name__ == "__main__":
    count = soft_delete_legacy_fuel_expenses()
    print(f"Marked {count} legacy fuel expenses as deleted.")
