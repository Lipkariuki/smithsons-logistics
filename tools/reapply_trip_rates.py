#!/usr/bin/env python3
"""
Re-apply rates to existing trips from the CSV rate card.

Usage examples:
  # Dry-run first
  PYTHONPATH=.. python3 tools/reapply_trip_rates.py --destination NJORO --truck-size "7.5T" --dry-run

  # Apply updates
  PYTHONPATH=.. python3 tools/reapply_trip_rates.py --destination NJORO --truck-size "7.5T" --confirm

Notes:
  - Reads backend/data/rate_card.csv via utils.rate_lookup.get_rate()
  - Matches trips by Order.destination and Vehicle.size
  - Updates Trip.revenue only; does not change expenses/commission
"""

from __future__ import annotations

import argparse
from typing import Optional

from sqlalchemy.orm import Session, joinedload

from database import SessionLocal
from models import Trip, Order, Vehicle
from utils.rate_lookup import get_rate


def main():
    p = argparse.ArgumentParser(description="Re-apply rate card to existing trips")
    p.add_argument("--destination", required=True, help="Destination to match, case-insensitive (exact match after trim)")
    p.add_argument("--truck-size", default=None, help="Optional truck size filter, e.g., 7.5T (case-insensitive)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--confirm", action="store_true")
    args = p.parse_args()

    dest = args.destination.strip().upper()
    size_filter = args.truck_size.strip().upper() if args.truck_size else None

    db: Session = SessionLocal()
    try:
        # Eager-load relationships for efficiency
        q = (
            db.query(Trip)
            .options(joinedload(Trip.order), joinedload(Trip.vehicle))
            .join(Order, Trip.order_id == Order.id)
        )
        trips = [
            t for t in q.all()
            if t.order and (t.order.destination or '').strip().upper() == dest
        ]
        if size_filter:
            trips = [t for t in trips if t.vehicle and (t.vehicle.size or '').strip().upper() == size_filter]

        print(f"Found {len(trips)} trip(s) for destination={dest} size={size_filter or '*'}")

        changes = 0
        total_delta = 0.0
        for t in trips:
            veh_size = (t.vehicle.size or '').strip() if t.vehicle else ''
            try:
                new_rate = get_rate(destination=t.order.destination or '', truck_size=veh_size)
            except Exception as e:
                print(f" - Trip {t.id}: rate lookup failed for dest='{t.order.destination}' size='{veh_size}': {e}")
                continue
            old = float(t.revenue or 0)
            if abs(new_rate - old) < 0.005:
                continue
            print(f" - Trip {t.id}: {old:.2f} -> {new_rate:.2f} (Δ {new_rate - old:+.2f})")
            t.revenue = float(new_rate)
            changes += 1
            total_delta += (new_rate - old)

        if args.dry_run and not args.confirm:
            print(f"Dry-run complete. Would update {changes} trip(s); total revenue delta {total_delta:+.2f}.")
            return
        if not args.confirm:
            print("Refusing to update without --confirm")
            return

        db.commit()
        print(f"✅ Updated {changes} trip(s). Total revenue delta {total_delta:+.2f}.")
    except Exception as e:
        db.rollback()
        print("ERROR:", e)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

