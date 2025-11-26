# app/routers/auth_router.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from datetime import timedelta
from app.auth import authenticate_user, create_access_token, get_password_hash, get_session,get_current_user
from app.schemas import Token, UserCreate, UserRead
from sqlmodel import select
from app.models import User
from sqlalchemy.ext.asyncio import AsyncSession


router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), session: AsyncSession = Depends(get_session)):
    user = await authenticate_user(session, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    access_token_expires = timedelta(minutes=60*24)
    access_token = create_access_token({"sub": user.username}, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/create", response_model=UserRead)
async def create_user(payload: UserCreate, session: AsyncSession = Depends(get_session)):
    q = select(User).where(User.username == payload.username)
    res = await session.execute(q)
    existing = res.scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="User already exists")
    user = User(username=payload.username, hashed_password=get_password_hash(payload.password), full_name=payload.full_name or "",role=payload.role or "read", is_admin=False)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user



@router.get("/me", response_model=UserRead)
async def read_current_user(current_user: User = Depends(get_current_user)):
    # return user info (UserRead should include id, username, full_name, is_admin, role)
    return current_user