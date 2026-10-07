import time

import anyio
import pytest
from mcp import types

from tests.integration.mcp_client import WorkerLog, open_gateway_session
from tests.integration.stack_control import (
    StackConfig,
    apply_stack_config,
    kill_worker,
    start_worker,
    write_result_section,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]

USER_THINKING_SECONDS = 1.0


class UserWhoseWorkerDies:
    """On the first question, kills the worker that asked it, thinks, then confirms."""

    def __init__(self, worker_log: WorkerLog) -> None:
        self._worker_log = worker_log
        self.questions: list[str] = []
        self.killed_workers: list[str] = []

    async def answer(
        self, context: object, params: types.ElicitRequestParams
    ) -> types.ElicitResult:
        self.questions.append(params.message)
        if not self.killed_workers:
            worker_to_kill = self._worker_log.latest_worker
            await anyio.to_thread.run_sync(kill_worker, worker_to_kill)
            self.killed_workers.append(worker_to_kill)
            await anyio.sleep(USER_THINKING_SECONDS)
        return types.ElicitResult(action="accept", content={"confirmed": True})


@pytest.mark.parametrize(
    ("elicitation_mode", "expected_question_count"),
    [("worker_waits", 2), ("continuation", 1)],
)
async def test_confirmation_survives_worker_kill_while_user_thinks(
    elicitation_mode: str, expected_question_count: int
) -> None:
    apply_stack_config(StackConfig(worker_count=2, elicitation_mode=elicitation_mode))
    worker_log = WorkerLog()
    user = UserWhoseWorkerDies(worker_log)
    started_at = time.monotonic()
    async with open_gateway_session(
        elicitation_callback=user.answer, logging_callback=worker_log.record
    ) as session:
        result = await session.call_tool("ask_confirmation", {"question": "Proceed?"})
    elapsed_seconds = time.monotonic() - started_at
    for killed_worker in user.killed_workers:
        await anyio.to_thread.run_sync(start_worker, killed_worker)
    write_result_section(
        f"elicitation-{elicitation_mode}.md",
        f"ask_confirmation with the asking worker killed ({elicitation_mode})",
        f"Questions shown to the user: {len(user.questions)}\n\n"
        f"Job attempts (attempt, worker): {worker_log.attempts}\n\n"
        f"Answer: {result.structuredContent}\n\nTotal time: {elapsed_seconds:.1f} s",
    )

    assert result.structuredContent == {"result": "confirmed"}
    assert len(user.questions) == expected_question_count
