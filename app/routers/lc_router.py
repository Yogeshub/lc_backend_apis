# app/routers/lc_router.py
from fastapi import APIRouter, Depends, HTTPException, Form
from app.auth import get_current_active_user, get_session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select
from app.models import LC, Attachment, ValidationResult, UCPDocument
from app.schemas import LCCreate, LCRead
from app.services.pdf_reader import read_pdf_text
from app.services.agent_services import run_lc_extractor, run_doc_extractor, run_discrepancy_check, run_compliance_check
import os, json

router = APIRouter(prefix="/lc", tags=["lc"])


def clean_ai_json(model_output: str):
    """
    Removes ```json fences and parses the cleaned string into a dict.
    """
    if not model_output:
        return {}

    # Remove markdown fences
    cleaned = (
        model_output.replace("```json", "")
                    .replace("```", "")
                    .strip()
    )

    # Attempt JSON parsing
    try:
        return json.loads(cleaned)
    except Exception as e:
        # Return raw output so frontend knows something is wrong
        return {
            "error": "Failed to parse JSON",
            "raw": cleaned,
            "exception": str(e),
        }


@router.post("/", response_model=LCRead)
async def create_lc(payload: LCCreate, session: AsyncSession = Depends(get_session), user=Depends(get_current_active_user)):
    lc = LC(lc_no=payload.lc_no, status="created")
    session.add(lc)
    await session.commit()
    await session.refresh(lc)
    return lc


@router.get("/", response_model=list[LCRead])
async def list_lcs(session: AsyncSession = Depends(get_session), user=Depends(get_current_active_user)):
    q = select(LC).order_by(LC.created_at.desc())
    res = await session.execute(q)
    lcs = res.scalars().all()
    return lcs


@router.get("/{lc_id}")
async def get_lc_detail(lc_id: int, session: AsyncSession = Depends(get_session), user=Depends(get_current_active_user)):
    q = select(LC).where(LC.id == lc_id)
    res = await session.execute(q)
    lc = res.scalar_one_or_none()
    if not lc:
        raise HTTPException(404, "LC not found")
    q2 = select(Attachment).where(Attachment.lc_id == lc_id)
    res2 = await session.execute(q2)
    attachments = res2.scalars().all()
    q3 = select(ValidationResult).where(ValidationResult.lc_id == lc_id)
    res3 = await session.execute(q3)
    validations = res3.scalars().all()
    return {"lc": lc, "attachments": attachments, "validations": validations}


# @router.post("/{lc_id}/extract_lc")
# async def extract_lc_endpoint(lc_id: int, file_path: str = Form(None), session: AsyncSession = Depends(get_session), user=Depends(get_current_active_user)):
#     """
#     If file_path is provided, read that PDF; otherwise try to pick a first attachment for LC.
#     """
#     q = select(LC).where(LC.id == lc_id)
#     res = await session.execute(q)
#     lc = res.scalar_one_or_none()
#     if not lc:
#         raise HTTPException(404, "LC not found")
#     # pick attachment if file_path not provided
#     if not file_path:
#         q2 = select(Attachment).where(Attachment.lc_id == lc_id)
#         res2 = await session.execute(q2)
#         att = res2.scalars().first()
#         if not att:
#             raise HTTPException(400, "No LC file attached. Upload a PDF first.")
#         file_path = att.filepath
#     text = read_pdf_text(file_path)
#     extracted = run_lc_extractor(text)
#     lc.extracted_json = json.dumps(extracted)
#     lc.status = "extracted"
#     session.add(lc)
#     await session.commit()
#     await session.refresh(lc)
#     return {"lc_id": lc.id, "extracted": extracted}


@router.post("/{lc_id}/extract_lc")
async def extract_lc_endpoint(
    lc_id: int,
    file_path: str = Form(None),
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_active_user),
):
    """
    Extract structured LC data from the attached LC PDF.
    If file_path is not provided, it uses the first LC attachment.
    """

    q = select(LC).where(LC.id == lc_id)
    res = await session.execute(q)
    lc = res.scalar_one_or_none()

    if not lc:
        raise HTTPException(404, "LC not found")

    if not file_path:
        q2 = select(Attachment).where(Attachment.lc_id == lc_id)
        res2 = await session.execute(q2)
        att = res2.scalars().first()

        if not att:
            raise HTTPException(400, "No LC file attached. Upload a PDF first.")

        file_path = att.filepath
    text = read_pdf_text(file_path)

    raw_output = run_lc_extractor(text)
    model_text = raw_output.get("raw_output", "")
    cleaned = (
        model_text.replace("```json", "")
                  .replace("```", "")
                  .strip()
    )
    try:
        structured_data = json.loads(cleaned)
    except Exception as e:
        structured_data = {
            "error": "Failed to parse LC JSON output",
            "raw": cleaned,
            "exception": str(e),
        }
    lc.extracted_json = json.dumps(structured_data)
    lc.status = "extracted"
    session.add(lc)
    await session.commit()
    await session.refresh(lc)
    return {
        "lc_id": lc.id,
        "extracted": structured_data
    }


