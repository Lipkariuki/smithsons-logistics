#!/usr/bin/env python3
"""
Rename a vehicle plate across the DB and keep orders' displayed truck_plate in sync.

Usage:
  # Dry-run
  PYTHONPATH=.. python3 tools/rename_vehicle_plate.py --from KDL092S --to KDL090S --dry-run

  # Execute
  PYTHONPATH=.. python3 tools/rename_vehicle_plate.py --from KDL092S --to KDL090S --confirm

What it does:
  - Updates Vehicle.plate_number (enforces uniqueness)
  - Updates Orders.truck_plate for orders whose trip links to the vehicle
"""

from __future__ import annotations

import argparse
from sqlalchemy.orm import Session
from sqlalchemy import update

from database import SessionLocal
from models import Vehicle, Trip, Order


def main():
    p = argparse.ArgumentParser(description="Rename a vehicle plate and sync related orders")
    p.add_argument("--from", dest="old", required=True, help="Current plate, e.g., KDL092S")
    p.add_argument("--to", dest="new", required=True, help="New plate, e.g., KDL090S")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--confirm", action="store_true")
    args = p.parse_args()

    old = args.old.strip().upper()
    new = args.new.strip().upper()

    db: Session = SessionLocal()
    try:
        veh = db.query(Vehicle).filter(Vehicle.plate_number == old).first()
        if not veh:
            print(f"No vehicle found with plate {old}")
            return
        clash = db.query(Vehicle).filter(Vehicle.plate_number == new).first()
        if clash:
            print(f"Cannot rename: another vehicle already has plate {new} (id={clash.id})")
            return

        # Count affected orders via trips
        trip_ids = [t.id for t in veh.trips]
        order_ids = [t.order_id for t in veh.trips if t.order_id]
        print(f"Vehicle id={veh.id} {old} -> {new}; trips={len(trip_ids)} orders={len(order_ids)}")
        if args.dry_run and not args.confirm:
            print("Dry-run only. Re-run with --confirm to apply changes.")
            return
        if not args.confirm:
            print("Refusing to proceed without --confirm")
            return

        # Update vehicle
        veh.plate_number = new
        db.flush()

        # Update orders.truck_plate for orders linked via trips for display consistency
        if order_ids:
            db.execute(
                update(Order).where(Order.id.in_(order_ids)).values(truck_plate=new)
            )

        db.commit()
        print(f"✅ Renamed plate {old} -> {new}. Updated {len(order_ids)} order(s) display plate.")
    except Exception as e:
        db.rollback()
        print("ERROR:", e)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

