import os
import hashlib
from datetime import datetime, timedelta

from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.database import AsyncSessionLocal
from app.models import User


# Password hashing config
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

# JWT config
SECRET_KEY = os.getenv("JWT_SECRET", "supersecretlocalkey")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


# -------------------------
# Database session
# -------------------------
async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as s:
        yield s


# -------------------------
# Password handling
# -------------------------

def safe_password(password: str) -> str:
    """
    Convert the password into a fixed-length SHA256 hex string
    to avoid bcrypt 72-byte limitation.
    """
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_password_hash(password: str) -> str:
    """
    Hash SHA256(password) with bcrypt.
    """
    password = safe_password(password)
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Pre-hash with SHA256, then verify with bcrypt.
    """
    plain_password = safe_password(plain_password)
    return pwd_context.verify(plain_password, hashed_password)


# -------------------------
# Authentication logic
# -------------------------

async def authenticate_user(session: AsyncSession, username: str, password: str):
    q = select(User).where(User.username == username)
    res = await session.execute(q)
    user = res.scalar_one_or_none()

    if not user:
        return None

    if not verify_password(password, user.hashed_password):
        return None

    return user


# -------------------------
# JWT token generation
# -------------------------

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# -------------------------
# Current user dependencies
# -------------------------

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if not username:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    q = select(User).where(User.username == username)
    res = await session.execute(q)
    user = res.scalar_one_or_none()

    if not user:
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user)
):
    return current_user