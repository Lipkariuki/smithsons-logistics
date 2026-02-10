from __future__ import annotations

from datetime import date, datetime, time, timedelta
import os
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session, joinedload
from fpdf import FPDF

from database import get_db
from models import (
    DHLOrder,
    DHLPayslip,
    DHLPayslipExpense,
    DHLPayslipDocument,
    Expense,
    FuelExpense,
    Order,
    Trip,
    User,
    Vehicle,
)
from routers.auth import require_role
from schemas import (
    DHLOrderOut,
    DHLSummaryOut,
    DHLPayslipCreate,
    DHLPayslipOut,
    DHLPayslipUpdate,
)
from services.dhl_import import import_dhl_report

router = APIRouter(prefix="/dhl-reports", tags=["DHL Reports"])


def _default_dates(start: Optional[date], end: Optional[date]) -> tuple[date, date]:
    today = date.today()
    if start is None:
        start = today.replace(day=1)
    if end is None:
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        end = next_month - timedelta(days=1)
    if end < start:
        raise HTTPException(status_code=400, detail="end_date must be on or after start_date")
    return start, end


def _date_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    start_dt = datetime.combine(start, time.min)
    end_dt = datetime.combine(end + timedelta(days=1), time.min)
    return start_dt, end_dt


def _looks_like_fuel(description: Optional[str]) -> bool:
    if not description:
        return False
    lower = description.lower()
    return "fuel" in lower or "diesel" in lower or "petrol" in lower


def _format_currency(value: float) -> str:
    return f"Ksh {value:,.2f}"


def _latin1(text: Optional[str]) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    return text.encode("latin-1", "replace").decode("latin-1")


def _compute_default_expenses(db: Session, vehicle_id: int, start: date, end: date) -> list[dict]:
    start_dt, end_dt = _date_bounds(start, end)

    fuel_total = (
        db.query(func.coalesce(func.sum(FuelExpense.amount), 0.0))
        .join(Trip, FuelExpense.trip_id == Trip.id)
        .outerjoin(Order, Trip.order_id == Order.id)
        .filter(
            Trip.vehicle_id == vehicle_id,
            or_(
                and_(Order.date >= start_dt, Order.date < end_dt),
                and_(Order.id.is_(None), Trip.created_at >= start_dt, Trip.created_at < end_dt),
            ),
        )
        .scalar()
        or 0.0
    )

    expense_rows = (
        db.query(Expense.amount, Expense.description)
        .join(Trip, Expense.trip_id == Trip.id)
        .outerjoin(Order, Trip.order_id == Order.id)
        .filter(
            Trip.vehicle_id == vehicle_id,
            Expense.is_deleted.is_(False),
            or_(
                and_(Order.date >= start_dt, Order.date < end_dt),
                and_(Order.id.is_(None), Trip.created_at >= start_dt, Trip.created_at < end_dt),
            ),
        )
        .all()
    )
    other_total = sum(float(amount or 0.0) for amount, desc in expense_rows if not _looks_like_fuel(desc))

    return [
        {"name": "Fuel", "amount": float(fuel_total or 0.0)},
        {"name": "Trip Expenses", "amount": float(other_total or 0.0)},
    ]


def _sum_dhl_revenue(db: Session, vehicle_id: int, start: date, end: date) -> float:
    total = (
        db.query(func.coalesce(func.sum(DHLOrder.total_revenue), 0.0))
        .filter(
            DHLOrder.vehicle_id == vehicle_id,
            DHLOrder.date >= start,
            DHLOrder.date <= end,
        )
        .scalar()
    )
    return float(total or 0.0)


