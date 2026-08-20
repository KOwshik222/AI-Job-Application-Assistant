"""MCP server exposing search_jobs, apply_job, send_email, resume_application."""

import asyncio
import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from mcp_server.tools.apply_job import apply_job_tool, resume_application_tool
from mcp_server.tools.search_jobs import search_jobs_tool
from mcp_server.tools.send_email import send_email_tool

server = Server("job-assistant-tools")

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
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
        for name, meta in TOOLS.items()
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    if name not in TOOLS:
        raise ValueError(f"Unknown tool: {name}")
    result = await TOOLS[name]["tool"](**arguments)
    if isinstance(result, str):
        text = result
    else:
        text = json.dumps(result)
    return [TextContent(type="text", text=text)]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
