"""FastAPI application entry point."""

import sys
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import applications, config, email, resume, workflow
from app.db.session import init_db
from app.rag.llm_provider import LLMProviderError
from app.services.mcp_client import MCPConnectionError, MCPToolError, get_mcp_client, shutdown_mcp_client

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    await init_db()

    # Connect MCP client to MCP server
    mcp_client = get_mcp_client()
    try:
        await mcp_client.connect()
        logger.info("MCP client connected successfully at startup")
    except Exception as exc:
        logger.error(
            "MCP client failed to connect at startup: %s. "
            "Tools will return MCP_UNAVAILABLE until server is available.",
            exc,
        )

    yield

    # Shutdown MCP client
    await shutdown_mcp_client()
    logger.info("MCP client shut down")


app = FastAPI(
    title="AI Job Application Assistant",
    description="LangGraph-powered job search, resume matching, and application automation",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(LLMProviderError)
async def llm_provider_exception_handler(request: Request, exc: LLMProviderError):
    logger.error("LLMProviderError on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=getattr(exc, "status_code", 503),
        content={
            "detail": f"{exc.reason}. (Provider: {exc.provider}). Please configure a valid key or enable DEMO_MODE=true in .env.",
            "status": "LLM_PROVIDER_ERROR",
            "provider": exc.provider,
            "reason": exc.reason,
        },
    )


@app.exception_handler(MCPConnectionError)
async def mcp_connection_exception_handler(request: Request, exc: MCPConnectionError):
    logger.error("MCPConnectionError on %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": f"MCP tool server unavailable: {exc}",
            "status": "MCP_UNAVAILABLE",
        },
    )


app.include_router(resume.router)
app.include_router(workflow.router)
app.include_router(applications.router)
app.include_router(config.router)
app.include_router(email.router)

if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/health")
async def health():
    mcp = get_mcp_client()
    return {
        "status": "ok",
        "service": "ai-job-application-assistant",
        "mcp_connected": mcp.is_connected,
        "mcp_tools": [t["name"] for t in mcp.get_available_tools()] if mcp.is_connected else [],
    }


@app.get("/")
async def serve_frontend():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "API running. Frontend not found at static/index.html"}