def _generate_payslip_pdf(payslip: DHLPayslip, vehicle: Vehicle) -> bytes:
    period_label = f"{payslip.period_start:%Y-%m-%d} to {payslip.period_end:%Y-%m-%d}"
    generated_on = datetime.utcnow().strftime("%Y-%m-%d")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    logo_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "assets", "smithsons-logo.svg")
    )
    try:
        pdf.image(logo_path, x=14, y=12, w=12, h=12)
    except Exception:
        pass

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 8, "Smithsons Logistics", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "Powering Every Trip. Empowering Every Partner.", ln=True, align="C")
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, _latin1("DHL Partner Payslip"), ln=True, align="C")
    pdf.set_draw_color(60, 60, 60)
    pdf.set_line_width(0.5)
    pdf.line(15, 34, 195, 34)

    pdf.ln(6)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _latin1(f"Generated: {generated_on}"), ln=True, align="R")

    owner = vehicle.owner
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, _latin1(f"Owner: {owner.name if owner else 'N/A'}"), ln=True)
    pdf.cell(0, 6, _latin1(f"Vehicle: {vehicle.plate_number}"), ln=True)
    pdf.cell(0, 6, _latin1(f"Period: {period_label}"), ln=True)

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Earnings", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(140, 7, "DHL Revenue", 1)
    pdf.cell(0, 7, _format_currency(payslip.total_revenue), 1, ln=True, align="R")

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Deductions", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(140, 7, f"Commission ({payslip.commission_rate * 100:.2f}%)", 1)
    pdf.cell(0, 7, _format_currency(payslip.commission_amount), 1, ln=True, align="R")
    for item in payslip.expenses:
        pdf.cell(140, 7, _latin1(item.name), 1)
        pdf.cell(0, 7, _format_currency(item.amount), 1, ln=True, align="R")

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(140, 8, "Total Deductions", 1)
    pdf.cell(0, 8, _format_currency(payslip.total_expenses + payslip.commission_amount), 1, ln=True, align="R")
    pdf.cell(140, 8, "Net Payable", 1)
    pdf.cell(0, 8, _format_currency(payslip.net_pay), 1, ln=True, align="R")

    pdf.ln(10)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, _latin1("Prepared by: ______________________"), ln=True)
    pdf.cell(0, 6, _latin1("Approved by: ______________________"), ln=True)

    output = pdf.output(dest="S")
    if isinstance(output, str):
        return output.encode("latin1")
    return output


