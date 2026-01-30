import calendar
import io
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional

import pandas as pd
from sqlalchemy.orm import Session

from models import DHLOrder, DHLPayslip, Vehicle


@dataclass
class DHLImportResult:
    period_start: date
    period_end: date
    inserted: int
    skipped: int
    unmatched: int


def _normalize_plate(value: str) -> str:
    return value.strip().replace(" ", "").upper()


def _normalize_ref(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _parse_amount(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _parse_date(value: object) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%m.%d.%y", "%m.%d.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        parsed = pd.to_datetime(text, dayfirst=False, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.date()


def _find_header_row(df_preview: pd.DataFrame) -> int:
    for idx, row in df_preview.iterrows():
        values = {str(v).strip().upper() for v in row.values if v is not None}
        if {"DATE", "TRUCK", "REF NO"}.issubset(values):
            return int(idx)
    return 0


def _period_bounds(dates: Iterable[date]) -> tuple[date, date]:
    months = {(d.year, d.month) for d in dates}
    if len(months) != 1:
        raise ValueError("DHL file contains multiple months; upload one month at a time.")
    year, month = next(iter(months))
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def parse_dhl_excel(content: bytes) -> tuple[list[dict], date, date]:
    buffer = io.BytesIO(content)
    preview = pd.read_excel(buffer, sheet_name=0, header=None, nrows=10)
    header_row = _find_header_row(preview)

    buffer.seek(0)
    df = pd.read_excel(buffer, sheet_name=0, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    required = {"DATE", "REF NO", "TRUCK", "COST", "AMOUNT"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    df = df[df["DATE"].notna()]

    records: dict[tuple[date, str, str], dict] = {}
    for _, row in df.iterrows():
        row_date = _parse_date(row.get("DATE"))
        ref_no = _normalize_ref(row.get("REF NO"))
        truck = row.get("TRUCK")
        if not row_date or not ref_no or not truck:
            continue

        plate = _normalize_plate(str(truck))
        cost_label = str(row.get("COST") or "").strip().lower()
        amount = _parse_amount(row.get("AMOUNT"))

        key = (row_date, ref_no, plate)
        item = records.setdefault(
            key,
            {
                "date": row_date,
                "ref_no": ref_no,
                "invoice_no": _normalize_ref(row.get("KBL INVOICE NO")),
                "truck_plate": plate,
                "distribution_cost": 0.0,
                "offloading_cost": 0.0,
                "description": row.get("DESCRIPTION"),
                "lane_description": row.get("LANE DESCRIPTION"),
                "depot": row.get("DEPOT"),
            },
        )

        if "dist" in cost_label:
            item["distribution_cost"] += amount
        elif "off" in cost_label:
            item["offloading_cost"] += amount

    if not records:
        raise ValueError("No valid DHL rows found in the file.")

    dates = [key[0] for key in records.keys()]
    period_start, period_end = _period_bounds(dates)

    rows = []
    for item in records.values():
        item["total_revenue"] = item["distribution_cost"] + item["offloading_cost"]
        rows.append(item)

    return rows, period_start, period_end


def import_dhl_report(db: Session, content: bytes, replace: bool = True) -> DHLImportResult:
    rows, period_start, period_end = parse_dhl_excel(content)

    if replace:
        db.query(DHLPayslip).filter(
            DHLPayslip.period_start == period_start,
            DHLPayslip.period_end == period_end,
        ).delete(synchronize_session=False)
        db.query(DHLOrder).filter(
            DHLOrder.date >= period_start,
            DHLOrder.date <= period_end,
        ).delete(synchronize_session=False)

    vehicles = {
        _normalize_plate(v.plate_number): v.id
        for v in db.query(Vehicle).all()
        if v.plate_number
    }

    inserted = 0
    skipped = 0
    unmatched = 0

    for row in rows:
        vehicle_id = vehicles.get(row["truck_plate"])
        if vehicle_id is None:
            unmatched += 1

        order = DHLOrder(
            ref_no=row["ref_no"],
            invoice_no=row.get("invoice_no"),
            date=row["date"],
            truck_plate=row["truck_plate"],
            vehicle_id=vehicle_id,
            distribution_cost=row["distribution_cost"],
            offloading_cost=row["offloading_cost"],
            total_revenue=row["total_revenue"],
            description=row.get("description"),
            lane_description=row.get("lane_description"),
            depot=row.get("depot"),
        )
        db.add(order)
        inserted += 1

    db.commit()

    return DHLImportResult(
        period_start=period_start,
        period_end=period_end,
        inserted=inserted,
        skipped=skipped,
        unmatched=unmatched,
    )
