"""LangGraph workflow compilation."""

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from app.agents.application import application_agent
from app.agents.job_search import job_search_agent
from app.agents.notification import notification_agent
from app.agents.resume_match import resume_match_agent
from app.agents.state import AgentState
from app.agents.supervisor import route_supervisor, supervisor_node
from app.db.session import async_session_factory


async def _resume_match_with_session(state: AgentState) -> dict:
    async with async_session_factory() as session:
        return await resume_match_agent(state, session)


async def _application_with_session(state: AgentState) -> dict:
    async with async_session_factory() as session:
        return await application_agent(state, session)


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("job_search_agent", job_search_agent)
    graph.add_node("resume_match_agent", _resume_match_with_session)
    graph.add_node("application_agent", _application_with_session)
    graph.add_node("notification_agent", notification_agent)

    graph.set_entry_point("supervisor")

    graph.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {
            "job_search_agent": "job_search_agent",
            "resume_match_agent": "resume_match_agent",
            "application_agent": "application_agent",
            "notification_agent": "notification_agent",
            "__end__": END,
        },
    )

    graph.add_edge("job_search_agent", "supervisor")
    graph.add_edge("resume_match_agent", "supervisor")
    graph.add_edge("application_agent", "supervisor")
    graph.add_edge("notification_agent", "supervisor")

    return graph.compile(checkpointer=MemorySaver())


_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph
