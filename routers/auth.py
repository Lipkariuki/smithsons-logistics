import logging
from settings import jwt_secret

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

logger = logging.getLogger(__name__)

router = APIRouter()

# ✅ OAuth2 setup
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# ✅ JWT Config
SECRET_KEY = jwt_secret()

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# ✅ Password hashing config
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _normalize_password_length(password: str) -> str:
    if password is None:
        return ""
    # bcrypt only supports up to 72 bytes; truncating keeps compatibility with stored hashes
    return password[:72]


def verify_password(plain_password, hashed_password):
    try:
        return pwd_context.verify(_normalize_password_length(plain_password), hashed_password)
    except ValueError:
        # If bcrypt refuses the input (e.g., password longer than 72 bytes), treat as invalid credentials
        return False


def get_password_hash(password):
    return pwd_context.hash(_normalize_password_length(password))


def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    logger.debug("Access token created")
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
    if len(p) == 9 and p.startswith("7"):
        return "+254" + p
    return p

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials. Please log in again.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            logger.info("Authentication rejected: missing subject")
            raise credentials_exception
        user_id = int(user_id)
    except (JWTError, ValueError, TypeError):
        logger.info("Authentication rejected: invalid or expired token")
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not getattr(user, "is_active", True):
        logger.info("Authentication rejected: unavailable account")
        raise credentials_exception

    logger.debug("Authentication succeeded")
    return user


def require_role(required):
    """Return a dependency that ensures the current user has the required role.

    `required` may be a single role string or an iterable of allowed roles.
    """
    def role_checker(current_user: User = Depends(get_current_user)):
        # allow both a single role or a collection of roles
        try:
            is_collection = not isinstance(required, (str, bytes)) and hasattr(required, "__iter__")
        except Exception:
            is_collection = False

        if is_collection:
            if current_user.role not in required:
                raise HTTPException(status_code=403, detail="Insufficient permissions")
        else:
            if current_user.role != required:
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
    if not user or not getattr(user, "is_active", True) or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    access_token = create_access_token(data={
        "sub": str(user.id),
        "role": user.role
    })

    return {"access_token": access_token, "token_type": "bearer"}
