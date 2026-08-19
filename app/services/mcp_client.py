"""MCP client wrapper for LangGraph agents."""

import json
from typing import Any

from langsmith import traceable

from app.config import get_settings

settings = get_settings()


class MCPClient:
    """Direct tool invocation — calls MCP tool implementations in-process for reliability."""

    def __init__(self):
        from mcp_server.tools.apply_job import apply_job_tool
        from mcp_server.tools.search_jobs import search_jobs_tool
        from mcp_server.tools.send_email import send_email_tool

        self._tools = {
            "search_jobs": search_jobs_tool,
            "apply_job": apply_job_tool,
            "send_email": send_email_tool,
        }

    @traceable(name="mcp_tool_call")
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self._tools:
            raise ValueError(f"Unknown MCP tool: {name}")
        result = await self._tools[name](**arguments)
        if isinstance(result, str):
            return json.loads(result)
        return result


_mcp_client: MCPClient | None = None


def get_mcp_client() -> MCPClient:
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client
