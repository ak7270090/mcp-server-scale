import pytest

from mcpharness.client_factory import create_http_client, create_mcp_connection, open_raw_session
from mcpharness.config import HarnessSettings
from mcpharness.constants import METHOD_TOOLS_LIST, STANDARD_TOOL_NAMES
from mcpharness.raw_protocol import build_mcp_headers, build_request
from mcpharness.scenario_steps import fetch_replica_identity, run_slow_job_collecting_progress

pytestmark = [pytest.mark.anyio, pytest.mark.conformance]

UNKNOWN_SESSION_ID = "unknown-session-0000"


async def test_lists_standard_tool_set(harness_settings: HarnessSettings) -> None:
    async with create_mcp_connection(harness_settings) as connection:
        listed = await connection.session.list_tools()

    assert {tool.name for tool in listed.tools} == STANDARD_TOOL_NAMES


async def test_reports_replica_identity(harness_settings: HarnessSettings) -> None:
    async with create_mcp_connection(harness_settings) as connection:
        identity = await fetch_replica_identity(connection.session)

    assert identity.replica_id
    assert identity.process_id > 0


async def test_slow_job_reports_progress_each_second(harness_settings: HarnessSettings) -> None:
    async with create_mcp_connection(harness_settings) as connection:
        progress_values = await run_slow_job_collecting_progress(
            connection.session, harness_settings.slow_job_seconds
        )

    assert progress_values == [
        float(step) for step in range(1, harness_settings.slow_job_seconds + 1)
    ]


async def test_rejects_request_without_session_id(harness_settings: HarnessSettings) -> None:
    async with create_http_client(harness_settings) as http_client:
        response = await http_client.post(
            harness_settings.target_url,
            json=build_request(METHOD_TOOLS_LIST, {}, request_id=1),
            headers=build_mcp_headers(),
        )

    assert response.status_code == 400


async def test_rejects_unknown_session_id(harness_settings: HarnessSettings) -> None:
    async with create_http_client(harness_settings) as http_client:
        response = await http_client.post(
            harness_settings.target_url,
            json=build_request(METHOD_TOOLS_LIST, {}, request_id=1),
            headers=build_mcp_headers(session_id=UNKNOWN_SESSION_ID),
        )

    assert response.status_code == 404


async def test_rejects_session_after_delete(harness_settings: HarnessSettings) -> None:
    async with create_http_client(harness_settings) as http_client:
        raw_session = await open_raw_session(http_client, harness_settings.target_url)
        delete_response = await http_client.delete(
            harness_settings.target_url, headers=raw_session.headers()
        )
        after_delete_response = await http_client.post(
            harness_settings.target_url,
            json=build_request(METHOD_TOOLS_LIST, {}, request_id=2),
            headers=raw_session.headers(),
        )

    assert delete_response.status_code in (200, 204)
    assert after_delete_response.status_code == 404
