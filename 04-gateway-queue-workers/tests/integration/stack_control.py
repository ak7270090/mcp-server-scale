"""Drives the Compose stack for integration tests: worker count, worker mode, queue size."""

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

PHASE_DIRECTORY = Path(__file__).resolve().parents[2]
RESULTS_DIRECTORY = PHASE_DIRECTORY / "results" / "integration"
GATEWAY_URL = "http://localhost:8000/mcp"
COMPOSE_COMMAND_TIMEOUT_SECONDS = 300
WORKER_FILTERS = [
    "--filter",
    "label=com.docker.compose.project=mcp-phase4",
    "--filter",
    "label=com.docker.compose.service=worker",
]


@dataclass(frozen=True)
class StackConfig:
    worker_count: int = 3
    elicitation_mode: str = "continuation"
    queue_max_pending: int = 1000
    is_autoscaled: bool = False
    min_workers: int = 1
    max_workers: int = 10
    scale_down_cooldown_seconds: int = 10


def run_docker(arguments: list[str], environment: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["docker", *arguments],
        cwd=PHASE_DIRECTORY,
        env={**os.environ, **(environment or {})},
        capture_output=True,
        text=True,
        check=True,
        timeout=COMPOSE_COMMAND_TIMEOUT_SECONDS,
    )
    return completed.stdout


def apply_stack_config(config: StackConfig) -> None:
    """Bring the stack to ``config``; Compose recreates only services whose settings changed."""
    environment = {
        "MCP_ELICITATION_MODE": config.elicitation_mode,
        "MCP_QUEUE_MAX_PENDING": str(config.queue_max_pending),
        "MCP_MIN_WORKERS": str(config.min_workers),
        "MCP_MAX_WORKERS": str(config.max_workers),
        "MCP_SCALE_DOWN_COOLDOWN_SECONDS": str(config.scale_down_cooldown_seconds),
    }
    profile_arguments = ["--profile", "autoscale"] if config.is_autoscaled else []
    if not config.is_autoscaled:
        run_docker(["compose", "--profile", "autoscale", "rm", "-sf", "autoscaler"], environment)
    run_docker(
        [
            "compose",
            *profile_arguments,
            "up",
            "-d",
            "--wait",
            "--scale",
            f"worker={config.worker_count}",
        ],
        environment,
    )


def list_running_worker_ids() -> list[str]:
    """Short container IDs, which are also the workers' hostnames (their replica IDs)."""
    output = run_docker(["ps", *WORKER_FILTERS, "--format", "{{.ID}}"])
    return [line for line in output.splitlines() if line]


def kill_worker(worker_id: str) -> None:
    run_docker(["kill", worker_id])


def start_worker(worker_id: str) -> None:
    run_docker(["start", worker_id])


def write_result_section(file_name: str, title: str, body: str) -> None:
    RESULTS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    (RESULTS_DIRECTORY / file_name).write_text(
        f"# {title}\n\nGenerated {generated_at}\n\n{body}\n", encoding="utf-8"
    )


def format_json(value: object) -> str:
    return json.dumps(value, indent=2)
