# app/services/ucp_loader.py
import os
from PyPDF2 import PdfReader
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings

UCP_PDF_PATH = "UCP.pdf"  # default; but in our app we'll store per-upload paths
CHROMA_DIR_BASE = "./storage/ucp"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
CHROMA_COLLECTION = "ucp600"

def build_ucp_vector_db(uploaded_pdf_path: str, persist_dir: str):
    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-mpnet-base-v2",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": False}
    )

    reader = PdfReader(uploaded_pdf_path)
    pages = [page.extract_text() or "" for page in reader.pages]
    ucp_text = "\n\n".join(pages)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )
    texts = splitter.split_text(ucp_text)

    os.makedirs(persist_dir, exist_ok=True)
    ucp_db = Chroma.from_texts(
        texts,
        embedding=embeddings,
        persist_directory=persist_dir,
        collection_name=CHROMA_COLLECTION
    )
    ucp_db.persist()
    return ucp_db

def load_ucp_db_from_dir(persist_dir: str):
    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-mpnet-base-v2",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": False}
    )
    if not os.path.exists(persist_dir):
        raise FileNotFoundError("No persisted ucp chroma at " + persist_dir)
    return Chroma(persist_directory=persist_dir, embedding_function=embeddings, collection_name=CHROMA_COLLECTION)