# @router.post("/{lc_id}/extract_supporting")
# async def extract_supporting_docs(lc_id: int, session: AsyncSession = Depends(get_session), user=Depends(get_current_active_user)):
#     q = select(Attachment).where(Attachment.lc_id == lc_id)
#     res = await session.execute(q)
#     attachments = res.scalars().all()
#     results = []
#     for att in attachments:
#         # skip the main LC if present; heuristics: filename contains lc or letter
#         if "lc" in att.filename.lower() and att.filepath.endswith(".pdf"):
#             continue
#         text = read_pdf_text(att.filepath)
#         parsed = run_doc_extractor(text)
#         results.append({"file_name": att.filename, "data": parsed})
#     return {"results": results}


@router.post("/{lc_id}/extract_supporting")
async def extract_supporting_docs(
    lc_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_active_user)
):
    q = select(Attachment).where(Attachment.lc_id == lc_id)
    res = await session.execute(q)
    attachments = res.scalars().all()

    results = []

    for att in attachments:

        # Skip the main LC PDF
        if "lc" in att.filename.lower() and att.filepath.endswith(".pdf"):
            continue

        text = read_pdf_text(att.filepath)

        # Run supporting doc extractor
        parsed_output = run_doc_extractor(text)

        # Expecting:
        # parsed_output = { "raw_output": "```json {..} ```" }
        raw_str = parsed_output.get("raw_output", "")

        # Clean & convert to structured dict
        structured = clean_ai_json(raw_str)

        results.append({
            "file_name": att.filename,
            "data": structured
        })

    return {"results": results}


# @router.post("/{lc_id}/discrepancy")
# async def run_discrepancy(lc_id: int, session: AsyncSession = Depends(get_session), user=Depends(get_current_active_user)):
#     # load LC
#     q = select(LC).where(LC.id == lc_id)
#     res = await session.execute(q)
#     lc = res.scalar_one_or_none()
#     if not lc or not lc.extracted_json:
#         raise HTTPException(400, "LC not extracted")
#     lc_data = json.loads(lc.extracted_json)
#     # gather parsed supporting docs: for now call extract_supporting to get parsed results
#     # NOTE: The client should first call /extract_supporting and pass the parsed data if it wants
#     # Here we will re-run doc extractor for attachments
#     q2 = select(Attachment).where(Attachment.lc_id == lc_id)
#     res2 = await session.execute(q2)
#     attachments = res2.scalars().all()
#     doc_results = []
#     for att in attachments:
#         if "lc" in att.filename.lower() and att.filepath.endswith(".pdf"):
#             continue
#         text = read_pdf_text(att.filepath)
#         parsed = run_doc_extractor(text)
#         doc_results.append({"file_name": att.filename, "data": parsed})
#     tables = run_discrepancy_check(lc_data, doc_results)
#     return {"discrepancy_tables": tables}


@router.post("/{lc_id}/discrepancy")
async def run_discrepancy(
    lc_id: int,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_active_user)
):
    # Load LC record
    q = select(LC).where(LC.id == lc_id)
    res = await session.execute(q)
    lc = res.scalar_one_or_none()
    if not lc or not lc.extracted_json:
        raise HTTPException(400, "LC not extracted")

    lc_data = json.loads(lc.extracted_json)

    # Collect supporting docs
    q2 = select(Attachment).where(Attachment.lc_id == lc_id)
    res2 = await session.execute(q2)
    attachments = res2.scalars().all()

    doc_results = []

    for att in attachments:
        # Skip main LC PDF
        if "lc" in att.filename.lower() and att.filepath.endswith(".pdf"):
            continue

        text = read_pdf_text(att.filepath)

        # Extract supporting doc
        parsed_output = run_doc_extractor(text)

        # raw_output may contain ```json ... ```
        raw_str = parsed_output.get("raw_output", "")

        # Clean markdown → structured JSON
        structured = clean_ai_json(raw_str)

        doc_results.append({
            "file_name": att.filename,
            "data": structured
        })

    # Run discrepancy check USING CLEANED STRUCTURED DATA
    tables = run_discrepancy_check(lc_data, doc_results)

    return {"discrepancy_tables": tables}


