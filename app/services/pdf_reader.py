# app/services/pdf_reader.py
from langchain_community.document_loaders import PyPDFLoader
from typing import Optional

def read_pdf_text(path: str) -> str:
    try:
        loader = PyPDFLoader(path)
        pages = loader.load_and_split()
        return "".join(page.page_content for page in pages)
    except Exception as e:
        return f"ERROR_READING_PDF: {e}"
