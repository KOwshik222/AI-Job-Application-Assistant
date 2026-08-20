"""MCP client — real protocol communication via stdio transport.

Connects to the MCP server as a subprocess using StdioClientTransport.
NEVER imports tool implementations directly from mcp_server.tools.
"""

import asyncio
import json
import logging
import time
from typing import Any

from langsmith import traceable

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Sensitive fields that must NEVER be logged
_SENSITIVE_FIELDS = frozenset({
    "api_key", "api_secret", "password", "otp", "token",
    "secret", "auth_token", "access_token", "refresh_token",
    "smtp_password", "credentials",
})


def _sanitize_for_logging(data: Any, depth: int = 0) -> Any:
    """Recursively sanitize sensitive fields from data before logging."""
    if depth > 10:
        return "..."
    if isinstance(data, dict):
        return {
            k: "***REDACTED***" if k.lower() in _SENSITIVE_FIELDS else _sanitize_for_logging(v, depth + 1)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [_sanitize_for_logging(item, depth + 1) for item in data[:20]]
    return data


class MCPConnectionError(Exception):
    """Raised when MCP server connection fails."""
    pass


class MCPToolError(Exception):
    """Raised when an MCP tool execution fails."""
    pass


class MCPClient:
    """Real MCP protocol client using stdio transport.
    
    Architecture:
        LangGraph Agent → MCPClient → MCP Protocol (stdio) → MCP Server → Tool → External System
    
    This client does NOT import any tool implementations directly.
    """

    def __init__(self):
        self._session = None
        self._read_stream = None
        self._write_stream = None
        self._transport_ctx = None
        self._session_ctx = None
        self._connected = False
        self._available_tools: list[dict] = []

    @property
    def is_connected(self) -> bool:
        return self._connected and self._session is not None

    @traceable(name="mcp_connect")
    async def connect(self) -> None:
        """Connect to MCP server via stdio transport."""
        if self._connected:
            logger.debug("MCP client already connected")
            return

        start_time = time.monotonic()
        try:
            from mcp.client.session import ClientSession
            from mcp.client.stdio import StdioServerParameters, stdio_client

            server_params = StdioServerParameters(
                command=settings.mcp_server_command,
                args=settings.mcp_args_list,
            )

            logger.info(
                "Connecting to MCP server: %s %s",
                settings.mcp_server_command,
                " ".join(settings.mcp_args_list),
            )

            # Create the stdio transport context
            self._transport_ctx = stdio_client(server_params)
            self._read_stream, self._write_stream = await self._transport_ctx.__aenter__()

            # Create the client session context
            self._session_ctx = ClientSession(self._read_stream, self._write_stream)
            self._session = await self._session_ctx.__aenter__()

            # Initialize the session
            await asyncio.wait_for(
                self._session.initialize(),
                timeout=settings.mcp_connection_timeout,
            )

            self._connected = True
            elapsed = time.monotonic() - start_time
            logger.info("MCP client connected in %.2fs", elapsed)

            # Discover tools
            await self._discover_tools()

        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start_time
            logger.error("MCP connection timed out after %.2fs", elapsed)
            await self._cleanup()
            raise MCPConnectionError(
                f"MCP server connection timed out after {settings.mcp_connection_timeout}s"
            )
        except Exception as exc:
            elapsed = time.monotonic() - start_time
            logger.error("MCP connection failed after %.2fs: %s", elapsed, exc)
            await self._cleanup()
            raise MCPConnectionError(f"MCP server connection failed: {exc}") from exc

    @traceable(name="mcp_discover_tools")
    async def _discover_tools(self) -> None:
        """Discover available tools from the MCP server."""
        if not self._session:
            raise MCPConnectionError("Not connected to MCP server")

        try:
            result = await asyncio.wait_for(
                self._session.list_tools(),
                timeout=settings.mcp_connection_timeout,
            )
            self._available_tools = [
                {"name": tool.name, "description": tool.description}
                for tool in result.tools
            ]
            tool_names = [t["name"] for t in self._available_tools]
            logger.info("MCP tools discovered: %s", tool_names)
        except Exception as exc:
            logger.error("MCP tool discovery failed: %s", exc)
            raise MCPConnectionError(f"Tool discovery failed: {exc}") from exc

    def get_available_tools(self) -> list[dict]:
        """Return list of discovered tools."""
        return list(self._available_tools)

    @traceable(name="mcp_tool_call")
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke an MCP tool through the protocol. Never calls tools directly."""
        if not self._connected or not self._session:
            logger.error("MCP client not connected — returning MCP_UNAVAILABLE")
            return {
                "status": "MCP_UNAVAILABLE",
                "error": "MCP server is not connected. Cannot execute tool.",
                "tool": name,
            }

        # Sanitize arguments for logging (never log secrets)
        safe_args = _sanitize_for_logging(arguments)
        logger.info("MCP call_tool: %s with args: %s", name, safe_args)

        start_time = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._session.call_tool(name, arguments),
                timeout=settings.mcp_tool_timeout,
            )

            elapsed = time.monotonic() - start_time
            logger.info("MCP tool '%s' completed in %.2fs", name, elapsed)

            # Parse TextContent responses
            if result.content:
                for content_item in result.content:
                    if hasattr(content_item, "text"):
                        try:
                            parsed = json.loads(content_item.text)
                            return parsed
                        except json.JSONDecodeError:
                            return {"raw_output": content_item.text}

            # If result indicates error
            if result.isError:
                error_text = ""
                if result.content:
                    error_text = " ".join(
                        getattr(c, "text", "") for c in result.content
                    )
                logger.error("MCP tool '%s' returned error: %s", name, error_text)
                return {
                    "status": "FAILED",
                    "error": f"MCP tool '{name}' error: {error_text}",
                    "tool": name,
                }

            return {"status": "FAILED", "error": "Empty response from MCP tool", "tool": name}

        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start_time
            logger.error("MCP tool '%s' timed out after %.2fs", name, elapsed)
            return {
                "status": "SEARCH_TIMEOUT" if name == "search_jobs" else "TIMEOUT",
                "message": f"MCP tool '{name}' timed out after {settings.mcp_tool_timeout}s",
                "error": f"MCP tool '{name}' timed out after {settings.mcp_tool_timeout}s",
                "tool": name,
                "jobs": [],
                "partial_jobs": [],
            }
        except Exception as exc:
            elapsed = time.monotonic() - start_time
            logger.error("MCP tool '%s' failed after %.2fs: %s", name, elapsed, exc)
            return {
                "status": "FAILED",
                "reason": f"MCP tool '{name}' execution error: {exc}",
                "error": str(exc),
                "tool": name,
            }

    async def close(self) -> None:
        """Close MCP connection and clean up resources."""
        logger.info("Closing MCP client connection")
        await self._cleanup()

    async def _cleanup(self) -> None:
        """Internal cleanup of transport and session contexts."""
        self._connected = False
        self._session = None
        self._available_tools = []

        if self._session_ctx:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug("Session cleanup error (non-fatal): %s", exc)
            self._session_ctx = None

        if self._transport_ctx:
            try:
                await self._transport_ctx.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug("Transport cleanup error (non-fatal): %s", exc)
            self._transport_ctx = None

        self._read_stream = None
        self._write_stream = None


# --- Module-level singleton ---

_mcp_client: MCPClient | None = None


def get_mcp_client() -> MCPClient:
    """Get or create the singleton MCP client.
    
    The client must be connected via connect() before calling tools.
    If not connected, call_tool() returns MCP_UNAVAILABLE.
    """
    global _mcp_client
    if _mcp_client is None:
        _mcp_client = MCPClient()
    return _mcp_client


async def shutdown_mcp_client() -> None:
    """Shutdown the MCP client (called during app shutdown)."""
    global _mcp_client
    if _mcp_client is not None:
        await _mcp_client.close()
        _mcp_client = None
