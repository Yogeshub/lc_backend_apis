# app/routers/files_router.py
import os
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from app.auth import get_current_active_user, get_session
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import LC, Attachment
from sqlmodel import select
import shutil
from uuid import uuid4

router = APIRouter(prefix="/files", tags=["files"])

STORAGE_BASE = os.getenv("STORAGE_BASE", "./storage")
LC_STORAGE = os.path.join(STORAGE_BASE, "lc")
os.makedirs(LC_STORAGE, exist_ok=True)

@router.post("/lc/{lc_id}/upload_lc")
async def upload_lc_file(lc_id: int, file: UploadFile = File(...), user=Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    q = select(LC).where(LC.id == lc_id)
    res = await session.execute(q)
    lc = res.scalar_one_or_none()
    if not lc:
        raise HTTPException(status_code=404, detail="LC not found")
    ext = os.path.splitext(file.filename)[1]
    fname = f"{uuid4().hex}{ext}"
    lc_dir = os.path.join(LC_STORAGE, str(lc_id))
    os.makedirs(lc_dir, exist_ok=True)
    path = os.path.join(lc_dir, fname)
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    att = Attachment(lc_id=lc_id, filename=file.filename, filepath=path)
    session.add(att)
    await session.commit()
    await session.refresh(att)
    return {"attachment_id": att.id, "filename": att.filename}

@router.post("/lc/{lc_id}/upload_supporting")
async def upload_supporting_files(lc_id: int, files: list[UploadFile] = File(...), user=Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    q = select(LC).where(LC.id == lc_id)
    res = await session.execute(q)
    lc = res.scalar_one_or_none()
    if not lc:
        raise HTTPException(status_code=404, detail="LC not found")
    saved = []
    lc_dir = os.path.join(LC_STORAGE, str(lc_id), "supporting")
    os.makedirs(lc_dir, exist_ok=True)
    for file in files:
        ext = os.path.splitext(file.filename)[1]
        fname = f"{uuid4().hex}{ext}"
        path = os.path.join(lc_dir, fname)
        with open(path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        att = Attachment(lc_id=lc_id, filename=file.filename, filepath=path)
        session.add(att)
        saved.append(file.filename)
    await session.commit()
    return {"saved": saved}
