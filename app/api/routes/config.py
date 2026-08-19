"""App configuration endpoint."""

from fastapi import APIRouter

from app.config import get_settings
from app.rag.embeddings import is_demo_mode

router = APIRouter(prefix="/api/v1", tags=["config"])
settings = get_settings()


@router.get("/config")
async def get_app_config():
    from mcp_server.tools.send_email import is_smtp_configured

    return {
        "demo_mode": is_demo_mode(),
        "smtp_configured": is_smtp_configured(),
        "tavily_configured": bool(settings.tavily_api_key),
        "max_applications_per_day": settings.max_applications_per_day,
        "match_threshold": settings.match_threshold,
        "service": "AI Job Application Assistant",
    }
