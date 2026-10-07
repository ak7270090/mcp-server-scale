"""Settings for each service, read from environment variables prefixed with ``MCP_``."""

import socket
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcpqueue.constants import ENV_PREFIX

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
ElicitationMode = Literal["worker_waits", "continuation"]


class QueueSettings(BaseSettings):
    """Values every service needs to agree on: where NATS is and how the job queue behaves."""

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, env_file=".env", extra="ignore")

    nats_url: str = "nats://localhost:4222"
    job_ack_wait_seconds: float = 5.0
    job_max_deliveries: int = 3
    queue_max_pending: int = 1000
    session_counter_ttl_seconds: float = 3600
    log_level: LogLevel = "INFO"


class GatewaySettings(QueueSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    graceful_shutdown_seconds: int = 30
    session_idle_timeout_seconds: float = 1800
    job_message_timeout_seconds: float = 60.0
    event_store_max_events_per_stream: int = 500
    event_store_max_streams: int = 10_000


class WorkerSettings(QueueSettings):
    replica_id: str = Field(default_factory=socket.gethostname)
    elicitation_mode: ElicitationMode = "continuation"
    answer_timeout_seconds: float = 120.0
    heartbeat_seconds: float = 1.0
    fetch_timeout_seconds: float = 2.0
    slow_job_max_seconds: int = 60
    slow_job_step_seconds: float = 1.0


class AutoscalerSettings(QueueSettings):
    compose_project: str = "mcp-phase4"
    min_workers: int = 1
    max_workers: int = 10
    target_jobs_per_worker: int = 2
    poll_interval_seconds: float = 2.0
    scale_down_cooldown_seconds: float = 20.0
    worker_stop_timeout_seconds: int = 10
