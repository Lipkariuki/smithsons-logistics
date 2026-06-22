from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from fleet_schemas import (
    FleetDashboardOut,
    FleetDriverComplianceUpdate,
    FleetDriverOut,
    FleetNotificationOut,
    FleetNotificationRunOut,
    FleetVehicleCreate,
    FleetVehicleOut,
    FleetVehicleUpdate,
)
from models import (
    FleetDriverCompliance,
    FleetNotificationHistory,
    FleetVehicleCompliance,
    User,
    Vehicle,
)
from routers.auth import require_role
from services.fleet_notifications import run_fleet_notification_checks

router = APIRouter(
    prefix="/fleet",
    tags=["Fleet Management"],
    dependencies=[Depends(require_role("admin"))],
)


def _vehicle_out(
    vehicle: Vehicle,
    compliance: FleetVehicleCompliance | None,
    owner_name: str | None = None,
) -> FleetVehicleOut:
    current_mileage = compliance.current_mileage if compliance else None
    next_due = compliance.next_service_due_mileage if compliance else None
    return FleetVehicleOut(
        id=vehicle.id,
        registration_number=vehicle.plate_number,
        owner_id=vehicle.owner_id,
        owner_name=owner_name,
        size=vehicle.size,
        make_model=compliance.make_model if compliance else None,
        insurance_provider=compliance.insurance_provider if compliance else None,
        insurance_policy_number=compliance.insurance_policy_number if compliance else None,
        insurance_expiry_date=compliance.insurance_expiry_date if compliance else None,
        inspection_expiry_date=compliance.inspection_expiry_date if compliance else None,
        service_interval_km=compliance.service_interval_km if compliance else None,
        current_mileage=current_mileage,
        last_service_date=compliance.last_service_date if compliance else None,
        last_service_mileage=compliance.last_service_mileage if compliance else None,
        next_service_due_mileage=next_due,
        service_km_remaining=(
            next_due - current_mileage
            if next_due is not None and current_mileage is not None
            else None
        ),
    )


def _driver_out(
    driver: User,
    compliance: FleetDriverCompliance | None,
) -> FleetDriverOut:
    return FleetDriverOut(
        id=driver.id,
        name=driver.name,
        phone=driver.phone,
        email=driver.email,
        driver_license_number=(
            compliance.driver_license_number if compliance else None
        ),
        driver_license_expiry_date=(
            compliance.driver_license_expiry_date if compliance else None
        ),
    )


def _get_vehicle_or_404(db: Session, vehicle_id: int) -> Vehicle:
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle


@router.get("/vehicles", response_model=list[FleetVehicleOut])
def list_fleet_vehicles(db: Session = Depends(get_db)):
    rows = (
        db.query(Vehicle, FleetVehicleCompliance, User.name)
        .outerjoin(
            FleetVehicleCompliance,
            FleetVehicleCompliance.vehicle_id == Vehicle.id,
        )
        .outerjoin(User, User.id == Vehicle.owner_id)
        .order_by(Vehicle.plate_number)
        .all()
    )
    return [_vehicle_out(vehicle, compliance, owner_name) for vehicle, compliance, owner_name in rows]


@router.post("/vehicles", response_model=FleetVehicleOut, status_code=201)
def create_fleet_vehicle(
    payload: FleetVehicleCreate,
    db: Session = Depends(get_db),
):
    registration = payload.registration_number.strip().upper()
    existing = db.query(Vehicle).filter(Vehicle.plate_number == registration).first()
    if existing:
        raise HTTPException(status_code=400, detail="Registration number already exists")

    if payload.owner_id is not None:
        owner = db.query(User).filter(User.id == payload.owner_id).first()
        if not owner:
            raise HTTPException(status_code=400, detail="Owner not found")

    vehicle = Vehicle(
        plate_number=registration,
        owner_id=payload.owner_id,
        size=payload.size,
    )
    db.add(vehicle)
    db.flush()
    compliance = FleetVehicleCompliance(
        vehicle_id=vehicle.id,
        **payload.model_dump(
            exclude={"registration_number", "owner_id", "size"},
        ),
    )
    db.add(compliance)
    db.commit()
    db.refresh(vehicle)
    db.refresh(compliance)
    owner_name = vehicle.owner.name if vehicle.owner else None
    return _vehicle_out(vehicle, compliance, owner_name)


