"""Server settings, read from environment variables prefixed with ``MCP_``."""

import socket
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcpserver.constants import ENV_PREFIX


class ServerSettings(BaseSettings):
    """Tunable values for the Streamable HTTP server."""

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, env_file=".env", extra="ignore")

    replica_id: str = Field(default_factory=socket.gethostname)
    host: str = "0.0.0.0"
    port: int = 8000
    worker_count: int = 1
    graceful_shutdown_seconds: int = 30
    session_idle_timeout_seconds: float = 1800
    event_store_max_events_per_stream: int = 500
    event_store_max_streams: int = 10_000
    slow_job_max_seconds: int = 60
    slow_job_step_seconds: float = 1.0
    otel_exporter_endpoint: str | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
