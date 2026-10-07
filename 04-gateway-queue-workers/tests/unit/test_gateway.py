import pytest
from mcp import types
from mcp.shared.memory import create_connected_server_and_client_session
from starlette.testclient import TestClient

from mcpqueue.config import GatewaySettings
from mcpqueue.constants import HEALTH_CHECK_BODY, HEALTH_CHECK_PATH, LOCAL_SESSION_KEY_PREFIX
from mcpqueue.gateway.app import create_gateway_app, create_gateway_server
from mcpqueue.job_messages import (
    ElicitationAnswer,
    JobFailed,
    JobInputRequired,
    JobProgress,
    JobRequest,
    JobResult,
    JobStarted,
)
from tests.unit.fakes import FakeJobBus

pytestmark = pytest.mark.anyio

GATEWAY_SETTINGS = GatewaySettings(job_message_timeout_seconds=0.5)


class ProgressRecorder:
    def __init__(self) -> None:
        self.progress_values: list[float] = []

    async def record(self, progress: float, total: float | None, message: str | None) -> None:
        self.progress_values.append(progress)


class ConfirmingUser:
    def __init__(self) -> None:
        self.questions: list[str] = []

    async def answer(
        self, context: object, params: types.ElicitRequestParams
    ) -> types.ElicitResult:
        self.questions.append(params.message)
        return types.ElicitResult(action="accept", content={"confirmed": True})


class FixedResultScript:
    """A worker that starts the job and returns one fixed result."""

    def __init__(self, result: object) -> None:
        self._result = result

    def __call__(self, job: JobRequest) -> list:
        return [
            JobStarted(worker_id="worker-1", delivery_attempt=1),
            JobResult(result=self._result),
        ]


def redelivered_slow_job(job: JobRequest) -> list:
    return [
        JobProgress(progress=1, total=3),
        JobProgress(progress=2, total=3),
        JobStarted(worker_id="worker-2", delivery_attempt=2),
        JobProgress(progress=1, total=3),
        JobProgress(progress=2, total=3),
        JobProgress(progress=3, total=3),
        JobResult(result="done"),
    ]


def failing_job(job: JobRequest) -> list:
    return [JobFailed(error="seconds must be between 1 and 60")]


def silent_workers(job: JobRequest) -> list:
    return []


def ask_and_wait(job: JobRequest) -> list:
    return [JobInputRequired(question="Proceed?")]


def finish_after_answer(job_id: str, answer: ElicitationAnswer) -> list:
    return [JobResult(result="confirmed" if answer.content["confirmed"] else "declined")]


def ask_with_saved_state(job: JobRequest) -> list:
    if job.continuation is None:
        return [JobInputRequired(question="Proceed?", continuation_state={"step": 1})]
    return [JobResult(result="confirmed")]


async def call_tool(
    fake_bus: FakeJobBus,
    tool_name: str,
    arguments: dict | None = None,
    elicitation_callback: object = None,
    progress_callback: object = None,
) -> types.CallToolResult:
    mcp = create_gateway_server(GATEWAY_SETTINGS, fake_bus)
    async with create_connected_server_and_client_session(
        mcp, elicitation_callback=elicitation_callback
    ) as session:
        return await session.call_tool(
            tool_name, arguments or {}, progress_callback=progress_callback
        )


async def test_returns_worker_result_as_tool_result() -> None:
    fake_bus = FakeJobBus(FixedResultScript({"replica_id": "worker-1", "process_id": 7}))

    result = await call_tool(fake_bus, "get_replica_id")

    assert result.structuredContent == {"replica_id": "worker-1", "process_id": 7}
    assert fake_bus.submitted_jobs[0].tool_name == "get_replica_id"


async def test_job_carries_a_session_key() -> None:
    fake_bus = FakeJobBus(FixedResultScript(1))

    await call_tool(fake_bus, "increment_counter")

    assert fake_bus.submitted_jobs[0].session_key.startswith(LOCAL_SESSION_KEY_PREFIX)


async def test_forwards_only_increasing_progress_after_redelivery() -> None:
    recorder = ProgressRecorder()

    result = await call_tool(
        FakeJobBus(redelivered_slow_job),
        "run_slow_job",
        {"seconds": 3},
        progress_callback=recorder.record,
    )

    assert result.structuredContent == {"result": "done"}
    assert recorder.progress_values == [1.0, 2.0, 3.0]


async def test_worker_failure_becomes_tool_error() -> None:
    fake_bus = FakeJobBus(failing_job)

    result = await call_tool(fake_bus, "run_slow_job", {"seconds": 99})

    assert result.isError
    assert "seconds must be between" in result.content[0].text
    assert fake_bus.cancelled_job_ids == []


async def test_full_queue_becomes_tool_error() -> None:
    result = await call_tool(FakeJobBus(FixedResultScript(1), is_queue_full=True), "get_replica_id")

    assert result.isError
    assert "queue is full" in result.content[0].text


async def test_silent_workers_time_out_and_job_is_cancelled() -> None:
    fake_bus = FakeJobBus(silent_workers)

    result = await call_tool(fake_bus, "get_replica_id")

    assert result.isError
    assert fake_bus.cancelled_job_ids == [fake_bus.submitted_jobs[0].job_id]


async def test_waiting_worker_receives_the_user_answer() -> None:
    fake_bus = FakeJobBus(ask_and_wait, finish_after_answer)
    user = ConfirmingUser()

    result = await call_tool(
        fake_bus, "ask_confirmation", {"question": "Proceed?"}, elicitation_callback=user.answer
    )

    assert result.structuredContent == {"result": "confirmed"}
    assert user.questions == ["Proceed?"]
    assert len(fake_bus.submitted_jobs) == 1
    assert fake_bus.sent_answers[0][1].action == "accept"


async def test_continuation_answer_is_queued_as_a_new_job() -> None:
    fake_bus = FakeJobBus(ask_with_saved_state)
    user = ConfirmingUser()

    result = await call_tool(
        fake_bus, "ask_confirmation", {"question": "Proceed?"}, elicitation_callback=user.answer
    )

    first_job, continuation_job = fake_bus.submitted_jobs
    assert result.structuredContent == {"result": "confirmed"}
    assert user.questions == ["Proceed?"]
    assert fake_bus.sent_answers == []
    assert continuation_job.job_id != first_job.job_id
    assert continuation_job.session_key == first_job.session_key
    assert continuation_job.continuation.state == {"step": 1}
    assert continuation_job.continuation.answer.content == {"confirmed": True}


def test_app_connects_job_bus_and_reports_health() -> None:
    fake_bus = FakeJobBus(FixedResultScript(1))

    with TestClient(create_gateway_app(GATEWAY_SETTINGS, fake_bus)) as client:
        response = client.get(HEALTH_CHECK_PATH)
        is_connected_while_running = fake_bus.is_connected

    assert response.json() == HEALTH_CHECK_BODY
    assert is_connected_while_running
    assert not fake_bus.is_connected
