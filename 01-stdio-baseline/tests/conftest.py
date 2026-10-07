import pytest
from mcp.server.fastmcp import FastMCP

from mcpserver.app import create_mcp_server
from mcpserver.config import ServerSettings

TEST_REPLICA_ID = "test-replica"
TEST_SLOW_JOB_MAX_SECONDS = 5


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def mcp_server() -> FastMCP:
    settings = ServerSettings(
        replica_id=TEST_REPLICA_ID,
        slow_job_max_seconds=TEST_SLOW_JOB_MAX_SECONDS,
        slow_job_step_seconds=0.01,
    )
    return create_mcp_server(settings)
