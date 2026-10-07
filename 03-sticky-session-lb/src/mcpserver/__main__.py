"""Entry point: ``python -m mcpserver`` serves the tools over Streamable HTTP with Uvicorn."""

import uvicorn

from mcpserver.config import ServerSettings
from mcpserver.constants import ASGI_APP_FACTORY

if __name__ == "__main__":
    settings = ServerSettings()
    uvicorn.run(
        ASGI_APP_FACTORY,
        factory=True,
        host=settings.host,
        port=settings.port,
        workers=settings.worker_count,
        timeout_graceful_shutdown=settings.graceful_shutdown_seconds,
        log_level=settings.log_level.lower(),
    )
