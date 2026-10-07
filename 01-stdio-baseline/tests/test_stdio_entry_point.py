import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.anyio

STDIO_REPLICA_ID = "stdio-replica"


async def test_entry_point_serves_tools_over_stdio() -> None:
    server_parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcpserver"],
        env={"MCP_REPLICA_ID": STDIO_REPLICA_ID},
    )
    async with (
        stdio_client(server_parameters) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        identity = await session.call_tool("get_replica_id")
        counter_values = [
            (await session.call_tool("increment_counter")).structuredContent["result"]
            for _ in range(2)
        ]

    assert identity.structuredContent["replica_id"] == STDIO_REPLICA_ID
    assert counter_values == [1, 2]
