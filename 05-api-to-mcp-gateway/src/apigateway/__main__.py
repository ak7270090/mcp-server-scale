"""Entry point: ``python -m apigateway`` serves MCP, the REST facade and admin routes."""

import logging

import uvicorn

from apigateway.config import GatewaySettings
from apigateway.constants import GATEWAY_APP_FACTORY

if __name__ == "__main__":
    settings = GatewaySettings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(name)s %(message)s")
    uvicorn.run(
        GATEWAY_APP_FACTORY,
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
