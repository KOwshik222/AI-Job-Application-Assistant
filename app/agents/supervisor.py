"""Supervisor — routes agents through the workflow."""

import logging

from langsmith import traceable

from app.agents.state import AgentState

logger = logging.getLogger(__name__)


@traceable(name="supervisor")
def supervisor_node(state: AgentState) -> dict:
    current_next = state.get("next_agent", "")
    if not current_next:
        logger.info("SUPERVISOR | next_agent was empty -> defaulting to 'job_search'")
        return {"next_agent": "job_search"}
    logger.info("SUPERVISOR | next_agent='%s' (no change needed)", current_next)
    return {}


def route_supervisor(state: AgentState) -> str:
    nxt = state.get("next_agent", "job_search")
    if nxt == "end":
        logger.info("SUPERVISOR ROUTE | next_agent='end' -> __end__")
        return "__end__"
    mapping = {
        "job_search": "job_search_agent",
        "resume_match": "resume_match_agent",
        "application": "application_agent",
        "notification": "notification_agent",
    }
    resolved = mapping.get(nxt, "notification_agent")
    logger.info("SUPERVISOR ROUTE | next_agent='%s' -> routing to '%s'", nxt, resolved)
    return resolved

