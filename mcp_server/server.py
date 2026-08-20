"""MCP server exposing search_jobs, apply_job, send_email, resume_application over stdio."""

import asyncio
import json
import logging
from typing import Any

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

from mcp_server.tools.apply_job import (
    apply_job_tool,
    cancel_application_session_tool,
    get_application_session_status_tool,
    resume_application_tool,
)
from mcp_server.tools.search_jobs import search_jobs_tool
from mcp_server.tools.send_email import send_email_tool

logger = logging.getLogger(__name__)

TOOLS = {
    "search_jobs": {
        "tool": search_jobs_tool,
        "schema": {
            "type": "object",
            "properties": {
                "role": {"type": "string"},
                "skills": {"type": "array", "items": {"type": "string"}},
                "locations": {"type": "array", "items": {"type": "string"}},
                "experience_years": {"type": "integer"},
                "max_results": {"type": "integer", "default": 30},
            },
            "required": ["role"],
        },
        "description": "Search internet for job openings matching criteria",
    },
    "apply_job": {
        "tool": apply_job_tool,
        "schema": {
            "type": "object",
            "properties": {
                "application_url": {"type": "string"},
                "resume_file_path": {"type": "string"},
                "user_profile": {"type": "object"},
                "company": {"type": "string"},
                "job_title": {"type": "string"},
                "expected_resume_hash": {"type": "string", "default": ""},
            },
            "required": ["application_url", "resume_file_path", "user_profile"],
        },
        "description": "Apply to a job using the original resume PDF",
    },
    "send_email": {
        "tool": send_email_tool,
        "schema": {
            "type": "object",
            "properties": {
                "to_email": {"type": "string"},
                "subject": {"type": "string"},
                "summary": {"type": "object"},
            },
            "required": ["to_email", "summary"],
        },
        "description": "Send application summary email to user",
    },
    "resume_application": {
        "tool": resume_application_tool,
        "schema": {
            "type": "object",
            "properties": {
                "browser_session_id": {"type": "string"},
            },
            "required": ["browser_session_id"],
        },
        "description": "Resume a paused job application after user completes manual action (CAPTCHA, login, etc.)",
    },
    "get_application_session_status": {
        "tool": get_application_session_status_tool,
        "schema": {
            "type": "object",
            "properties": {
                "browser_session_id": {"type": "string"},
            },
            "required": ["browser_session_id"],
        },
        "description": "Get status of an active human-in-the-loop browser session",
    },
    "cancel_application_session": {
        "tool": cancel_application_session_tool,
        "schema": {
            "type": "object",
            "properties": {
                "browser_session_id": {"type": "string"},
            },
            "required": ["browser_session_id"],
        },
        "description": "Cancel and clean up an active browser session",
    },
}


async def handle_list_tools(ctx, params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in TOOLS.items()
        ]
    )


async def handle_call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    name = params.name
    if name not in TOOLS:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps({"status": "FAILED", "error": f"Unknown tool: {name}"}))],
            is_error=True,
        )
    args = params.arguments or {}
    try:
        result = await TOOLS[name]["tool"](**args)
        if isinstance(result, str):
            text = result
        else:
            text = json.dumps(result)
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)])
    except Exception as exc:
        logger.exception("Error executing MCP tool %s: %s", name, exc)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps({"status": "FAILED", "error": str(exc)}))],
            is_error=True,
        )


server = Server(
    "job-assistant-tools",
    on_list_tools=handle_list_tools,
    on_call_tool=handle_call_tool,
)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
