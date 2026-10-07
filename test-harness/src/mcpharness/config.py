"""Harness settings from ``HARNESS_*`` environment variables or the ``HARNESS_ENV_FILE`` file."""

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from mcpharness.constants import ENV_FILE_VARIABLE, ENV_PREFIX


class HarnessSettings(BaseSettings):
    """Which server to test, what to expect from it, and how hard to push it."""

    model_config = SettingsConfigDict(env_prefix=ENV_PREFIX, extra="ignore")

    target_url: str = "http://localhost:8000/mcp"
    expected_replica_count: int = 1
    expected_failures: set[str] = set()
    skipped_suites: set[str] = set()
    reuse_connections: bool = True

    request_timeout_seconds: float = 15.0
    stream_read_timeout_seconds: float = 60.0

    affinity_call_count: int = 200
    distribution_session_count: int = 30
    distribution_max_share_deviation: float = 0.15
    slow_job_seconds: int = 3
    resumability_events_before_disconnect: int = 1
    resumability_max_reconnects: int = 5
    resumability_reconnect_delay_seconds: float = 0.5

    kill_command: str = "docker kill {replica}"
    restore_command: str = "docker start {replica}"
    failover_settle_seconds: float = 5.0
    restore_settle_seconds: float = 10.0
    command_timeout_seconds: float = 30.0

    load_warmup_users: int = 10
    load_warmup_seconds: int = 60
    load_steady_users: int = 100
    load_steady_seconds: int = 300
    load_spike_users: int = 300
    load_spike_ramp_seconds: int = 30
    load_wait_min_seconds: float = 0.5
    load_wait_max_seconds: float = 1.5
    load_slow_job_seconds: int = 2

    results_dir: Path = Path("results")


def load_harness_settings() -> HarnessSettings:
    """Read settings; real environment variables override the optional ``HARNESS_ENV_FILE``."""
    env_file = os.environ.get(ENV_FILE_VARIABLE)
    return HarnessSettings(_env_file=env_file) if env_file else HarnessSettings()
