"""
Import a DHL Excel report into the database.

Usage:
  python import_dhl_report.py --file /path/to/TRIPS_SUMMARY.xlsx [--replace]
"""

import argparse

from database import SessionLocal
from services.dhl_import import import_dhl_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Import DHL report Excel file")
    parser.add_argument("--file", required=True, help="Path to DHL Excel file")
    parser.add_argument(
        "--no-replace",
        action="store_true",
        help="Do not replace existing data for the month",
    )
    args = parser.parse_args()

    with open(args.file, "rb") as f:
        content = f.read()

    db = SessionLocal()
    try:
        result = import_dhl_report(db, content, replace=not args.no_replace)
    finally:
        db.close()

    print("✅ DHL import complete")
    print(f"Period: {result.period_start} to {result.period_end}")
    print(f"Inserted: {result.inserted}")
    print(f"Unmatched vehicles: {result.unmatched}")


if __name__ == "__main__":
    main()
