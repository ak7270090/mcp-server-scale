"""The standard tool set, as thin gateway tools: each call becomes a job for the workers."""

from mcp.server.fastmcp import Context, FastMCP

from mcpqueue.constants import (
    TOOL_ASK_CONFIRMATION,
    TOOL_GET_REPLICA_ID,
    TOOL_INCREMENT_COUNTER,
    TOOL_RUN_SLOW_JOB,
)
from mcpqueue.gateway.job_runner import JobRunner
from mcpqueue.schemas import ReplicaIdentity


class GatewayTools:
    """Same names and signatures as the earlier phases, so the harness runs unchanged."""

    def __init__(self, job_runner: JobRunner) -> None:
        self._job_runner = job_runner

    def register(self, mcp: FastMCP) -> None:
        for tool_function in (
            self.get_replica_id,
            self.increment_counter,
            self.run_slow_job,
            self.ask_confirmation,
        ):
            mcp.add_tool(tool_function)

    async def get_replica_id(self, ctx: Context) -> ReplicaIdentity:
        """Return the worker and process that handled this call."""
        result = await self._job_runner.run_tool(TOOL_GET_REPLICA_ID, {}, ctx)
        return ReplicaIdentity.model_validate(result)

    async def increment_counter(self, ctx: Context) -> int:
        """Add 1 to this session's counter and return the new value."""
        return await self._job_runner.run_tool(TOOL_INCREMENT_COUNTER, {}, ctx)

    async def run_slow_job(self, seconds: int, ctx: Context) -> str:
        """Wait the given number of seconds, reporting progress after each second."""
        return await self._job_runner.run_tool(TOOL_RUN_SLOW_JOB, {"seconds": seconds}, ctx)

    async def ask_confirmation(self, question: str, ctx: Context) -> str:
        """Ask the user a yes/no question and return their answer."""
        return await self._job_runner.run_tool(TOOL_ASK_CONFIRMATION, {"question": question}, ctx)
