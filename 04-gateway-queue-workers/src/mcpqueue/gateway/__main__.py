"""Entry point: ``python -m mcpqueue.gateway`` serves MCP over Streamable HTTP (one process)."""

import uvicorn

from mcpqueue.config import GatewaySettings
from mcpqueue.constants import GATEWAY_APP_FACTORY

if __name__ == "__main__":
    settings = GatewaySettings()
    uvicorn.run(
        GATEWAY_APP_FACTORY,
        factory=True,
        host=settings.host,
        port=settings.port,
        timeout_graceful_shutdown=settings.graceful_shutdown_seconds,
        log_level=settings.log_level.lower(),
    )
