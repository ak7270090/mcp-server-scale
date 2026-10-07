import pytest

from mcpharness.client_factory import create_mcp_connection
from mcpharness.config import HarnessSettings
from mcpharness.constants import DISTRIBUTION_REPORT_FILE
from mcpharness.replica_metrics import ReplicaDistribution, write_markdown_report
from mcpharness.scenario_steps import fetch_replica_identity

pytestmark = [pytest.mark.anyio, pytest.mark.distribution]


async def test_new_sessions_spread_across_replicas(harness_settings: HarnessSettings) -> None:
    distribution = ReplicaDistribution()
    for _ in range(harness_settings.distribution_session_count):
        async with create_mcp_connection(harness_settings) as connection:
            identity = await fetch_replica_identity(connection.session)
        distribution.record(identity.serving_unit)
    write_markdown_report(
        harness_settings.results_dir / DISTRIBUTION_REPORT_FILE,
        "New sessions per serving unit",
        f"Target: `{harness_settings.target_url}`\n\n{distribution.to_markdown_table()}",
    )

    assert distribution.serving_unit_count == harness_settings.expected_replica_count
    assert (
        distribution.max_share_deviation(harness_settings.expected_replica_count)
        <= harness_settings.distribution_max_share_deviation
    ), distribution.to_markdown_table()
