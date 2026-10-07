"""Gateway settings, read from environment variables prefixed with ``MCP_``."""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from apigateway.constants import DEFAULT_REDACTION_PATTERNS, ENV_PREFIX


class GatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8000
    services_file: Path = Path("config/services.yaml")
    overrides_file: Path = Path("config/tool_overrides.yaml")
    registry_refresh_seconds: float = 10.0
    http_timeout_seconds: float = 10.0
    grpc_timeout_seconds: float = 10.0
    grpc_stream_timeout_seconds: float = 60.0
    read_only_retry_attempts: int = 2
    retry_backoff_seconds: float = 0.2
    redaction_patterns: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_REDACTION_PATTERNS)
    )
    is_discovery_mode: bool = False
    discovery_result_limit: int = 10
    max_schema_depth: int = 6
    facade_upstream_url: str = "http://localhost:8000/mcp"
    facade_timeout_seconds: float = 60.0
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
