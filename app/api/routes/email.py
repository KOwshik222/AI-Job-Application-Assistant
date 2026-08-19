"""View saved email summaries."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app.config import get_settings

router = APIRouter(prefix="/api/v1", tags=["email"])
settings = get_settings()


@router.get("/email-log/{run_id}", response_class=HTMLResponse)
async def get_email_log(run_id: str):
    path = settings.data_dir / "email_logs" / f"{run_id}.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Email log not found for this run")
    return HTMLResponse(content=path.read_text(encoding="utf-8"))
