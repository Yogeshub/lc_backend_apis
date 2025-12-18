# app/services/agent_services.py
import os
import json
from crewai import Agent, Task, Crew, LLM
from app.services.pdf_reader import read_pdf_text
from app.services.ucp_loader import load_ucp_db_from_dir
from typing import List, Dict, Any

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
model_name = "groq/llama-3.3-70b-versatile"


def lc_compliance_view(lc_data: dict) -> dict:
    return {
        "lc_number": lc_data.get("letter_of_credit_number"),
        "amount": f"{lc_data['amount']['currency']} {lc_data['amount']['in_figures']}",
        "expiry_date": lc_data.get("expiry_date"),
        "latest_shipment_date": lc_data.get("latest_date_of_shipment"),
        "payment_terms": lc_data.get("availability"),
        "documents_required": [
            doc.split(",")[0] for doc in lc_data.get("documents_required", [])
        ],
        "partial_shipments": lc_data.get("shipment_details", {}).get("partial_shipments"),
        "transshipments": lc_data.get("shipment_details", {}).get("transshipments"),
        "ucp_applicable": "UCP 600" in " ".join(lc_data.get("additional_conditions", []))
    }


def compress_discrepancies(discrepancy_tables: list) -> list:
    compressed = []
    for d in discrepancy_tables:
        doc = d.get("document", "Unknown document")
        issue = d.get("issue") or d.get("discrepancy")
        if issue:
            compressed.append(f"{doc}: {issue}")
    return compressed[:10]  # hard cap


def get_ucp_context(ucp_persist_dir: str, lc_view: dict) -> str:
    try:
        if ucp_persist_dir and os.path.exists(ucp_persist_dir):
            ucp_db = load_ucp_db_from_dir(ucp_persist_dir)

            query = (
                f"UCP 600 rules for expiry date, shipment date, "
                f"bill of lading, and document compliance"
            )

            docs = ucp_db.similarity_search(query, k=1)
            if docs:
                return docs[0].page_content[:800]  # HARD truncate
    except Exception:
        pass

    return ""


def run_lc_extractor(lc_text: str):
    extractor = Agent(
        role="LC Extractor",
        goal="Extract key fields from a Letter of Credit (LC) document",
        backstory="You are an expert in trade finance documents and extract only structured fields.",
        # llm=LLM(model="groq/meta-llama/llama-guard-4-12b", temperature=0.1, api_key=GROQ_API_KEY),
        llm=LLM(model=model_name, temperature=0.1, api_key=GROQ_API_KEY),
        allow_delegation=False,
        verbose=False,
    )
    task = Task(
        description=f"""
Extract the most important fields from the following Letter of Credit (LC) document and return ONLY a valid JSON object.

Document:
{lc_text}
""",
        expected_output="Valid JSON object with LC details.",
        agent=extractor,
    )
    crew = Crew(agents=[extractor], tasks=[task], verbose=False)
    result = crew.kickoff()
    try:
        return json.loads(str(result).strip())
    except Exception:
        return {"raw_output": str(result)}

def run_doc_extractor(doc_text: str):
    extractor = Agent(
        role="Document Extractor",
        goal="Extract key structured fields from PDF documents",
        backstory="You are an expert in trade finance and logistics documents.",
        # llm=LLM(model="groq/meta-llama/llama-guard-4-12b", temperature=0.1, api_key=GROQ_API_KEY),
        llm=LLM(model=model_name, temperature=0.1, api_key=GROQ_API_KEY),
        allow_delegation=False,
        verbose=False,
    )
    task = Task(
        description=f"Extract fields from the following document. Return only a valid JSON object.\n\n{doc_text}",
        expected_output="Valid JSON object with extracted fields.",
        agent=extractor,
    )
    crew = Crew(agents=[extractor], tasks=[task], verbose=False)
    result = crew.kickoff()
    try:
        return json.loads(str(result).strip())
    except Exception:
        return {"raw_output": str(result)}

