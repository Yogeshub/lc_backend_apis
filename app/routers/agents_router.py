# app/routers/agents_router.py
from fastapi import APIRouter, Depends, HTTPException, Form
from app.auth import get_current_active_user, get_session
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.agent_services import run_doc_extractor
from app.services.ucp_loader import load_ucp_db_from_dir
import os, json

router = APIRouter(prefix="/agent", tags=["agent"])
model_name = "groq/llama-3.3-70b-versatile"


def lc_chat_view(lc_data):
    # --- SAFETY: convert string JSON to dict ---
    if isinstance(lc_data, str):
        try:
            lc_data = json.loads(lc_data)
        except Exception:
            return {}

    if not isinstance(lc_data, dict):
        return {}

    return {
        "lc_number": lc_data.get("letter_of_credit_number"),
        "amount": (
            f"{lc_data.get('amount', {}).get('currency')} "
            f"{lc_data.get('amount', {}).get('in_figures')}"
        ),
        "expiry_date": lc_data.get("expiry_date"),
        "latest_shipment_date": lc_data.get("latest_date_of_shipment"),
        "documents_required": [
            d.split(",")[0]
            for d in lc_data.get("documents_required", [])
        ]
    }


@router.post("/chat")
async def chat_query(
    query: str = Form(...), 
    lc_id: int | None = None, 
    ucp_id: int | None = None, 
    user=Depends(get_current_active_user), 
    session: AsyncSession = Depends(get_session)
    ):
    from crewai import Agent, Task, Crew, LLM
    # ---------------- UCP context (MINIMAL) ----------------
    ucp_context = ""
    if ucp_id:
        ucp_dir = os.path.join("storage", "ucp", str(ucp_id), "chroma")
        if os.path.exists(ucp_dir):
            try:
                ucp_db = load_ucp_db_from_dir(ucp_dir)
                docs = ucp_db.similarity_search(query, k=1)
                if docs:
                    ucp_context = docs[0].page_content[:600]
            except Exception:
                pass
        # chroma_dir = os.path.join(ucp_dir, "chroma")
        # if os.path.exists(chroma_dir):
        #     try:
        #         ucp_db = load_ucp_db_from_dir(chroma_dir)
        #         retrieved = ucp_db.similarity_search(query, k=3)
        #         ucp_context = "\n\n".join([doc.page_content for doc in retrieved])
        #     except Exception as e:
        #         ucp_context = ""
    
    # ---------------- LC context (REDUCED) ----------------
    lc_context = ""
    if lc_id:
        from sqlmodel import select
        from app.models import LC
        res = await session.execute(select(LC).where(LC.id == lc_id))
        lc = res.scalar_one_or_none()
        if lc and lc.extracted_json:
            lc_context = lc_chat_view(lc.extracted_json)
            
    # ---------------- LLM (Groq-safe) ----------------
    llm = LLM(
        model=model_name, 
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.2,
        max_tokens=400)
    
    agent = Agent(
        role="QA Agent", 
        goal="Answer user query using LC / UCP content",
        backstory="You are a trade finance assistant specializing in Letters of Credit and UCP 600.",
        llm=llm, 
        allow_delegation=False
    )

    task_text = f"""
User question:
{query}

LC summary:
{json.dumps(lc_context, ensure_ascii=False)}

Relevant UCP context:
{ucp_context}

Answer concisely and avoid generic explanations of UCP 600.
Focus only on this LC.
"""
    task = Task(
        description=task_text, 
        expected_output="Plain text answer",
        agent=agent
    )

    crew = Crew(agents=[agent], tasks=[task], verbose=False)
    res = crew.kickoff()

    return {"answer": str(res)}