# @router.post("/{lc_id}/compliance")
# async def run_compliance(lc_id: int, ucp_id: int | None = None, session: AsyncSession = Depends(get_session), user=Depends(get_current_active_user)):
#     q = select(LC).where(LC.id == lc_id)
#     res = await session.execute(q)
#     lc = res.scalar_one_or_none()
#     if not lc or not lc.extracted_json:
#         raise HTTPException(400, "LC not extracted")
#     lc_data = json.loads(lc.extracted_json)
#     # build support docs parsed
#     q2 = select(Attachment).where(Attachment.lc_id == lc_id)
#     res2 = await session.execute(q2)
#     attachments = res2.scalars().all()
#     supporting_paths = [a.filepath for a in attachments]
#     # choose ucp persist dir
#     ucp_dir = None
#     if ucp_id:
#         q3 = select(UCPDocument).where(UCPDocument.id == ucp_id)
#         res3 = await session.execute(q3)
#         ucp = res3.scalar_one_or_none()
#         if ucp:
#             # persist dir uses id
#             ucp_dir = os.path.join("storage", "ucp", str(ucp.id))
#     else:
#         # find active UCP
#         qact = select(UCPDocument).where(UCPDocument.active == True)
#         resact = await session.execute(qact)
#         ucp = resact.scalars().first()
#         if ucp:
#             ucp_dir = os.path.join("storage", "ucp", str(ucp.id))
#     # run compliance
#     # For discrepancy_tables we will run discrepancy check to provide context
#     # Simple approach: call run_discrepancy_check again
#     doc_results = []
#     from app.services.agent_services import run_doc_extractor
#     for a in attachments:
#         if "lc" in a.filename.lower():
#             continue
#         text = read_pdf_text(a.filepath)
#         parsed = run_doc_extractor(text)
#         doc_results.append({"file_name": a.filename, "data": parsed})
#     from app.services.agent_services import run_discrepancy_check, run_compliance_check
#     tables = run_discrepancy_check(json.loads(lc.extracted_json), doc_results)
#     compliance_result = run_compliance_check(json.loads(lc.extracted_json), tables, ucp_dir, None, supporting_paths)
#     # store validation result
#     vr = ValidationResult(lc_id=lc.id, valid=(compliance_result.get("overall_status", "").lower()=="accepted"), summary=str(compliance_result), raw=str(compliance_result))
#     session.add(vr)
#     lc.status = compliance_result.get("overall_status", lc.status)
#     session.add(lc)
#     await session.commit()
#     await session.refresh(vr)
#     return {"compliance_result": compliance_result}


@router.post("/{lc_id}/compliance")
async def run_compliance(
    lc_id: int,
    ucp_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    user=Depends(get_current_active_user)
):
    # Load LC record
    q = select(LC).where(LC.id == lc_id)
    res = await session.execute(q)
    lc = res.scalar_one_or_none()
    if not lc or not lc.extracted_json:
        raise HTTPException(400, "LC not extracted")

    lc_data = json.loads(lc.extracted_json)

    # Collect supporting attachments
    q2 = select(Attachment).where(Attachment.lc_id == lc_id)
    res2 = await session.execute(q2)
    attachments = res2.scalars().all()
    supporting_paths = [a.filepath for a in attachments]

    # Determine UCP directory
    ucp_dir = None
    if ucp_id:
        q3 = select(UCPDocument).where(UCPDocument.id == ucp_id)
        res3 = await session.execute(q3)
        ucp = res3.scalar_one_or_none()
        if ucp:
            ucp_dir = os.path.join("storage", "ucp", str(ucp.id))
    else:
        qact = select(UCPDocument).where(UCPDocument.active == True)
        resact = await session.execute(qact)
        ucp = resact.scalars().first()
        if ucp:
            ucp_dir = os.path.join("storage", "ucp", str(ucp.id))

    # Extract supporting documents with markdown fix
    doc_results = []
    from app.services.agent_services import run_doc_extractor

    for att in attachments:
        # Skip the main LC
        if "lc" in att.filename.lower() and att.filepath.endswith(".pdf"):
            continue

        text = read_pdf_text(att.filepath)
        parsed = run_doc_extractor(text)

        # NORMALIZE MARKDOWN → JSON
        raw_output = parsed.get("raw_output", "")
        structured = clean_ai_json(raw_output)

        doc_results.append({
            "file_name": att.filename,
            "data": structured
        })

    # Run discrepancy & compliance
    from app.services.agent_services import run_discrepancy_check, run_compliance_check
    
    tables = run_discrepancy_check(lc_data, doc_results)

    compliance_result = run_compliance_check(
        lc_data,
        tables,
        ucp_dir,
        None,
        supporting_paths
    )

    # Store validation result
    vr = ValidationResult(
        lc_id=lc.id,
        valid=(compliance_result.get("overall_status", "").lower() == "accepted"),
        summary=str(compliance_result),
        raw=str(compliance_result)
    )
    session.add(vr)

    lc.status = compliance_result.get("overall_status", lc.status)
    session.add(lc)

    await session.commit()
    await session.refresh(vr)

    return {"compliance_result": compliance_result}
