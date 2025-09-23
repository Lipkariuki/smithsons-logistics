#!/usr/bin/env python3
"""
Delete specific orders and their related records (trip, expenses, commission)
by order IDs, order_numbers, and/or truck plate.

Usage examples:

  # Dry run first (recommended)
  python tools/delete_orders_specific.py \
      --order-number 119324730 --order-number 119319662 --order-id 23 --plate KCX114D --dry-run

  # Execute deletion
  python tools/delete_orders_specific.py \
      --order-number 119324730 --order-number 119319662 --order-id 23 --plate KCX114D --confirm

This script uses the same DB settings as database.SessionLocal.
"""

from __future__ import annotations

import argparse
from typing import Iterable, List, Set

from sqlalchemy.orm import Session
from sqlalchemy import or_

from database import SessionLocal
from models import Order, Trip, Expense, Commission


def collect_targets(db: Session, ids: Iterable[int], numbers: Iterable[str], plate: str | None) -> List[Order]:
    filters = []
    id_set: Set[int] = {int(i) for i in ids if str(i).strip()}
    num_set: Set[str] = {str(n).strip() for n in numbers if str(n).strip()}

    q = db.query(Order)
    if id_set:
        filters.append(Order.id.in_(sorted(id_set)))
    if num_set:
        filters.append(Order.order_number.in_(sorted(num_set)))
    if plate:
        filters.append(Order.truck_plate == plate)

    if not filters:
        return []

    # Combine OR to capture any of the identifiers
    query = q.filter(or_(*filters))
    return query.all()


def delete_order_tree(db: Session, order: Order) -> dict:
    """Delete order and related records; return counts for logging."""
    deleted = {"orders": 0, "trips": 0, "expenses": 0, "commissions": 0}
    trip = order.trip
    if trip:
        # Delete expenses
        exps = db.query(Expense).filter(Expense.trip_id == trip.id).all()
        for e in exps:
            db.delete(e)
            deleted["expenses"] += 1
        # Delete commission
        comm = db.query(Commission).filter(Commission.trip_id == trip.id).first()
        if comm:
            db.delete(comm)
            deleted["commissions"] += 1
        # Delete trip
        db.delete(trip)
        deleted["trips"] += 1
    # Delete order
    db.delete(order)
    deleted["orders"] += 1
    return deleted


def main():
    ap = argparse.ArgumentParser(description="Delete specific orders and related records.")
    ap.add_argument("--order-id", action="append", default=[], help="Order ID to delete (repeatable)")
    ap.add_argument("--order-number", action="append", default=[], help="Order number to delete (repeatable)")
    ap.add_argument("--plate", default=None, help="Truck plate to match (optional; combined with others via OR)")
    ap.add_argument("--dry-run", action="store_true", help="Do not delete; just list matches")
    ap.add_argument("--confirm", action="store_true", help="Actually perform deletion")
    args = ap.parse_args()

    db: Session = SessionLocal()
    try:
        targets = collect_targets(db, args.order_id, args.order_number, args.plate)
        if not targets:
            print("No matching orders found for the given criteria.")
            return

        print(f"Found {len(targets)} matching order(s):")
        for o in targets:
            trip = o.trip
            print(f" - Order id={o.id} number={o.order_number} date={o.date} plate={o.truck_plate} dest={o.destination}")
            if trip:
                print(f"   Trip id={trip.id} vehicle_id={trip.vehicle_id} driver_id={trip.driver_id} revenue={trip.revenue}")
            else:
                print("   No trip linked")

        if args.dry_run and not args.confirm:
            print("Dry-run complete. Re-run with --confirm to delete.")
            return

        if not args.confirm:
            print("Refusing to delete without --confirm flag.")
            return

        totals = {"orders": 0, "trips": 0, "expenses": 0, "commissions": 0}
        for o in targets:
            counts = delete_order_tree(db, o)
            for k, v in counts.items():
                totals[k] += v
        db.commit()
        print(
            f"Deleted: orders={totals['orders']}, trips={totals['trips']}, "
            f"expenses={totals['expenses']}, commissions={totals['commissions']}"
        )
    except Exception as e:
        db.rollback()
        print("ERROR:", str(e))
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

