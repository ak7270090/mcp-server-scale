import os

import pytest
from mcp import types
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from tests.conftest import TEST_REPLICA_ID, TEST_SLOW_JOB_MAX_SECONDS

pytestmark = pytest.mark.anyio

STANDARD_TOOL_NAMES = {"get_replica_id", "increment_counter", "run_slow_job", "ask_confirmation"}


class ElicitationResponder:
    """Answers every elicitation request with a fixed result."""

    def __init__(self, result: types.ElicitResult) -> None:
        self._result = result

    async def answer(
        self, context: object, params: types.ElicitRequestParams
    ) -> types.ElicitResult:
        return self._result


class ProgressRecorder:
    """Collects progress values reported by the server."""

    def __init__(self) -> None:
        self.progress_values: list[float] = []

    async def record(self, progress: float, total: float | None, message: str | None) -> None:
        self.progress_values.append(progress)


async def test_lists_standard_tool_set(mcp_server: FastMCP) -> None:
    async with create_connected_server_and_client_session(mcp_server) as session:
        listed = await session.list_tools()

    assert {tool.name for tool in listed.tools} == STANDARD_TOOL_NAMES


async def test_get_replica_id_returns_configured_identity(mcp_server: FastMCP) -> None:
    async with create_connected_server_and_client_session(mcp_server) as session:
        result = await session.call_tool("get_replica_id")

    assert result.structuredContent == {"replica_id": TEST_REPLICA_ID, "process_id": os.getpid()}


async def test_increment_counter_counts_up_within_a_session(mcp_server: FastMCP) -> None:
    async with create_connected_server_and_client_session(mcp_server) as session:
        values = [
            (await session.call_tool("increment_counter")).structuredContent["result"]
            for _ in range(3)
        ]

    assert values == [1, 2, 3]


async def test_increment_counter_is_separate_per_session(mcp_server: FastMCP) -> None:
    async with create_connected_server_and_client_session(mcp_server) as first_session:
        await first_session.call_tool("increment_counter")
        await first_session.call_tool("increment_counter")
    async with create_connected_server_and_client_session(mcp_server) as second_session:
        result = await second_session.call_tool("increment_counter")

    assert result.structuredContent["result"] == 1


async def test_run_slow_job_reports_progress_every_second(mcp_server: FastMCP) -> None:
    recorder = ProgressRecorder()
    async with create_connected_server_and_client_session(mcp_server) as session:
        result = await session.call_tool(
            "run_slow_job", {"seconds": 3}, progress_callback=recorder.record
        )

    assert not result.isError
    assert recorder.progress_values == [1.0, 2.0, 3.0]


@pytest.mark.parametrize("seconds", [0, TEST_SLOW_JOB_MAX_SECONDS + 1])
async def test_run_slow_job_rejects_out_of_range_seconds(mcp_server: FastMCP, seconds: int) -> None:
    async with create_connected_server_and_client_session(mcp_server) as session:
        result = await session.call_tool("run_slow_job", {"seconds": seconds})

    assert result.isError


@pytest.mark.parametrize(
    ("elicit_result", "expected_answer"),
    [
        (types.ElicitResult(action="accept", content={"confirmed": True}), "confirmed"),
        (types.ElicitResult(action="accept", content={"confirmed": False}), "declined"),
        (types.ElicitResult(action="decline"), "decline"),
        (types.ElicitResult(action="cancel"), "cancel"),
    ],
)
async def test_ask_confirmation_returns_user_answer(
    mcp_server: FastMCP, elicit_result: types.ElicitResult, expected_answer: str
) -> None:
    responder = ElicitationResponder(elicit_result)
    async with create_connected_server_and_client_session(
        mcp_server, elicitation_callback=responder.answer
    ) as session:
        result = await session.call_tool("ask_confirmation", {"question": "Proceed?"})

    assert result.structuredContent["result"] == expected_answer
