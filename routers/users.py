from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
from models import User
from database import get_db
from schemas import UserCreate, UserOut, UserUpdate
from routers.auth import get_current_user, require_role

router = APIRouter(prefix="/users", tags=["Users"])


def _normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _ensure_unique_user_fields(db: Session, phone: str | None, email: str | None, user_id: int | None = None):
    query = db.query(User)
    if user_id is not None:
        query = query.filter(User.id != user_id)

    if phone:
        existing = query.filter(User.phone == phone).first()
        if existing:
            raise HTTPException(status_code=400, detail="Phone number already registered")

    if email:
        existing = query.filter(User.email == email).first()
        if existing:
            raise HTTPException(status_code=400, detail="Email already registered")

@router.get("/me", response_model=UserOut)
def get_my_user(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/", response_model=List[UserOut])
def list_users(
    role: str = None,
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(User)
    if role:
        roles = [r.strip() for r in role.split(",") if r.strip()]
        if roles:
            if len(roles) == 1:
                query = query.filter(User.role == roles[0])
            else:
                query = query.filter(User.role.in_(roles))
    if include_inactive:
        if current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Insufficient permissions")
    else:
        query = query.filter(User.is_active.is_(True))
    return query.order_by(User.name.asc()).all()

@router.post("/", response_model=UserOut)
def create_user(user: UserCreate, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    phone = _normalize_optional_string(user.phone)
    email = _normalize_optional_string(user.email)
    name = _normalize_optional_string(user.name)
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not phone:
        raise HTTPException(status_code=400, detail="Phone number is required")

    _ensure_unique_user_fields(db, phone=phone, email=email)

    hashed_password = pwd_context.hash(user.password)

    db_user = User(
        name=name,
        email=email,
        phone=phone,
        password_hash=hashed_password,
        role=user.role,
        is_active=True,
        deleted_at=None,
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.post("/drivers", response_model=UserOut)
def create_driver(
    user: UserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    driver_payload = user.model_copy(update={"role": "driver"})
    return create_user(user=driver_payload, db=db, current_user=current_user)


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    db_user = db.query(User).filter(User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    if payload.name is not None:
        name = _normalize_optional_string(payload.name)
        if not name:
            raise HTTPException(status_code=400, detail="Name is required")
        db_user.name = name

    if payload.phone is not None:
        phone = _normalize_optional_string(payload.phone)
        if not phone:
            raise HTTPException(status_code=400, detail="Phone number is required")
        _ensure_unique_user_fields(db, phone=phone, email=None, user_id=user_id)
        db_user.phone = phone

    if payload.email is not None:
        email = _normalize_optional_string(payload.email)
        _ensure_unique_user_fields(db, phone=None, email=email, user_id=user_id)
        db_user.email = email

    if payload.password is not None:
        if not payload.password.strip():
            raise HTTPException(status_code=400, detail="Password cannot be blank")
        db_user.password_hash = pwd_context.hash(payload.password)

    if payload.role is not None:
        db_user.role = payload.role

    if payload.is_active is not None:
        db_user.is_active = payload.is_active
        db_user.deleted_at = None if payload.is_active else (db_user.deleted_at or datetime.utcnow())

    db.commit()
    db.refresh(db_user)
    return db_user


@router.put("/drivers/{driver_id}", response_model=UserOut)
def update_driver(
    driver_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    driver = db.query(User).filter(User.id == driver_id, User.role == "driver").first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    driver_payload = payload.model_copy(update={"role": "driver"})
    return update_user(user_id=driver_id, payload=driver_payload, db=db, current_user=current_user)


@router.delete("/drivers/{driver_id}", response_model=UserOut)
def deactivate_driver(
    driver_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    driver = db.query(User).filter(User.id == driver_id, User.role == "driver").first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    if not driver.is_active:
        return driver

    driver.is_active = False
    driver.deleted_at = datetime.utcnow()
    db.commit()
    db.refresh(driver)
    return driver
