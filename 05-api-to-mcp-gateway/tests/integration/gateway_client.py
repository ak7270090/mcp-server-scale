"""Helpers for integration tests against the Compose stack."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

PHASE_DIRECTORY = Path(__file__).resolve().parents[2]
OVERRIDES_FILE = PHASE_DIRECTORY / "config" / "tool_overrides.yaml"
RESULTS_DIRECTORY = PHASE_DIRECTORY / "results" / "integration"
GATEWAY_BASE_URL = "http://localhost:8000"
GATEWAY_MCP_URL = f"{GATEWAY_BASE_URL}/mcp"
REQUEST_TIMEOUT_SECONDS = 60
PASSTHROUGH_HEADERS = {
    "Authorization": "Bearer integration-token",
    "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
}


@asynccontextmanager
async def open_gateway_session(
    headers: dict[str, str] | None = None,
) -> AsyncIterator[ClientSession]:
    async with (
        httpx.AsyncClient(
            headers=headers or {}, timeout=httpx.Timeout(30, read=REQUEST_TIMEOUT_SECONDS)
        ) as http_client,
        streamable_http_client(GATEWAY_MCP_URL, http_client=http_client) as (read, write, _),
        ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=REQUEST_TIMEOUT_SECONDS)
        ) as session,
    ):
        await session.initialize()
        yield session


def run_schemathesis(report_directory: Path, max_examples: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "schemathesis.cli",
            "run",
            f"{GATEWAY_BASE_URL}/facade/openapi.json",
            "--url",
            GATEWAY_BASE_URL,
            "--checks",
            "not_a_server_error,response_schema_conformance,status_code_conformance",
            "--max-examples",
            str(max_examples),
            "--report",
            "junit",
            "--report-dir",
            str(report_directory),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        timeout=900,
        check=False,
    )
