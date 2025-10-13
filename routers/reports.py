from __future__ import annotations

import csv
import io
from datetime import date, datetime, time, timedelta
from typing import Iterable, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel

from database import get_db
from models import OwnerReconciliation, Trip, User, Vehicle
from schemas import OwnerReconciliationOut, VehicleReportOut
from utils.sms import send_sms

router = APIRouter(prefix="/reports", tags=["Reports"])


def _normalize_plate(value: str) -> str:
    return value.strip().replace(" ", "").upper()


def _default_dates(start: Optional[date], end: Optional[date]) -> tuple[date, date]:
    today = date.today()
    if start is None:
        start = today.replace(day=1)
    if end is None:
        # end of month of start
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(days=1)
    if end < start:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    return start, end


def _date_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end + timedelta(days=1), time.min)
    return start_dt, end_dt


def _parse_float(value: Optional[str]) -> float:
    if value is None:
        return 0.0
    text = value.strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid numeric value: '{value}'") from exc


def _build_vehicle_reports(
    db: Session,
    owner_id: Optional[int],
    vehicle_id: Optional[int],
    start_date: date,
    end_date: date,
) -> list[VehicleReportOut]:
    start_dt, end_dt = _date_bounds(start_date, end_date)

    trip_query = (
        db.query(Trip)
        .options(
            joinedload(Trip.expenses),
            joinedload(Trip.commission),
            joinedload(Trip.vehicle).joinedload(Vehicle.owner),
        )
        .filter(Trip.created_at >= start_dt, Trip.created_at < end_dt)
    )
    if owner_id:
        trip_query = trip_query.join(Vehicle).filter(Vehicle.owner_id == owner_id)
    if vehicle_id:
        trip_query = trip_query.filter(Trip.vehicle_id == vehicle_id)

    trips = trip_query.all()

    stats: dict[int, dict] = {}

    for trip in trips:
        vehicle = trip.vehicle
        if vehicle is None:
            continue
        key = vehicle.id
        data = stats.setdefault(
            key,
            {
                "vehicle": vehicle,
                "trip_count": 0,
                "gross_revenue": 0.0,
                "other_expenses": 0.0,
                "commission": 0.0,
                "fuel_cost": 0.0,
                "extra_expenses": 0.0,
                "actual_payment": 0.0,
                "notes": [],
            },
        )
        data["trip_count"] += 1
        data["gross_revenue"] += float(trip.revenue or 0.0)
        for expense in trip.expenses or []:
            data["other_expenses"] += float(expense.amount or 0.0)
        if trip.commission:
            data["commission"] += float(trip.commission.amount_paid or 0.0)

    vehicle_query = db.query(Vehicle).options(joinedload(Vehicle.owner))
    if owner_id:
        vehicle_query = vehicle_query.filter(Vehicle.owner_id == owner_id)
    if vehicle_id:
        vehicle_query = vehicle_query.filter(Vehicle.id == vehicle_id)

    vehicles = vehicle_query.all()

    for vehicle in vehicles:
        stats.setdefault(
            vehicle.id,
            {
                "vehicle": vehicle,
                "trip_count": 0,
                "gross_revenue": 0.0,
                "other_expenses": 0.0,
                "commission": 0.0,
                "fuel_cost": 0.0,
                "extra_expenses": 0.0,
                "actual_payment": 0.0,
                "notes": [],
            },
        )

    if not stats:
        return []

    adjustments = (
        db.query(OwnerReconciliation)
        .filter(
            OwnerReconciliation.vehicle_id.in_(stats.keys()),
            OwnerReconciliation.period_start <= end_date,
            OwnerReconciliation.period_end >= start_date,
        )
        .all()
    )

    for adj in adjustments:
        data = stats.get(adj.vehicle_id)
        if data is None:
            continue
        data["fuel_cost"] += float(adj.fuel_cost or 0.0)
        data["extra_expenses"] += float(adj.extra_expenses or 0.0)
        data["commission"] += float(adj.commission_adjustment or 0.0)
        if adj.actual_payment:
            data["actual_payment"] += float(adj.actual_payment)
        if adj.notes:
            data["notes"].append(adj.notes.strip())

    results: list[VehicleReportOut] = []

    for vehicle_id_key, data in stats.items():
        vehicle = data["vehicle"]
        owner: Optional[User] = vehicle.owner if hasattr(vehicle, "owner") else None
        gross = data["gross_revenue"]
        fuel_cost = data["fuel_cost"]
        other_expenses = data["other_expenses"]
        extra_expenses = data["extra_expenses"]
        commission_total = data["commission"]
        net_profit = gross - fuel_cost - other_expenses - extra_expenses - commission_total
        actual_payment = data["actual_payment"] or None
        variance = None
        if actual_payment is not None:
            variance = actual_payment - net_profit
        notes = "; ".join([note for note in data["notes"] if note]) or None

        owner_name = (owner.name or "").strip() if owner else ""
        owner_phone = owner.phone.strip() if getattr(owner, "phone", None) else None

        results.append(
            VehicleReportOut(
                vehicle_id=vehicle_id_key,
                plate_number=vehicle.plate_number,
                owner_id=owner.id if owner else None,
                owner_name=owner_name,
                owner_phone=owner_phone,
                trip_count=data["trip_count"],
                gross_revenue=round(gross, 2),
                fuel_cost=round(fuel_cost, 2),
                other_expenses=round(other_expenses, 2),
                extra_expenses=round(extra_expenses, 2),
                commission=round(commission_total, 2),
                net_profit=round(net_profit, 2),
                actual_payment=round(actual_payment, 2) if actual_payment is not None else None,
                variance=round(variance, 2) if variance is not None else None,
                notes=notes,
            )
        )

    results.sort(key=lambda item: (item.owner_name.lower(), item.plate_number))
    return results


