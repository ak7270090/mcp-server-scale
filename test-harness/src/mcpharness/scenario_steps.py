"""Reusable steps the test suites combine: call a tool, collect progress, answer elicitation."""

import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession, types

from mcpharness.constants import (
    CONFIRMATION_QUESTION,
    REPLICA_ID_PATTERN,
    STRUCTURED_RESULT_KEY,
    TOOL_ASK_CONFIRMATION,
    TOOL_GET_REPLICA_ID,
    TOOL_INCREMENT_COUNTER,
    TOOL_RUN_SLOW_JOB,
)


class ToolCallFailedError(RuntimeError):
    """The server answered a tool call with ``isError: true``."""


@dataclass(frozen=True)
class ReplicaIdentity:
    replica_id: str
    process_id: int

    @property
    def serving_unit(self) -> str:
        return f"{self.replica_id}/pid-{self.process_id}"


class ProgressCollector:
    """Progress callback that records every reported value."""

    def __init__(self) -> None:
        self.progress_values: list[float] = []

    async def record(self, progress: float, total: float | None, message: str | None) -> None:
        self.progress_values.append(progress)


class ConfirmationResponder:
    """Elicitation callback that always accepts with ``confirmed: true``."""

    def __init__(self) -> None:
        self.received_questions: list[str] = []

    async def answer(
        self, context: object, params: types.ElicitRequestParams
    ) -> types.ElicitResult:
        self.received_questions.append(params.message)
        return types.ElicitResult(action="accept", content={"confirmed": True})


def read_structured_result(result: types.CallToolResult) -> Any:
    if result.isError:
        error_text = " ".join(
            block.text for block in result.content if isinstance(block, types.TextContent)
        )
        raise ToolCallFailedError(error_text)
    structured = result.structuredContent or {}
    return structured.get(STRUCTURED_RESULT_KEY, structured)


async def fetch_replica_identity(session: ClientSession) -> ReplicaIdentity:
    structured = read_structured_result(await session.call_tool(TOOL_GET_REPLICA_ID))
    return ReplicaIdentity(replica_id=structured["replica_id"], process_id=structured["process_id"])


async def increment_session_counter(session: ClientSession) -> int:
    return read_structured_result(await session.call_tool(TOOL_INCREMENT_COUNTER))


async def run_slow_job_collecting_progress(session: ClientSession, seconds: int) -> list[float]:
    collector = ProgressCollector()
    result = await session.call_tool(
        TOOL_RUN_SLOW_JOB, {"seconds": seconds}, progress_callback=collector.record
    )
    read_structured_result(result)
    return collector.progress_values


async def ask_for_confirmation(session: ClientSession) -> str:
    result = await session.call_tool(TOOL_ASK_CONFIRMATION, {"question": CONFIRMATION_QUESTION})
    return read_structured_result(result)


def run_replica_command(command_template: str, replica_id: str, timeout_seconds: float) -> None:
    """Run a kill/restore command for one replica; the replica ID is validated before use."""
    if not re.fullmatch(REPLICA_ID_PATTERN, replica_id):
        raise ValueError(f"refusing to run a command for unexpected replica id {replica_id!r}")
    command = shlex.split(command_template.format(replica=replica_id))
    subprocess.run(command, check=True, timeout=timeout_seconds, capture_output=True)
