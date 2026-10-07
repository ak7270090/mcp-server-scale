import pytest

from mcpharness.client_factory import create_mcp_connection
from mcpharness.config import HarnessSettings
from mcpharness.scenario_steps import fetch_replica_identity

pytestmark = [pytest.mark.anyio, pytest.mark.pinning]


async def test_session_stays_on_one_serving_unit(harness_settings: HarnessSettings) -> None:
    async with create_mcp_connection(harness_settings) as connection:
        serving_units = {
            (await fetch_replica_identity(connection.session)).serving_unit
            for _ in range(harness_settings.affinity_call_count)
        }

    assert len(serving_units) == 1, serving_units