@router.get("/summary", response_model=list[VehicleReportOut])
def get_reports_summary(
    owner_id: Optional[int] = Query(None),
    vehicle_id: Optional[int] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
):
    start, end = _default_dates(start_date, end_date)
    return _build_vehicle_reports(db, owner_id, vehicle_id, start, end)


class SendReportPayload(BaseModel):
    vehicle_id: int
    start_date: Optional[date] = None
    end_date: Optional[date] = None


@router.post("/send")
def send_vehicle_report(payload: SendReportPayload, db: Session = Depends(get_db)):
    start, end = _default_dates(payload.start_date, payload.end_date)
    reports = _build_vehicle_reports(db, None, payload.vehicle_id, start, end)
    if not reports:
        raise HTTPException(status_code=404, detail="No report data for the selected vehicle and period")

    report = reports[0]
    if not report.owner_phone:
        raise HTTPException(status_code=400, detail="Owner does not have a phone number on record")

    message_lines = [
        f"Dear {report.owner_name.split()[0] if report.owner_name else 'Partner'},",
        f"{report.plate_number} ({start.isoformat()} to {end.isoformat()}):",
        f"Trips: {report.trip_count}",
        f"Gross: Ksh {report.gross_revenue:,.2f}",
        f"Fuel: Ksh {report.fuel_cost:,.2f}",
        f"Other expenses: Ksh {report.other_expenses + report.extra_expenses:,.2f}",
        f"Commission: Ksh {report.commission:,.2f}",
        f"Net: Ksh {report.net_profit:,.2f}",
    ]
    if report.actual_payment is not None:
        message_lines.append(f"Paid: Ksh {report.actual_payment:,.2f}")
        if report.variance is not None:
            message_lines.append(f"Balance: Ksh {report.variance:,.2f}")

    message = " ".join(message_lines)
    send_sms([report.owner_phone], message)
    return {"status": "sent", "message": message}


@router.post("/reconciliation/upload")
async def upload_reconciliation(file: UploadFile = File(...), db: Session = Depends(get_db)):
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="Unable to decode CSV file. Use UTF-8 encoding.") from exc

    reader = csv.DictReader(io.StringIO(text))
    required = {"vehicle_plate", "period_start", "period_end"}
    if not required.issubset(reader.fieldnames or []):
        raise HTTPException(
            status_code=400,
            detail=f"CSV must include headers: {', '.join(sorted(required))}",
        )

    created = 0
    updated = 0
    skipped = 0
    errors: list[str] = []

    for idx, row in enumerate(reader, start=2):
        plate = row.get("vehicle_plate", "") or ""
        if not plate.strip():
            skipped += 1
            errors.append(f"Row {idx}: missing vehicle_plate")
            continue

        norm_plate = _normalize_plate(plate)
        vehicle = (
            db.query(Vehicle)
            .filter(Vehicle.plate_number.in_({plate.strip().upper(), norm_plate}))
            .first()
        )
        if not vehicle:
            skipped += 1
            errors.append(f"Row {idx}: vehicle '{plate}' not found")
            continue

        def parse_date(field: str) -> date:
            value = row.get(field)
            if not value:
                raise ValueError(f"{field} is required")
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()

        try:
            start = parse_date("period_start")
            end = parse_date("period_end")
        except ValueError as exc:
            skipped += 1
            errors.append(f"Row {idx}: {exc}")
            continue

        fuel_cost = _parse_float(row.get("fuel_cost"))
        extra_expenses = _parse_float(row.get("extra_expenses"))
        commission_adjustment = _parse_float(row.get("commission_adjustment"))
        actual_payment = row.get("actual_payment")
        actual_payment_value = None
        if actual_payment and actual_payment.strip():
            try:
                actual_payment_value = float(actual_payment.strip())
            except ValueError:
                skipped += 1
                errors.append(f"Row {idx}: invalid actual_payment value '{actual_payment}'")
                continue

        notes = (row.get("notes") or "").strip() or None

        existing = (
            db.query(OwnerReconciliation)
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
            existing.actual_payment = actual_payment_value
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
                actual_payment=actual_payment_value,
                notes=notes,
            )
            db.add(record)
            created += 1

    db.commit()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


@router.get("/reconciliation/template")
def download_template():
    path = "data/templates/owner_reconciliation_template.csv"
    return FileResponse(path, media_type="text/csv", filename="owner_reconciliation_template.csv")
