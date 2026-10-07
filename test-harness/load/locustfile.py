"""Standard load profile (warm-up, steady, spike). Run: ``locust -f load/locustfile.py``."""

from urllib.parse import urlsplit

from locust import HttpUser, LoadTestShape, between, events, task
from locust.env import Environment

from mcpharness.config import load_harness_settings
from mcpharness.constants import (
    LOAD_REPLICA_REPORT_FILE,
    TOOL_GET_REPLICA_ID,
    TOOL_INCREMENT_COUNTER,
    TOOL_RUN_SLOW_JOB,
)
from mcpharness.locust_mcp_session import LocustMcpSession, McpRequestFailedError
from mcpharness.replica_metrics import ReplicaDistribution, write_markdown_report

settings = load_harness_settings()
target_url_parts = urlsplit(settings.target_url)
replica_distribution = ReplicaDistribution()


class McpUser(HttpUser):
    """One MCP session per simulated user, calling the standard tools in the plan's mix."""

    host = f"{target_url_parts.scheme}://{target_url_parts.netloc}"
    wait_time = between(settings.load_wait_min_seconds, settings.load_wait_max_seconds)

    def on_start(self) -> None:
        self.mcp_session = LocustMcpSession(self.client, target_url_parts.path)
        self.mcp_session.initialize()

    def on_stop(self) -> None:
        self.mcp_session.close()

    @task(60)
    def get_replica_id(self) -> None:
        try:
            identity = self.mcp_session.call_tool(TOOL_GET_REPLICA_ID)
        except McpRequestFailedError:
            replica_distribution.record_failure()
            return
        replica_distribution.record(f"{identity['replica_id']}/pid-{identity['process_id']}")

    @task(25)
    def increment_counter(self) -> None:
        try:
            self.mcp_session.call_tool(TOOL_INCREMENT_COUNTER)
        except McpRequestFailedError:
            return

    @task(15)
    def run_slow_job(self) -> None:
        try:
            self.mcp_session.call_tool(
                TOOL_RUN_SLOW_JOB, {"seconds": settings.load_slow_job_seconds}
            )
        except McpRequestFailedError:
            return


class StandardLoadShape(LoadTestShape):
    """Warm-up → steady → spike, with user counts and durations from harness settings."""

    def tick(self) -> tuple[int, float] | None:
        run_time = self.get_run_time()
        warmup_end = settings.load_warmup_seconds
        steady_end = warmup_end + settings.load_steady_seconds
        spike_end = steady_end + settings.load_spike_ramp_seconds
        if run_time < warmup_end:
            return settings.load_warmup_users, settings.load_warmup_users
        if run_time < steady_end:
            return settings.load_steady_users, settings.load_steady_users
        if run_time < spike_end:
            spawn_rate = settings.load_spike_users / settings.load_spike_ramp_seconds
            return settings.load_spike_users, spawn_rate
        return None


@events.test_stop.add_listener
def write_replica_report(environment: Environment, **kwargs: object) -> None:
    report_path = settings.results_dir / LOAD_REPLICA_REPORT_FILE
    write_markdown_report(
        report_path,
        "Load test: get_replica_id calls per serving unit",
        f"Target: `{settings.target_url}`\n\n{replica_distribution.to_markdown_table()}",
    )
