"""Notification Agent — email summary via MCP."""

import logging

from langsmith import traceable

from app.agents.state import AgentState
from app.schemas import ApplicationResult, EmailSummary, ManualActionItem, UserProfile
from app.services.mcp_client import get_mcp_client

logger = logging.getLogger(__name__)


@traceable(name="notification_agent")
async def notification_agent(state: AgentState) -> dict:
    profile = UserProfile(**state["user_profile"])
    applied = [ApplicationResult(**a) for a in state.get("applied_jobs", [])]
    pending = [ManualActionItem(**p) for p in state.get("pending_manual_jobs", [])]
    failed = [ApplicationResult(**a) for a in state.get("failed_jobs", [])]

    # --- DIAGNOSTIC: NOTIFICATION START ---
    logger.info("-" * 60)
    logger.info("NOTIFICATION START | applied=%d | manual=%d | failed=%d | errors=%d",
                len(applied), len(pending), len(failed),
                len(state.get("errors", [])))

    summary = EmailSummary(
        applied_successfully=len(applied),
        manual_action_required=len(pending),
        failed=len(failed),
        pending_manual_jobs=pending,
        applied_jobs=applied,
        run_id=state["run_id"],
    )

    mcp = get_mcp_client()
    email_result = await mcp.call_tool(
        "send_email",
        {
            "to_email": profile.email,
            "subject": f"Job Application Summary — Run {state['run_id'][:8]}",
            "summary": summary.model_dump(),
        },
    )

    email_status = email_result.get("status", "UNKNOWN")
    logger.info("NOTIFICATION END | email_status=%s | delivered=%s",
                email_status, email_result.get("delivered", False))
    logger.info("-" * 60)

    return {
        "email_summary": summary.model_dump(),
        "notification_sent": email_result.get("delivered", False),
        "email_status": email_status,
        "email_note": email_result.get("note") or email_result.get("reason", ""),
        "email_log_path": email_result.get("local_log"),
        "next_agent": "end",
    }

