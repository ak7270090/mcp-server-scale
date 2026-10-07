"""Server settings, read from environment variables prefixed with ``MCP_``."""

import socket
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcpserver.constants import ENV_PREFIX


class ServerSettings(BaseSettings):
    """Tunable values for the stdio server."""

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, env_file=".env", extra="ignore")

    replica_id: str = Field(default_factory=socket.gethostname)
    slow_job_max_seconds: int = 60
    slow_job_step_seconds: float = 1.0
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
