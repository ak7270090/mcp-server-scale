import pytest

from mcpharness.client_factory import create_mcp_connection
from mcpharness.config import HarnessSettings
from mcpharness.scenario_steps import increment_session_counter

pytestmark = [pytest.mark.anyio, pytest.mark.affinity]


async def test_counter_counts_up_without_resets(harness_settings: HarnessSettings) -> None:
    expected_values = list(range(1, harness_settings.affinity_call_count + 1))
    async with create_mcp_connection(harness_settings) as connection:
        counter_values = [
            await increment_session_counter(connection.session) for _ in expected_values
        ]

    assert counter_values == expected_values
