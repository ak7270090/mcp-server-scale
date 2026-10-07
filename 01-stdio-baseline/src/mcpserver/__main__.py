"""Entry point: ``python -m mcpserver`` serves the tools over stdio."""

from mcpserver.app import create_mcp_server
from mcpserver.config import ServerSettings

if __name__ == "__main__":
    create_mcp_server(ServerSettings()).run(transport="stdio")
