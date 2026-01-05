"""
Utility script to backfill FuelExpense records for existing trips.

Usage:
    poetry run python scripts/backfill_fuel_expenses.py
or:
    python scripts/backfill_fuel_expenses.py --dry-run
"""

from __future__ import annotations

import argparse
from typing import Iterable, Optional

from sqlalchemy.orm import joinedload

from database import SessionLocal
from models import FuelExpense, Trip, User

DEFAULT_PRICE_PER_LITRE = 171.0


def _looks_like_fuel(description: Optional[str]) -> bool:
    if not description:
        return False
    lower = description.lower()
    return "fuel" in lower or "diesel" in lower or "petrol" in lower


def _infer_fuel_type(descriptions: Iterable[str]) -> str:
    for desc in descriptions:
        lower = desc.lower()
        if "petrol" in lower:
            return "petrol"
        if "diesel" in lower:
            return "diesel"
    return "diesel"


def backfill(dry_run: bool = False) -> None:
    session = SessionLocal()
    created = 0
    skipped = 0

    admin_id = (
        session.query(User.id)
        .filter(User.role == "admin")
        .order_by(User.id.asc())
        .limit(1)
        .scalar()
    )

    try:
        trips = (
            session.query(Trip)
            .options(
                joinedload(Trip.expenses),
                joinedload(Trip.order),
                joinedload(Trip.fuel_expense),
            )
            .all()
        )

        for trip in trips:
            if trip.fuel_expense:
                skipped += 1
                continue

            expenses = trip.expenses or []
            fuel_expenses = [exp for exp in expenses if _looks_like_fuel(exp.description)]
            total_amount = sum(float(exp.amount or 0.0) for exp in fuel_expenses)
            descriptions = [exp.description for exp in fuel_expenses if exp.description]

            litres = None
            if trip.order is not None:
                raw_litres = getattr(trip.order, "fuel_litres", None)
                if raw_litres not in (None, ""):
                    try:
                        litres = float(raw_litres)
                    except (TypeError, ValueError):
                        litres = None

            if total_amount <= 0 and litres:
                total_amount = litres * DEFAULT_PRICE_PER_LITRE

            if total_amount <= 0:
                skipped += 1
                continue

            if not litres or litres <= 0:
                litres = round(total_amount / DEFAULT_PRICE_PER_LITRE, 3)

            price_per_litre = total_amount / litres if litres else DEFAULT_PRICE_PER_LITRE
            fuel_type = _infer_fuel_type(descriptions)

            if dry_run:
                print(
                    f"[DRY RUN] Trip #{trip.id}: amount={total_amount:.2f}, "
                    f"litres={litres:.3f}, price={price_per_litre:.2f}, type={fuel_type}"
                )
                created += 1
                continue

            record = FuelExpense(
                trip_id=trip.id,
                fuel_type=fuel_type,
                price_per_litre=price_per_litre,
                amount=total_amount,
                litres=litres,
                updated_by=admin_id,
            )
            session.add(record)
            created += 1

        if not dry_run:
            session.commit()
    finally:
        session.close()

    mode = "DRY" if dry_run else "APPLIED"
    print(f"[{mode}] Created: {created}, Skipped: {skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill FuelExpense records for existing trips.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without committing changes.")
    args = parser.parse_args()

    backfill(dry_run=args.dry_run)
