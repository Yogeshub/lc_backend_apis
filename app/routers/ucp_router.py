# app/routers/ucp_router.py
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from app.auth import get_current_active_user, get_session
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import UCPDocument
from sqlmodel import select
import os, shutil, uuid
from app.services.ucp_loader import build_ucp_vector_db

router = APIRouter(prefix="/ucp", tags=["ucp"])
UCP_BASE = os.getenv("UCP_BASE", "./storage/ucp")
os.makedirs(UCP_BASE, exist_ok=True)

@router.post("/upload")
async def upload_ucp(file: UploadFile = File(...), name: str = Form(...), description: str = Form(None), user=Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    ext = os.path.splitext(file.filename)[1]
    ucp_id = uuid.uuid4().hex
    ucp_dir = os.path.join(UCP_BASE, ucp_id)
    os.makedirs(ucp_dir, exist_ok=True)
    pdf_path = os.path.join(ucp_dir, f"ucp{ext}")
    with open(pdf_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    # build chroma vector DB locally
    try:
        persist_dir = os.path.join(ucp_dir, "chroma")
        build_ucp_vector_db(pdf_path, persist_dir)
    except Exception as e:
        # allow upload even if vectorization fails
        print("UCP vectorization error:", e)
    u = UCPDocument(name=name, description=description or "", filepath=pdf_path, active=False)
    session.add(u)
    await session.commit()
    await session.refresh(u)
    return {"ucp_id": u.id, "name": u.name}

@router.get("/")
async def list_ucp(session: AsyncSession = Depends(get_session), user=Depends(get_current_active_user)):
    q = select(UCPDocument).order_by(UCPDocument.uploaded_at.desc())
    res = await session.execute(q)
    docs = res.scalars().all()
    return docs

@router.post("/{ucp_id}/activate")
async def activate_ucp(ucp_id: int, active: bool = True, session: AsyncSession = Depends(get_session), user=Depends(get_current_active_user)):
    q = select(UCPDocument).where(UCPDocument.id == ucp_id)
    res = await session.execute(q)
    doc = res.scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "UCP not found")
    if active:
        # deactivate others
        q2 = select(UCPDocument)
        res2 = await session.execute(q2)
        all_docs = res2.scalars().all()
        for d in all_docs:
            d.active = False
            session.add(d)
    doc.active = active
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return {"ucp_id": doc.id, "active": doc.active}
