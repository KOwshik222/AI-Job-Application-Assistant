"""App configuration and health status endpoint."""

from fastapi import APIRouter

from app.config import get_settings
from app.rag.embeddings import is_demo_mode

router = APIRouter(prefix="/api/v1", tags=["config"])
settings = get_settings()


@router.get("/config")
async def get_app_config():
    from mcp_server.tools.send_email import is_smtp_configured

    llm_configured = not is_demo_mode()
    active_provider = settings.llm_provider.lower()

    return {
        "service": "AI Job Application Assistant",
        "demo_mode": is_demo_mode(),
        "llm_provider": active_provider,
        "llm_configured": llm_configured,
        "rag_configured": llm_configured or True,  # RAG active via vectorstore or keyword fallback
        "tavily_configured": bool(settings.tavily_api_key),
        "langsmith_configured": bool(settings.langchain_api_key),
        "smtp_configured": is_smtp_configured(),
        "max_applications_per_day": settings.max_applications_per_day,
        "match_threshold": settings.match_threshold,
    }