@router.post("/upload")
def upload_dhl_report(
    file: UploadFile = File(...),
    replace: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    result = import_dhl_report(db, content, replace=replace)
    return {
        "period_start": result.period_start,
        "period_end": result.period_end,
        "inserted": result.inserted,
        "unmatched_vehicles": result.unmatched,
    }


@router.get("/orders", response_model=list[DHLOrderOut])
def list_dhl_orders(
    owner_id: Optional[int] = Query(None),
    vehicle_id: Optional[int] = Query(None),
    vehicle_plate: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    start, end = _default_dates(start_date, end_date)

    query = db.query(DHLOrder)
    if vehicle_id:
        query = query.filter(DHLOrder.vehicle_id == vehicle_id)
    if vehicle_plate:
        plate = vehicle_plate.strip().replace(" ", "").upper()
        query = query.filter(DHLOrder.truck_plate == plate)
    if owner_id:
        query = query.join(Vehicle, DHLOrder.vehicle_id == Vehicle.id).filter(Vehicle.owner_id == owner_id)

    query = query.filter(DHLOrder.date >= start, DHLOrder.date <= end)
    return query.order_by(DHLOrder.date.asc()).all()


@router.get("/summary", response_model=list[DHLSummaryOut])
def dhl_summary(
    owner_id: Optional[int] = Query(None),
    vehicle_id: Optional[int] = Query(None),
    vehicle_plate: Optional[str] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    start, end = _default_dates(start_date, end_date)

    query = (
        db.query(
            DHLOrder.vehicle_id,
            DHLOrder.truck_plate,
            func.count(DHLOrder.id).label("order_count"),
            func.coalesce(func.sum(DHLOrder.distribution_cost), 0.0).label("distribution_cost"),
            func.coalesce(func.sum(DHLOrder.offloading_cost), 0.0).label("offloading_cost"),
            func.coalesce(func.sum(DHLOrder.total_revenue), 0.0).label("total_revenue"),
        )
        .filter(DHLOrder.date >= start, DHLOrder.date <= end)
        .group_by(DHLOrder.vehicle_id, DHLOrder.truck_plate)
    )

    if vehicle_id:
        query = query.filter(DHLOrder.vehicle_id == vehicle_id)
    if vehicle_plate:
        plate = vehicle_plate.strip().replace(" ", "").upper()
        query = query.filter(DHLOrder.truck_plate == plate)

    rows = query.all()

    vehicle_ids = [row.vehicle_id for row in rows if row.vehicle_id]
    vehicles = {
        v.id: v for v in db.query(Vehicle).options(joinedload(Vehicle.owner)).filter(Vehicle.id.in_(vehicle_ids)).all()
    }

    payslips = {
        p.vehicle_id: p
        for p in db.query(DHLPayslip)
        .filter(
            DHLPayslip.period_start == start,
            DHLPayslip.period_end == end,
        )
        .all()
    }

    results = []
    for row in rows:
        vehicle = vehicles.get(row.vehicle_id)
        owner = vehicle.owner if vehicle else None
        payslip = payslips.get(row.vehicle_id) if row.vehicle_id else None
        if owner_id and (not owner or owner.id != owner_id):
            continue
        results.append(
            DHLSummaryOut(
                vehicle_id=row.vehicle_id,
                plate_number=row.truck_plate,
                owner_id=owner.id if owner else None,
                owner_name=owner.name if owner else None,
                owner_phone=owner.phone if owner else None,
                order_count=row.order_count,
                distribution_cost=float(row.distribution_cost or 0.0),
                offloading_cost=float(row.offloading_cost or 0.0),
                total_revenue=float(row.total_revenue or 0.0),
                total_expenses=payslip.total_expenses if payslip else None,
                net_pay=payslip.net_pay if payslip else None,
            )
        )

    results.sort(key=lambda item: (item.owner_name or "", item.plate_number))
    return results


@router.post("/payslips", response_model=DHLPayslipOut)
def create_payslip(
    payload: DHLPayslipCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    start, end = _default_dates(payload.period_start, payload.period_end)
    vehicle = db.query(Vehicle).options(joinedload(Vehicle.owner)).filter(Vehicle.id == payload.vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    revenue = _sum_dhl_revenue(db, payload.vehicle_id, start, end)
    if revenue <= 0:
        raise HTTPException(status_code=404, detail="No DHL revenue found for the selected period")

    commission_rate = payload.commission_rate if payload.commission_rate is not None else 0.07
    commission_amount = revenue * commission_rate

    expenses = payload.expenses or _compute_default_expenses(db, payload.vehicle_id, start, end)
    total_expenses = sum(float(item.amount) if hasattr(item, "amount") else float(item["amount"]) for item in expenses)
    net_pay = revenue - commission_amount - total_expenses

    payslip = db.query(DHLPayslip).filter(
        DHLPayslip.vehicle_id == payload.vehicle_id,
        DHLPayslip.period_start == start,
        DHLPayslip.period_end == end,
    ).first()

    if payslip is None:
        payslip = DHLPayslip(
            vehicle_id=payload.vehicle_id,
            period_start=start,
            period_end=end,
            total_revenue=revenue,
            commission_rate=commission_rate,
            commission_amount=commission_amount,
            total_expenses=total_expenses,
            net_pay=net_pay,
        )
        db.add(payslip)
        db.flush()
    else:
        payslip.total_revenue = revenue
        payslip.commission_rate = commission_rate
        payslip.commission_amount = commission_amount
        payslip.total_expenses = total_expenses
        payslip.net_pay = net_pay
        payslip.expenses.clear()

    for item in expenses:
        name = item.name if hasattr(item, "name") else item["name"]
        amount = item.amount if hasattr(item, "amount") else item["amount"]
        payslip.expenses.append(DHLPayslipExpense(name=name, amount=amount))

    db.commit()
    db.refresh(payslip)
    return payslip


@router.get("/payslips", response_model=list[DHLPayslipOut])
def list_payslips(
    owner_id: Optional[int] = Query(None),
    vehicle_id: Optional[int] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    start, end = _default_dates(start_date, end_date)
    query = db.query(DHLPayslip).options(joinedload(DHLPayslip.expenses))
    if vehicle_id:
        query = query.filter(DHLPayslip.vehicle_id == vehicle_id)
    query = query.filter(DHLPayslip.period_start == start, DHLPayslip.period_end == end)

    payslips = query.all()
    if owner_id:
        vehicle_ids = [p.vehicle_id for p in payslips]
        owners = {
            v.id: v.owner_id
            for v in db.query(Vehicle).filter(Vehicle.id.in_(vehicle_ids)).all()
        }
        payslips = [p for p in payslips if owners.get(p.vehicle_id) == owner_id]
    return payslips


@router.get("/payslips/{payslip_id}", response_model=DHLPayslipOut)
def get_payslip(
    payslip_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    payslip = (
        db.query(DHLPayslip)
        .options(
            joinedload(DHLPayslip.expenses),
            joinedload(DHLPayslip.document),
            joinedload(DHLPayslip.vehicle),
        )
        .filter(DHLPayslip.id == payslip_id)
        .first()
    )
    if not payslip:
        raise HTTPException(status_code=404, detail="Payslip not found")
    return payslip


@router.put("/payslips/{payslip_id}", response_model=DHLPayslipOut)
def update_payslip(
    payslip_id: int,
    payload: DHLPayslipUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    payslip = (
        db.query(DHLPayslip)
        .options(joinedload(DHLPayslip.expenses))
        .filter(DHLPayslip.id == payslip_id)
        .first()
    )
    if not payslip:
        raise HTTPException(status_code=404, detail="Payslip not found")

    if payload.commission_rate is not None:
        payslip.commission_rate = payload.commission_rate

    if payload.expenses is not None:
        payslip.expenses.clear()
        for item in payload.expenses:
            payslip.expenses.append(DHLPayslipExpense(name=item.name, amount=item.amount))

    payslip.commission_amount = payslip.total_revenue * payslip.commission_rate
    payslip.total_expenses = sum(item.amount for item in payslip.expenses)
    payslip.net_pay = payslip.total_revenue - payslip.commission_amount - payslip.total_expenses
    if payslip.document:
        payslip.document.pdf_bytes = _generate_payslip_pdf(payslip, payslip.vehicle)
    db.commit()
    db.refresh(payslip)
    return payslip


@router.get("/payslips/{payslip_id}/pdf")
def download_payslip_pdf(
    payslip_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    payslip = (
        db.query(DHLPayslip)
        .options(
            joinedload(DHLPayslip.expenses),
            joinedload(DHLPayslip.document),
            joinedload(DHLPayslip.vehicle).joinedload(Vehicle.owner),
        )
        .filter(DHLPayslip.id == payslip_id)
        .first()
    )
    if not payslip:
        raise HTTPException(status_code=404, detail="Payslip not found")

    if not payslip.vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found for payslip")

    if payslip.document:
        pdf_bytes = bytes(payslip.document.pdf_bytes)
    else:
        pdf_bytes = _generate_payslip_pdf(payslip, payslip.vehicle)
    pdf_bytes = bytes(pdf_bytes)
    filename = f"dhl_payslip_{payslip.vehicle.plate_number}_{payslip.period_start}.pdf"
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/payslips/{payslip_id}/send")
def send_payslip(
    payslip_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    payslip = (
        db.query(DHLPayslip)
        .options(joinedload(DHLPayslip.expenses), joinedload(DHLPayslip.vehicle).joinedload(Vehicle.owner))
        .filter(DHLPayslip.id == payslip_id)
        .first()
    )
    if not payslip:
        raise HTTPException(status_code=404, detail="Payslip not found")
    if not payslip.vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found for payslip")

    pdf_bytes = _generate_payslip_pdf(payslip, payslip.vehicle)
    if payslip.document:
        payslip.document.pdf_bytes = pdf_bytes
    else:
        payslip.document = DHLPayslipDocument(pdf_bytes=pdf_bytes)
    payslip.sent_at = datetime.utcnow()

    db.commit()
    return {"message": "Payslip stored and marked as sent"}
