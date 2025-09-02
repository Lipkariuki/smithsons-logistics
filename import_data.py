"""
Bulk import owners, vehicles, and drivers from CSV files.

Usage:
  python import_data.py --owners_vehicles data/owners_vehicles.csv --drivers data/drivers.csv \
      [--default_owner_password pw] [--default_driver_password pw]

CSV formats:
  owners_vehicles.csv columns (one vehicle per row):
    owner_name, owner_phone, owner_email(optional), vehicle_plate, tonnage(optional), size(optional)

  drivers.csv columns:
    name, phone, email(optional), password(optional)

Notes:
  - Phones are normalized to +2547XXXXXXXX where possible.
  - Vehicles are upserted by plate; owners are upserted by phone.
  - Vehicle.size is derived from tonnage if provided; falls back to size column string.
"""

import argparse
import csv
import re
from typing import Optional

from sqlalchemy.orm import Session
from passlib.context import CryptContext

from database import SessionLocal
from models import User, Vehicle

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def normalize_ke_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    p = phone.strip().replace(" ", "").replace("-", "")
    if p.startswith("+254"):
        return p
    if p.startswith("254"):
        return "+" + p
    if p.startswith("0") and len(p) == 10:
        return "+254" + p[1:]
    # Handle common spreadsheet case: 9-digit number starting with 7 (missing leading 0)
    if len(p) == 9 and p.startswith("7"):
        return "+254" + p
    return p


def tonnage_to_size(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    raw = value.strip().upper()
    if not raw:
        return None
    # Preserve known labels
    if "VAN" in raw:
        return "VAN"
    if "PICKUP" in raw:
        return "PICKUP"
    # Try numeric extract
    num = ""
    for ch in raw:
        if ch.isdigit() or ch == ".":
            num += ch
    try:
        t = float(num) if num else None
    except ValueError:
        t = None

    if t is not None:
        # Normalize to exact label like '14T' or '7.5T'
        if abs(t - int(t)) < 1e-6:
            return f"{int(t)}T"
        return f"{t}T"

    # Fallback to label cleanup (e.g., 'PICKUP', 'VAN')
    # Fallback: return cleaned raw (e.g., '14 TONNES' -> '14 TONNES')
    return raw


def upsert_owner_and_vehicle(db: Session, owner_name: str, owner_phone: str, owner_email: Optional[str], plate: str, tonnage: Optional[str], size_label: Optional[str], default_owner_password: str):
    phone = normalize_ke_phone(owner_phone)
    if not phone:
        print(f"[SKIP] Missing owner phone for plate {plate}")
        return

    owner = db.query(User).filter(User.phone == phone).first()
    if not owner:
        owner = User(
            name=owner_name.strip() if owner_name else "Owner",
            email=(owner_email or None),
            phone=phone,
            password_hash=pwd_context.hash(default_owner_password),
            role="owner",
        )
        db.add(owner)
        db.flush()  # get ID

    # Derive size
    size = tonnage_to_size(tonnage) or (size_label.strip().upper() if size_label else None)

    # Normalize plate: uppercase and remove inner spaces
    plate_norm = re.sub(r"\s+", "", plate.strip().upper())
    vehicle = db.query(Vehicle).filter(Vehicle.plate_number == plate_norm).first()
    if vehicle:
        vehicle.owner_id = owner.id
        if size:
            vehicle.size = size
    else:
        vehicle = Vehicle(plate_number=plate_norm, owner_id=owner.id, size=size)
        db.add(vehicle)


def upsert_driver(db: Session, name: str, phone: str, email: Optional[str], password: Optional[str], default_driver_password: str):
    phone_n = normalize_ke_phone(phone)
    if not phone_n:
        print(f"[SKIP] Missing driver phone for {name}")
        return
    user = db.query(User).filter(User.phone == phone_n).first()
    if user:
        # Update basic fields if changed; keep role as driver
        user.name = name or user.name
        user.email = email or user.email
        user.role = "driver"
        return
    pw = password or default_driver_password
    new_driver = User(name=name, email=email, phone=phone_n, password_hash=pwd_context.hash(pw), role="driver")
    db.add(new_driver)


def run_import(owners_vehicles_csv: Optional[str], drivers_csv: Optional[str], default_owner_password: str, default_driver_password: str):
    db: Session = SessionLocal()
    try:
        if owners_vehicles_csv:
            with open(owners_vehicles_csv, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    upsert_owner_and_vehicle(
                        db,
                        owner_name=row.get("owner_name", "").strip(),
                        owner_phone=row.get("owner_phone", "").strip(),
                        owner_email=row.get("owner_email") or None,
                        plate=row.get("vehicle_plate", "").strip(),
                        tonnage=row.get("tonnage") or None,
                        size_label=row.get("size") or None,
                        default_owner_password=default_owner_password,
                    )

        if drivers_csv:
            with open(drivers_csv, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    upsert_driver(
                        db,
                        name=row.get("name", "").strip(),
                        phone=row.get("phone", "").strip(),
                        email=row.get("email") or None,
                        password=row.get("password") or None,
                        default_driver_password=default_driver_password,
                    )

        db.commit()
        print("✅ Import completed.")
    except Exception as e:
        db.rollback()
        print("❌ Import failed:", str(e))
        raise
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Bulk import owners, vehicles, and drivers from CSV")
    parser.add_argument("--owners_vehicles", help="CSV path for owners + vehicles", default=None)
    parser.add_argument("--drivers", help="CSV path for drivers", default=None)
    parser.add_argument("--default_owner_password", help="Default password for owners", default="ownerpass123")
    parser.add_argument("--default_driver_password", help="Default password for drivers", default="driverpass123")
    parser.add_argument("--seed_dummy_drivers", type=int, default=0, help="Seed N dummy drivers if drivers CSV not supplied")
    args = parser.parse_args()

    if not args.owners_vehicles and not args.drivers:
        print("Provide at least one CSV via --owners_vehicles or --drivers")
        return

    run_import(args.owners_vehicles, args.drivers, args.default_owner_password, args.default_driver_password)

    # Optional: seed dummy drivers
    if args.seed_dummy_drivers and not args.drivers:
        db: Session = SessionLocal()
        try:
            base = 710000001
            for i in range(args.seed_dummy_drivers):
                phone = f"+254{base + i:09d}"[-13:]  # ensure +2547XXXXXXXX format
                existing = db.query(User).filter(User.phone == phone).first()
                if existing:
                    continue
                name = f"Driver {i+1:03d}"
                user = User(name=name, phone=phone, role="driver", password_hash=pwd_context.hash("driverpass123"))
                db.add(user)
            db.commit()
            print(f"✅ Seeded {args.seed_dummy_drivers} dummy drivers (where not existing)")
        finally:
            db.close()


if __name__ == "__main__":
    main()