@router.put("/vehicles/{vehicle_id}", response_model=FleetVehicleOut)
def update_fleet_vehicle(
    vehicle_id: int,
    payload: FleetVehicleUpdate,
    db: Session = Depends(get_db),
):
    vehicle = _get_vehicle_or_404(db, vehicle_id)
    fields = payload.model_fields_set

    if "registration_number" in fields and payload.registration_number:
        registration = payload.registration_number.strip().upper()
        duplicate = (
            db.query(Vehicle)
            .filter(Vehicle.plate_number == registration, Vehicle.id != vehicle_id)
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=400, detail="Registration number already exists")
        vehicle.plate_number = registration
    if "owner_id" in fields:
        if payload.owner_id is not None:
            owner = db.query(User).filter(User.id == payload.owner_id).first()
            if not owner:
                raise HTTPException(status_code=400, detail="Owner not found")
        vehicle.owner_id = payload.owner_id
    if "size" in fields:
        vehicle.size = payload.size

    compliance = (
        db.query(FleetVehicleCompliance)
        .filter(FleetVehicleCompliance.vehicle_id == vehicle_id)
        .first()
    )
    if not compliance:
        compliance = FleetVehicleCompliance(vehicle_id=vehicle_id)
        db.add(compliance)

    compliance_fields = fields - {"registration_number", "owner_id", "size"}
    for field in compliance_fields:
        setattr(compliance, field, getattr(payload, field))

    if (
        "next_service_due_mileage" not in fields
        and ({"last_service_mileage", "service_interval_km"} & fields)
        and compliance.last_service_mileage is not None
        and compliance.service_interval_km is not None
    ):
        compliance.next_service_due_mileage = (
            compliance.last_service_mileage + compliance.service_interval_km
        )

    db.commit()
    db.refresh(vehicle)
    db.refresh(compliance)
    owner_name = vehicle.owner.name if vehicle.owner else None
    return _vehicle_out(vehicle, compliance, owner_name)


@router.get("/drivers", response_model=list[FleetDriverOut])
def list_fleet_drivers(db: Session = Depends(get_db)):
    rows = (
        db.query(User, FleetDriverCompliance)
        .outerjoin(
            FleetDriverCompliance,
            FleetDriverCompliance.driver_id == User.id,
        )
        .filter(User.role == "driver")
        .order_by(User.name)
        .all()
    )
    return [_driver_out(driver, compliance) for driver, compliance in rows]


@router.put("/drivers/{driver_id}", response_model=FleetDriverOut)
def update_driver_compliance(
    driver_id: int,
    payload: FleetDriverComplianceUpdate,
    db: Session = Depends(get_db),
):
    driver = (
        db.query(User)
        .filter(User.id == driver_id, User.role == "driver")
        .first()
    )
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    compliance = (
        db.query(FleetDriverCompliance)
        .filter(FleetDriverCompliance.driver_id == driver_id)
        .first()
    )
    if not compliance:
        compliance = FleetDriverCompliance(driver_id=driver_id)
        db.add(compliance)

    for field in payload.model_fields_set:
        setattr(compliance, field, getattr(payload, field))

    db.commit()
    db.refresh(compliance)
    return _driver_out(driver, compliance)


@router.get("/dashboard", response_model=FleetDashboardOut)
def fleet_dashboard(
    window_days: int = Query(default=30, ge=1, le=365),
    service_window_km: int = Query(default=1000, ge=0, le=100000),
    db: Session = Depends(get_db),
):
    today = date.today()
    window_end = today + timedelta(days=window_days)
    vehicles = list_fleet_vehicles(db)
    drivers = list_fleet_drivers(db)

    insurance = [
        item
        for item in vehicles
        if item.insurance_expiry_date
        and today <= item.insurance_expiry_date <= window_end
    ]
    inspections = [
        item
        for item in vehicles
        if item.inspection_expiry_date
        and today <= item.inspection_expiry_date <= window_end
    ]
    service_due = [
        item
        for item in vehicles
        if item.service_km_remaining is not None
        and item.service_km_remaining <= service_window_km
    ]
    licenses = [
        item
        for item in drivers
        if item.driver_license_expiry_date
        and today <= item.driver_license_expiry_date <= window_end
    ]
    return FleetDashboardOut(
        insurance_expiring_soon=insurance,
        inspections_expiring_soon=inspections,
        vehicles_due_for_service=service_due,
        driver_licenses_expiring_soon=licenses,
        counts={
            "insurance_expiring_soon": len(insurance),
            "inspections_expiring_soon": len(inspections),
            "vehicles_due_for_service": len(service_due),
            "driver_licenses_expiring_soon": len(licenses),
        },
    )


@router.get("/notifications", response_model=list[FleetNotificationOut])
def notification_history(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return (
        db.query(FleetNotificationHistory)
        .order_by(FleetNotificationHistory.created_at.desc())
        .limit(limit)
        .all()
    )


@router.post("/notifications/run", response_model=FleetNotificationRunOut)
def run_notifications_now(db: Session = Depends(get_db)):
    return run_fleet_notification_checks(db)
