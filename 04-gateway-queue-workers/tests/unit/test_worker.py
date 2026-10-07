import pytest

from mcpqueue.config import WorkerSettings
from mcpqueue.job_messages import Continuation, ElicitationAnswer, JobRequest
from mcpqueue.worker.session_counters import SessionCounterStore
from mcpqueue.worker.tool_handlers import JobCancelledError, ToolHandlers, UnknownToolError
from tests.unit.fakes import FakeCounterBucket, FakeJobContext

pytestmark = pytest.mark.anyio

CONFIRMED = ElicitationAnswer(action="accept", content={"confirmed": True})
DECLINED = ElicitationAnswer(action="accept", content={"confirmed": False})


def build_handlers(elicitation_mode: str = "continuation") -> ToolHandlers:
    settings = WorkerSettings(
        replica_id="worker-test",
        elicitation_mode=elicitation_mode,
        slow_job_max_seconds=5,
        slow_job_step_seconds=0,
    )
    return ToolHandlers(settings, SessionCounterStore(FakeCounterBucket()))


def build_job(tool_name: str, arguments: dict | None = None, **fields: object) -> JobRequest:
    return JobRequest(tool_name=tool_name, arguments=arguments or {}, session_key="s1", **fields)


async def test_counter_increments_per_session_and_ignores_redelivered_job() -> None:
    store = SessionCounterStore(FakeCounterBucket())

    first = await store.increment("s1", "job-1")
    second = await store.increment("s1", "job-2")
    redelivered = await store.increment("s1", "job-2")
    other_session = await store.increment("s2", "job-3")

    assert (first, second, redelivered, other_session) == (1, 2, 2, 1)


async def test_counter_retries_after_a_concurrent_write() -> None:
    store = SessionCounterStore(FakeCounterBucket(conflicts_to_inject=2))

    assert await store.increment("s1", "job-1") == 1
    assert await store.increment("s1", "job-2") == 2


async def test_get_replica_id_reports_worker_identity() -> None:
    result = await build_handlers().handle(build_job("get_replica_id"), FakeJobContext())

    assert result.result["replica_id"] == "worker-test"


async def test_increment_counter_uses_job_session_key() -> None:
    handlers = build_handlers()

    first = await handlers.handle(build_job("increment_counter"), FakeJobContext())
    second = await handlers.handle(build_job("increment_counter"), FakeJobContext())

    assert (first.result, second.result) == (1, 2)


async def test_slow_job_reports_progress_each_step() -> None:
    job_context = FakeJobContext()

    result = await build_handlers().handle(build_job("run_slow_job", {"seconds": 3}), job_context)

    assert job_context.progress_values == [1, 2, 3]
    assert "3 seconds" in result.result


async def test_slow_job_stops_when_cancelled() -> None:
    job_context = FakeJobContext(cancel_after_sleeps=1)

    with pytest.raises(JobCancelledError):
        await build_handlers().handle(build_job("run_slow_job", {"seconds": 5}), job_context)
    assert job_context.progress_values == [1]


async def test_slow_job_rejects_out_of_range_seconds() -> None:
    with pytest.raises(ValueError, match="between 1 and 5"):
        await build_handlers().handle(build_job("run_slow_job", {"seconds": 9}), FakeJobContext())


async def test_unknown_tool_is_rejected() -> None:
    with pytest.raises(UnknownToolError):
        await build_handlers().handle(build_job("no_such_tool"), FakeJobContext())


async def test_waiting_worker_returns_the_answer() -> None:
    job_context = FakeJobContext(answer=DECLINED)
    job = build_job("ask_confirmation", {"question": "Proceed?"})

    result = await build_handlers("worker_waits").handle(job, job_context)

    assert job_context.questions_waited_on == ["Proceed?"]
    assert result.result == "declined"


async def test_continuation_mode_saves_state_and_finishes_without_result() -> None:
    job_context = FakeJobContext()
    job = build_job("ask_confirmation", {"question": "Proceed?"})

    result = await build_handlers("continuation").handle(job, job_context)

    assert result is None
    assert job_context.continuations_requested == [("Proceed?", {"question": "Proceed?"})]


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (CONFIRMED, "confirmed"),
        (DECLINED, "declined"),
        (ElicitationAnswer(action="cancel"), "cancel"),
    ],
)
async def test_continuation_job_returns_the_answer(
    answer: ElicitationAnswer, expected: str
) -> None:
    job = build_job(
        "ask_confirmation",
        {"question": "Proceed?"},
        continuation=Continuation(state={"question": "Proceed?"}, answer=answer),
    )

    result = await build_handlers("continuation").handle(job, FakeJobContext())

    assert result.result == expected
