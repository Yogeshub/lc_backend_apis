# app/routers/agents_router.py
from fastapi import APIRouter, Depends, HTTPException, Form
from app.auth import get_current_active_user, get_session
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.agent_services import run_doc_extractor
from app.services.ucp_loader import load_ucp_db_from_dir
import os, json

router = APIRouter(prefix="/agent", tags=["agent"])

@router.post("/chat")
async def chat_query(query: str = Form(...), lc_id: int | None = None, ucp_id: int | None = None, user=Depends(get_current_active_user), session: AsyncSession = Depends(get_session)):
    """
    Basic chat endpoint — uses UCP vector DB + LC extracted JSON + supporting docs to form prompt.
    For now, will call CrewAI LLM directly to answer with context.
    """
    # fetch ucp context
    ucp_context = ""
    if ucp_id:
        ucp_dir = os.path.join("storage", "ucp", str(ucp_id))
        chroma_dir = os.path.join(ucp_dir, "chroma")
        if os.path.exists(chroma_dir):
            try:
                ucp_db = load_ucp_db_from_dir(chroma_dir)
                retrieved = ucp_db.similarity_search(query, k=3)
                ucp_context = "\n\n".join([doc.page_content for doc in retrieved])
            except Exception as e:
                ucp_context = ""
    # optional LC context
    lc_context = ""
    if lc_id:
        from sqlmodel import select
        from app.models import LC, Attachment
        q = select(LC).where(LC.id == lc_id)
        res = await session.execute(q)
        lc = res.scalar_one_or_none()
        if lc and lc.extracted_json:
            lc_context = lc.extracted_json
    # Compose prompt & call crewai agent
    from crewai import Agent, Task, Crew, LLM
    llm = LLM(model="groq/meta-llama/llama-guard-4-12b", api_key=os.getenv("GROQ_API_KEY"))
    agent = Agent(role="QA Agent", goal="Answer user query using LC / UCP content", llm=llm, allow_delegation=False)
    task_text = f"""
User question:
{query}

LC context:
{lc_context}

UCP context:
{ucp_context}
"""
    task = Task(description=task_text, expected_output="Answer in plain text", agent=agent)
    crew = Crew(agents=[agent], tasks=[task])
    res = crew.kickoff()
    return {"answer": str(res)}
