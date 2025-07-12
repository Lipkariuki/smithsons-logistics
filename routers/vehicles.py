from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Vehicle
from schemas import VehicleCreate, VehicleOut

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])

# ✅ Fetch all vehicles
@router.get("/", response_model=list[VehicleOut])
def get_vehicles(db: Session = Depends(get_db)):
    return db.query(Vehicle).all()

# ✅ Create new vehicle (with size)
@router.post("/", response_model=VehicleOut)
def create_vehicle(vehicle: VehicleCreate, db: Session = Depends(get_db)):
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
