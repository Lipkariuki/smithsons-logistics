# routers/vehicles.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Vehicle
from schemas import VehicleCreate

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])


@router.get("/")
def get_vehicles(db: Session = Depends(get_db)):
    return db.query(Vehicle).all()


@router.post("/")
def create_vehicle(vehicle: VehicleCreate, db: Session = Depends(get_db)):
    existing = db.query(Vehicle).filter(
        Vehicle.plate_number == vehicle.plate_number).first()
    if existing:
        raise HTTPException(
            status_code=400, detail="Vehicle already exists with this plate number.")

    new_vehicle = Vehicle(
        plate_number=vehicle.plate_number,
        owner_id=vehicle.owner_id
    )
    db.add(new_vehicle)
    db.commit()
    db.refresh(new_vehicle)
    return new_vehicle
