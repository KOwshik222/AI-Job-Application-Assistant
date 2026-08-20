"""MCP client wrapper for LangGraph agents with LangSmith tracing and error handling."""

import json
import logging
from typing import Any

from langsmith import traceable

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class MCPClient:
    """In-process and protocol-compatible MCP tool invocation client."""

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
        """Invoke an MCP tool with tracing and structured JSON error handling."""
        if name not in self._tools:
            raise ValueError(f"Unknown MCP tool: {name}. Available: {list(self._tools.keys())}")

        try:
            result = await self._tools[name](**arguments)
            if isinstance(result, str):
                try:
                    return json.loads(result)
                except json.JSONDecodeError:
                    return {"raw_output": result}
            return result
        except Exception as exc:
            logger.error("Error executing MCP tool '%s': %s", name, exc)
            return {
                "status": "FAILED",
                "reason": f"MCP tool '{name}' execution error: {exc}",
                "error": str(exc),
            }


_mcp_client: MCPClient | None = None


def get_mcp_client() -> MCPClient:
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client