def run_discrepancy_check(lc_data: Dict[str, Any], doc_results: List[Dict[str, Any]]):
    checker = Agent(
        role="Discrepancy Checker",
        goal="Compare LC document with supporting documents and flag matches, mismatches, or interchanges.",
        backstory="You are an expert trade finance compliance officer.",
        # llm=LLM(model="groq/meta-llama/llama-guard-4-12b", temperature=0.1, api_key=GROQ_API_KEY),
        llm=LLM(model=model_name, temperature=0.1, api_key=GROQ_API_KEY),
        allow_delegation=False,
        verbose=False,
    )
    tables = []
    for doc in doc_results:
        comparison_instructions = f"""
Compare LC data against supporting document: {doc.get('file_name','doc')}

LC Data: {json.dumps(lc_data)}
Document Data: {json.dumps(doc.get('data', {}))}

Return a JSON array rows:
[{{"Field":"...","LC Value":"...","Document Value":"...","Status":"..."}}, ...]
"""
        task = Task(description=comparison_instructions, expected_output="JSON array", agent=checker)
        crew = Crew(agents=[checker], tasks=[task], verbose=False)
        result = crew.kickoff()
        try:
            rows = json.loads(str(result).strip())
        except Exception:
            # fallback rule-based comparison
            rows = []
            doc_data = doc.get("data", {})
            for field, lc_value in lc_data.items():
                doc_value = doc_data.get(field, "")
                status = "❌ Mismatch"
                if not lc_value or not doc_value:
                    status = "⚠️ Missing"
                elif str(lc_value).strip().lower() == str(doc_value).strip().lower():
                    status = "✅ Match"
                rows.append({"Field": field, "LC Value": lc_value, "Document Value": doc_value, "Status": status})
        tables.append({"file": doc.get("file_name", "Document"), "table": rows})
    return tables

def run_compliance_check(lc_data: Dict,
                        discrepancy_tables: List,
                        ucp_persist_dir: str, 
                        lc_file_path: str, 
                        supporting_file_paths: List[str]):
    # load ucp vector db if present
    ucp_context = ""
    lc_view = lc_compliance_view(lc_data)
    # print("LC Details", lc_data)

    discrepancy_summary = compress_discrepancies(discrepancy_tables)

    ucp_context = get_ucp_context(ucp_persist_dir, lc_view)

    # try:
    #     if ucp_persist_dir and os.path.exists(ucp_persist_dir):
    #         ucp_db = load_ucp_db_from_dir(ucp_persist_dir)
    #         retrieved = ucp_db.similarity_search(json.dumps(lc_data), k=3)
    #         ucp_context = "\n\n".join([doc.page_content for doc in retrieved])
    # except Exception:
    #     ucp_context = ""

    # llm_obj = LLM(model="groq/meta-llama/llama-guard-4-12b", temperature=0.1, api_key=GROQ_API_KEY)
    llm_obj = LLM(model=model_name, temperature=0.1, api_key=GROQ_API_KEY, max_tokens=512)

    compliance_agent = Agent(
        role="Compliance Officer",
        goal="Check LC compliance with UCP 600",
        backstory="You are a trade finance compliance expert",
        llm=llm_obj,
        tools=[],
        allow_delegation=False,
        verbose=False,
    )

    task_text = f"""
UCP context (summary):
{ucp_context}

LC (compliance view):
{json.dumps(lc_view, ensure_ascii=False)}

Discrepancies:
{json.dumps(discrepancy_summary, ensure_ascii=False)}

Return ONLY JSON:
{{"overall_status":"Accepted|Rejected","ucp_compliance_issues":[...],"recommendation":"string"}}
"""

    task = Task(
        description=task_text,
        expected_output="JSON",
        agent=compliance_agent
    )

    crew = Crew(
        agents=[compliance_agent],
        tasks=[task],
        verbose=False
    )

    result = crew.kickoff()
    
    try:
        return json.loads(str(result).strip())
    except Exception:
        return {"raw_output": str(result)}
