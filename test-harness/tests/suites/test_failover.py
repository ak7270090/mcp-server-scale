import anyio
import pytest

from mcpharness.client_factory import create_mcp_connection
from mcpharness.config import HarnessSettings
from mcpharness.scenario_steps import (
    fetch_replica_identity,
    increment_session_counter,
    run_replica_command,
)

pytestmark = [pytest.mark.anyio, pytest.mark.failover]

CALLS_BEFORE_KILL = 3


async def test_session_state_survives_replica_kill(harness_settings: HarnessSettings) -> None:
    async with create_mcp_connection(harness_settings) as connection:
        for _ in range(CALLS_BEFORE_KILL):
            await increment_session_counter(connection.session)
        owning_replica_id = (await fetch_replica_identity(connection.session)).replica_id

        run_replica_command(
            harness_settings.kill_command,
            owning_replica_id,
            harness_settings.command_timeout_seconds,
        )
        try:
            await anyio.sleep(harness_settings.failover_settle_seconds)
            counter_after_kill = await increment_session_counter(connection.session)
        finally:
            run_replica_command(
                harness_settings.restore_command,
                owning_replica_id,
                harness_settings.command_timeout_seconds,
            )
            await anyio.sleep(harness_settings.restore_settle_seconds)

    assert counter_after_kill == CALLS_BEFORE_KILL + 1
