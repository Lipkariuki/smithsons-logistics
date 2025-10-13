"""
Import owner reconciliation adjustments from a CSV file.

Usage:
    python import_reconciliations.py path/to/reconciliations.csv

CSV columns (headers required):
    vehicle_plate,period_start,period_end,fuel_cost,extra_expenses,commission_adjustment,actual_payment,notes
Dates must be in YYYY-MM-DD format. Amounts should be numeric.
"""

import argparse
import csv
from datetime import datetime
from pathlib import Path
from typing import Tuple

from database import SessionLocal
from models import OwnerReconciliation, Vehicle


def normalize_plate(plate: str) -> str:
    return plate.strip().replace(" ", "").upper()


def parse_float(value: str) -> float:
    value = (value or "").strip()
    if not value:
        return 0.0
    return float(value)


def parse_date(value: str):
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def import_csv(path: Path) -> Tuple[int, int, int]:
    created = 0
    updated = 0
    skipped = 0

    with path.open("r", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"vehicle_plate", "period_start", "period_end"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f"CSV must contain headers: {', '.join(sorted(required))}")

        session = SessionLocal()

        try:
            for row in reader:
                plate = (row.get("vehicle_plate") or "").strip()
                if not plate:
                    skipped += 1
                    continue

                norm_plate = normalize_plate(plate)
                vehicle = (
                    session.query(Vehicle)
                    .filter(Vehicle.plate_number.in_({plate.upper(), norm_plate}))
                    .first()
                )
                if not vehicle:
                    print(f"Skipping row for unknown vehicle: {plate}")
                    skipped += 1
                    continue

                try:
                    start = parse_date(row["period_start"])
                    end = parse_date(row["period_end"])
                except (KeyError, ValueError):
                    print(f"Skipping row with invalid dates for vehicle: {plate}")
                    skipped += 1
                    continue

                fuel_cost = parse_float(row.get("fuel_cost", ""))
                extra_expenses = parse_float(row.get("extra_expenses", ""))
                commission_adjustment = parse_float(row.get("commission_adjustment", ""))
                actual_payment_value = row.get("actual_payment", "")
                if actual_payment_value.strip():
                    try:
                        actual_payment = float(actual_payment_value)
                    except ValueError:
                        print(f"Skipping row with invalid actual_payment for vehicle: {plate}")
                        skipped += 1
                        continue
                else:
                    actual_payment = None
                notes = (row.get("notes") or "").strip() or None

                existing = (
                    session.query(OwnerReconciliation)
                    .filter(
                        OwnerReconciliation.vehicle_id == vehicle.id,
                        OwnerReconciliation.period_start == start,
                        OwnerReconciliation.period_end == end,
                    )
                    .first()
                )

                if existing:
                    existing.fuel_cost = fuel_cost
                    existing.extra_expenses = extra_expenses
                    existing.commission_adjustment = commission_adjustment
                    existing.actual_payment = actual_payment
                    existing.notes = notes
                    updated += 1
                else:
                    record = OwnerReconciliation(
                        vehicle_id=vehicle.id,
                        period_start=start,
                        period_end=end,
                        fuel_cost=fuel_cost,
                        extra_expenses=extra_expenses,
                        commission_adjustment=commission_adjustment,
                        actual_payment=actual_payment,
                        notes=notes,
                    )
                    session.add(record)
                    created += 1

            session.commit()
        finally:
            session.close()

    return created, updated, skipped


def main():
    parser = argparse.ArgumentParser(description="Import owner reconciliation data")
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args()

    created, updated, skipped = import_csv(args.csv_path)
    print(f"Import complete. Created: {created}, Updated: {updated}, Skipped: {skipped}")


if __name__ == "__main__":
    main()
