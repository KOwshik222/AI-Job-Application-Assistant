"""Tests for real MCP protocol communication.

Verifies that:
- MCP server starts as subprocess
- MCP client connects via stdio
- Tool discovery works
- Tools execute through MCP protocol
- MCP unavailable → MCP_UNAVAILABLE (no fallback)
- No direct tool-import fallback
"""

import json
import os
import pytest

# Force test settings
os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")
os.environ.setdefault("DEMO_MODE", "false")
os.environ.setdefault("TEST_MODE", "true")


@pytest.mark.asyncio
async def test_mcp_client_not_connected_returns_unavailable():
    """When MCP client is not connected, call_tool should return MCP_UNAVAILABLE."""
    from app.services.mcp_client import MCPClient

    client = MCPClient()
    # Do NOT call connect — simulate unavailable server
    result = await client.call_tool("search_jobs", {"role": "Developer"})
    assert result["status"] == "MCP_UNAVAILABLE"
    assert "tool" in result
    assert result["tool"] == "search_jobs"


@pytest.mark.asyncio
async def test_mcp_client_no_direct_imports():
    """Verify MCPClient does NOT import from mcp_server.tools directly."""
    import inspect
    from app.services.mcp_client import MCPClient

    source = inspect.getsource(MCPClient)

    # These imports must NOT exist in the client
    assert "from mcp_server.tools.search_jobs" not in source
    assert "from mcp_server.tools.apply_job" not in source
    assert "from mcp_server.tools.send_email" not in source
    assert "import search_jobs_tool" not in source
    assert "import apply_job_tool" not in source
    assert "import send_email_tool" not in source


@pytest.mark.asyncio
async def test_mcp_client_connect_and_discover():
    """Test MCP client can connect to server and discover tools."""
    from app.services.mcp_client import MCPClient

    client = MCPClient()
    try:
        await client.connect()
        assert client.is_connected

        tools = client.get_available_tools()
        assert len(tools) >= 3

        tool_names = [t["name"] for t in tools]
        assert "search_jobs" in tool_names
        assert "apply_job" in tool_names
        assert "send_email" in tool_names
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mcp_search_jobs_through_protocol():
    """Test search_jobs tool works through MCP protocol."""
    from app.services.mcp_client import MCPClient

    client = MCPClient()
    try:
        await client.connect()
        result = await client.call_tool("search_jobs", {
            "role": "Java Developer",
            "skills": ["Java", "Spring Boot"],
            "locations": ["Pune"],
            "max_results": 5,
            "test_mode": True,
        })

        assert "jobs" in result
        assert "status" in result
        assert isinstance(result["jobs"], list)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mcp_apply_job_through_protocol(sample_pdf_path):
    """Test apply_job tool works through MCP protocol."""
    from app.services.mcp_client import MCPClient

    client = MCPClient()
    try:
        await client.connect()
        result = await client.call_tool("apply_job", {
            "application_url": "https://careers.example.com/job/123",
            "resume_file_path": sample_pdf_path,
            "user_profile": {"email": "test@example.com", "full_name": "Test User"},
            "company": "Example Corp",
            "job_title": "Developer",
            "mock_mode": True,
        })

        assert result["status"] == "SUCCESS"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mcp_send_email_through_protocol():
    """Test send_email tool works through MCP protocol."""
    from app.services.mcp_client import MCPClient

    client = MCPClient()
    try:
        await client.connect()
        result = await client.call_tool("send_email", {
            "to_email": "test@example.com",
            "subject": "Test",
            "summary": {
                "applied_successfully": 1,
                "manual_action_required": 0,
                "failed": 0,
                "pending_manual_jobs": [],
                "applied_jobs": [],
                "run_id": "test-001",
            },
        })

        assert "status" in result
        assert result["status"] in ("SENT", "NOT_CONFIGURED")
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_mcp_unknown_tool_returns_error():
    """Unknown tool should return error through MCP protocol."""
    from app.services.mcp_client import MCPClient

    client = MCPClient()
    try:
        await client.connect()
        result = await client.call_tool("nonexistent_tool", {})

        assert result.get("status") == "FAILED"
    finally:
        await client.close()


def test_mcp_client_module_has_no_tool_imports():
    """Verify the mcp_client module file contains no direct tool imports."""
    import pathlib
    client_path = pathlib.Path("app/services/mcp_client.py")
    if client_path.exists():
        content = client_path.read_text()
        assert "from mcp_server.tools" not in content
        assert "import search_jobs_tool" not in content
        assert "import apply_job_tool" not in content
        assert "import send_email_tool" not in content
