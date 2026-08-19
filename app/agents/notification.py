"""Notification Agent — email summary via MCP."""

from langsmith import traceable

from app.agents.state import AgentState
from app.schemas import ApplicationResult, EmailSummary, ManualActionItem, UserProfile
from app.services.mcp_client import get_mcp_client


@traceable(name="notification_agent")
async def notification_agent(state: AgentState) -> dict:
    profile = UserProfile(**state["user_profile"])
    applied = [ApplicationResult(**a) for a in state.get("applied_jobs", [])]
    pending = [ManualActionItem(**p) for p in state.get("pending_manual_jobs", [])]
    failed = [ApplicationResult(**a) for a in state.get("failed_jobs", [])]

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

    return {
        "email_summary": summary.model_dump(),
        "notification_sent": email_result.get("delivered", False),
        "email_status": email_result.get("status", "UNKNOWN"),
        "email_note": email_result.get("note") or email_result.get("reason", ""),
        "email_log_path": email_result.get("local_log"),
        "next_agent": "end",
    }
