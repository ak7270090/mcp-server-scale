"""Builds the MCP server."""

from mcp.server.fastmcp import FastMCP

from mcpserver.config import ServerSettings
from mcpserver.constants import SERVER_INSTRUCTIONS, SERVER_NAME
from mcpserver.tools import ReplicaTools, SessionCounterStore


def create_mcp_server(settings: ServerSettings) -> FastMCP:
    mcp = FastMCP(SERVER_NAME, instructions=SERVER_INSTRUCTIONS, log_level=settings.log_level)
    ReplicaTools(settings, SessionCounterStore()).register(mcp)
    return mcp
