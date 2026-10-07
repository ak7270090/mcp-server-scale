"""The standard tool set used by every scaling pattern."""

import os
import weakref

import anyio
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from mcpserver.config import ServerSettings
from mcpserver.constants import (
    CONFIRMATION_ANSWER_CONFIRMED,
    CONFIRMATION_ANSWER_DECLINED,
    ELICITATION_ACTION_ACCEPT,
)
from mcpserver.schemas import ConfirmationAnswer, ReplicaIdentity


class SessionCounterStore:
    """Per-session counters kept in process memory; a counter disappears with its session."""

    def __init__(self) -> None:
        self._counters: weakref.WeakKeyDictionary[ServerSession, int] = weakref.WeakKeyDictionary()

    def increment(self, session: ServerSession) -> int:
        next_value = self._counters.get(session, 0) + 1
        self._counters[session] = next_value
        return next_value


class ReplicaTools:
    """Tool implementations; each method is registered as one MCP tool."""

    def __init__(self, settings: ServerSettings, counter_store: SessionCounterStore) -> None:
        self._settings = settings
        self._counter_store = counter_store

    def register(self, mcp: FastMCP) -> None:
        for tool_function in (
            self.get_replica_id,
            self.increment_counter,
            self.run_slow_job,
            self.ask_confirmation,
        ):
            mcp.add_tool(tool_function)

    async def get_replica_id(self) -> ReplicaIdentity:
        """Return the replica and process that handled this call."""
        return ReplicaIdentity(replica_id=self._settings.replica_id, process_id=os.getpid())

    async def increment_counter(self, ctx: Context) -> int:
        """Add 1 to this session's counter and return the new value."""
        return self._counter_store.increment(ctx.session)

    async def run_slow_job(self, seconds: int, ctx: Context) -> str:
        """Wait the given number of seconds, reporting progress after each second."""
        if not 1 <= seconds <= self._settings.slow_job_max_seconds:
            raise ValueError(f"seconds must be between 1 and {self._settings.slow_job_max_seconds}")
        for completed_seconds in range(1, seconds + 1):
            await anyio.sleep(self._settings.slow_job_step_seconds)
            await ctx.report_progress(
                completed_seconds, seconds, f"{completed_seconds}/{seconds} seconds done"
            )
        return f"slow job finished after {seconds} seconds"

    async def ask_confirmation(self, question: str, ctx: Context) -> str:
        """Ask the user a yes/no question and return their answer."""
        result = await ctx.elicit(question, ConfirmationAnswer)
        if result.action != ELICITATION_ACTION_ACCEPT:
            return result.action
        if result.data.confirmed:
            return CONFIRMATION_ANSWER_CONFIRMED
        return CONFIRMATION_ANSWER_DECLINED
