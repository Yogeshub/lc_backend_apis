# app/main.py
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db
from app.routers import auth_router, files_router, lc_router, ucp_router, agents_router
import httpx

# Patch all httpx calls to ignore SSL
_original_client = httpx.Client
_original_async_client = httpx.AsyncClient

def patched_client(*args, **kwargs):
    kwargs["verify"] = False
    return _original_client(*args, **kwargs)

def patched_async_client(*args, **kwargs):
    kwargs["verify"] = False
    return _original_async_client(*args, **kwargs)

httpx.Client = patched_client
httpx.AsyncClient = patched_async_client

app = FastAPI(title="LC Agentic API (Local)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(files_router.router)
app.include_router(lc_router.router)
app.include_router(ucp_router.router)
app.include_router(agents_router.router)

@app.on_event("startup")
async def on_startup():
    # SSL bypass for litellm as in your streamlit
    import httpx, litellm
    httpx_client = httpx.Client(verify=False)
    litellm.client_session = httpx_client
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    # init db
    await init_db()
    # ensure storage folders exist
    os.makedirs(os.getenv("STORAGE_BASE", "./storage"), exist_ok=True)
    os.makedirs("./storage/lc", exist_ok=True)
    os.makedirs("./storage/ucp", exist_ok=True)
