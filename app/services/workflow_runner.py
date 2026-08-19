"""LangGraph workflow execution."""

import os
import uuid
from typing import Any

from langsmith import traceable

from app.agents.graph import get_graph
from app.config import get_settings
from app.schemas import StartJobSearchRequest, UserProfile

settings = get_settings()

# In-memory run status (production: Redis or DB)
_run_status: dict[str, dict[str, Any]] = {}


def _configure_langsmith() -> None:
    if settings.langchain_tracing_v2:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        if settings.langchain_api_key:
            os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
        os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint


@traceable(name="run_job_application_workflow")
async def run_workflow(
    request: StartJobSearchRequest,
    resume_path: str,
    run_id: str | None = None,
) -> str:
    _configure_langsmith()
    if run_id is None:
        run_id = str(uuid.uuid4())
    graph = get_graph()

    profile = UserProfile(
        role=request.role,
        skills=request.skills,
        experience=request.experience,
        locations=request.locations,
        email=request.email,
        full_name=request.full_name,
        phone=request.phone,
    )

    initial_state = {
        "run_id": run_id,
        "user_id": request.user_id,
        "resume_id": request.resume_id,
        "resume_file_path": resume_path,
        "user_profile": profile.model_dump(),
        "resume_chunks": [],
        "resume_metadata": {},
        "jobs_found": [],
        "matched_jobs": [],
        "applied_jobs": [],
        "pending_manual_jobs": [],
        "failed_jobs": [],
        "match_threshold": request.match_threshold or settings.match_threshold,
        "max_applications_per_run": request.max_applications or settings.max_applications_per_day,
        "applications_attempted": 0,
        "next_agent": "",
        "application_complete": False,
        "notification_sent": False,
        "email_status": "",
        "email_note": "",
        "email_log_path": None,
        "errors": [],
        "email_summary": None,
        "email_status": "",
        "email_note": "",
        "messages": [],
    }

    _run_status[run_id] = {"status": "RUNNING", "state": None}

    config = {"configurable": {"thread_id": run_id}}

    try:
        final_state = await graph.ainvoke(initial_state, config)
        _run_status[run_id] = {
            "status": "COMPLETED",
            "state": final_state,
        }
    except Exception as exc:
        _run_status[run_id] = {
            "status": "FAILED",
            "error": str(exc),
        }
        raise

    return run_id


def get_run_status(run_id: str) -> dict[str, Any] | None:
    return _run_status.get(run_id)


def get_latest_run_for_user(user_id: str) -> dict[str, Any] | None:
    for run_id, data in reversed(list(_run_status.items())):
        state = data.get("state") or {}
        if state.get("user_id") == user_id:
            return {"run_id": run_id, **data}
    return None
