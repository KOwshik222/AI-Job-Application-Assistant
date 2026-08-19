"""Supervisor — routes agents through the workflow."""

from langsmith import traceable

from app.agents.state import AgentState


@traceable(name="supervisor")
def supervisor_node(state: AgentState) -> dict:
    if not state.get("next_agent"):
        return {"next_agent": "job_search"}
    return {}


def route_supervisor(state: AgentState) -> str:
    nxt = state.get("next_agent", "job_search")
    if nxt == "end":
        return "__end__"
    mapping = {
        "job_search": "job_search_agent",
        "resume_match": "resume_match_agent",
        "application": "application_agent",
        "notification": "notification_agent",
    }
    return mapping.get(nxt, "notification_agent")
