from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from database import get_db
from models import Vehicle, User
from schemas import VehicleCreate, VehicleOut, VehicleUpdate
from routers.auth import get_current_user

FLEET_MANAGER_PHONE = "+254722760992"


def _normalize_phone(phone: Optional[str]) -> str:
    if not phone:
        return ""
    p = phone.strip().replace(" ", "").replace("-", "")
    if p.startswith("+"):
        return p
    if p.startswith("0") and len(p) == 10:
        return "+254" + p[1:]
    if p.startswith("254"):
        return "+" + p
    return p


def ensure_fleet_manager(current_user: User = Depends(get_current_user)) -> User:
    if _normalize_phone(current_user.phone) != FLEET_MANAGER_PHONE:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return current_user

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])

# ✅ Fetch all vehicles
@router.get("/", response_model=list[VehicleOut])
def get_vehicles(db: Session = Depends(get_db)):
    return db.query(Vehicle).all()

# ✅ Create new vehicle (with size)
@router.post("/", response_model=VehicleOut)
def create_vehicle(
    vehicle: VehicleCreate,
    db: Session = Depends(get_db),
    _: User = Depends(ensure_fleet_manager),
):
    print("🚛 Incoming vehicle payload:", vehicle)

    existing = db.query(Vehicle).filter(
        Vehicle.plate_number == vehicle.plate_number).first()
    if existing:
        raise HTTPException(
            status_code=400, detail="Vehicle already exists with this plate number.")

    new_vehicle = Vehicle(
        plate_number=vehicle.plate_number,
        owner_id=vehicle.owner_id,
        size=vehicle.size
    )
    print("🔧 Saving vehicle to DB with size:", new_vehicle.size)

    db.add(new_vehicle)
    db.commit()
    db.refresh(new_vehicle)
    return new_vehicle


# ✅ Fetch one vehicle by ID (used by frontend on vehicle select)
@router.get("/{vehicle_id}")
def get_vehicle(vehicle_id: int, db: Session = Depends(get_db)):
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    return {
        "id": vehicle.id,
        "plate_number": vehicle.plate_number,
        "size": vehicle.size,
        "owner_id": vehicle.owner_id
    }


@router.put("/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(
    vehicle_id: int,
    payload: VehicleUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(ensure_fleet_manager),
):
    vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    if payload.plate_number and payload.plate_number != vehicle.plate_number:
        existing = (
            db.query(Vehicle)
            .filter(Vehicle.plate_number == payload.plate_number)
            .first()
        )
        if existing:
            raise HTTPException(status_code=400, detail="Plate number already in use")
        vehicle.plate_number = payload.plate_number

    if payload.owner_id is not None:
        vehicle.owner_id = payload.owner_id

    if payload.size is not None:
        vehicle.size = payload.size

    db.commit()
    db.refresh(vehicle)
    return vehicle
