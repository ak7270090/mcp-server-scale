import pytest
from mcp.server.fastmcp import FastMCP

from mcpserver.app import create_event_store, create_mcp_server
from mcpserver.config import ServerSettings

TEST_REPLICA_ID = "test-replica"
TEST_SLOW_JOB_MAX_SECONDS = 5


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def server_settings() -> ServerSettings:
    return ServerSettings(
        replica_id=TEST_REPLICA_ID,
        slow_job_max_seconds=TEST_SLOW_JOB_MAX_SECONDS,
        slow_job_step_seconds=0.01,
    )


@pytest.fixture
def mcp_server(server_settings: ServerSettings) -> FastMCP:
    return create_mcp_server(server_settings, create_event_store(server_settings))
