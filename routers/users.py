from fastapi import APIRouter, Depends, HTTPException  # ✅ now includes HTTPException

from sqlalchemy.orm import Session
from typing import List
from passlib.context import CryptContext
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
from models import User
from database import get_db
from schemas import UserCreate, UserOut
from routers.auth import get_current_user, require_role



router = APIRouter(prefix="/users", tags=["Users"])

@router.get("/me", response_model=UserOut)
def get_my_user(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/", response_model=List[UserOut])
def list_users(role: str = None, db: Session = Depends(get_db)):
    query = db.query(User)
    if role:
        roles = [r.strip() for r in role.split(",") if r.strip()]
        if roles:
            if len(roles) == 1:
                query = query.filter(User.role == roles[0])
            else:
                query = query.filter(User.role.in_(roles))
    return query.all()

@router.post("/", response_model=UserOut)
def create_user(user: UserCreate, db: Session = Depends(get_db), current_user: User = Depends(require_role("admin"))):
    existing = db.query(User).filter(User.phone == user.phone).first()
    if existing:
        raise HTTPException(status_code=400, detail="Phone number already registered")

    hashed_password = pwd_context.hash(user.password)

    db_user = User(
        name=user.name,
        email=user.email,
        phone=user.phone,
        password_hash=hashed_password,
        role=user.role
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user
