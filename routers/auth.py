from dotenv import load_dotenv
import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import or_
from jose import JWTError, jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta

from models import User
from schemas import Token
from database import get_db

# ✅ Load environment variables
load_dotenv()

router = APIRouter()

# ✅ OAuth2 setup
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# ✅ JWT Config
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "default_if_missing")
print("✅ Loaded SECRET_KEY:", SECRET_KEY)  # Debug print

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# ✅ Password hashing config
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password):
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    print("✅ Created JWT payload:", to_encode)  # Debug JWT creation
    return encoded


def normalize_ke_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    p = phone.strip().replace(" ", "").replace("-", "")
    if p.startswith("+254"):
        return p
    if p.startswith("254"):
        return "+" + p
    if p.startswith("0") and len(p) == 10:
        return "+254" + p[1:]
    return p

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    print("🪪 Received token:", token)  # Debug incoming token

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        print("✅ Decoded JWT payload:", payload)  # Debug decoded token
        user_id: str = payload.get("sub")
        if user_id is None:
            print("❌ Token missing 'sub' field")
            raise credentials_exception
    except JWTError as e:
        print("❌ JWT decoding error:", str(e))  # Debug JWT errors
        raise credentials_exception

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        print("❌ No user found with ID:", user_id)
        raise credentials_exception

    print("✅ Authenticated user:", user.name, "| Role:", user.role)
    return user


def require_role(role: str):
    def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role != role:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return role_checker


@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    raw = form_data.username
    normalized = normalize_ke_phone(raw)
    user = (
        db.query(User)
        .filter(
            or_(
                User.phone == raw,
                User.phone == normalized
            )
        )
        .first()
    )
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(data={
        "sub": str(user.id),
        "role": user.role
    })

    return {"access_token": access_token, "token_type": "bearer"}
