"""Session IDs that start with the replica ID, so a load balancer can route on the prefix."""

from mcp.server.auth.middleware.bearer_auth import AuthorizationContext
from mcp.server.fastmcp import FastMCP
from mcp.server.streamable_http import EventStore, StreamableHTTPServerTransport
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from mcpserver.config import ServerSettings
from mcpserver.constants import SESSION_ID_SEPARATOR


class ReplicaPrefixedSessionManager(StreamableHTTPSessionManager):
    """Renames each new session from ``<uuid>`` to ``<replica_id>.<uuid>``.

    mcp 1.30 has no public hook for session ID generation, so this overrides the private
    ``_admit_session`` step. ``test_session_id_generator.py`` fails if an SDK upgrade breaks it.
    """

    def __init__(self, *, session_id_prefix: str, **session_manager_options: object) -> None:
        super().__init__(**session_manager_options)
        self._session_id_prefix = session_id_prefix

    def _admit_session(
        self, requestor: AuthorizationContext | None
    ) -> StreamableHTTPServerTransport | None:
        transport = super()._admit_session(requestor)
        if transport is None:
            return None
        generated_session_id = transport.mcp_session_id
        prefixed_session_id = (
            f"{self._session_id_prefix}{SESSION_ID_SEPARATOR}{generated_session_id}"
        )
        transport.mcp_session_id = prefixed_session_id
        self._server_instances[prefixed_session_id] = self._server_instances.pop(
            generated_session_id
        )
        if generated_session_id in self._session_owners:
            self._session_owners[prefixed_session_id] = self._session_owners.pop(
                generated_session_id
            )
        return transport


def install_replica_prefixed_session_manager(
    mcp: FastMCP, settings: ServerSettings, event_store: EventStore
) -> None:
    """Hand FastMCP our session manager; ``streamable_http_app()`` reuses an existing one."""
    mcp._session_manager = ReplicaPrefixedSessionManager(
        session_id_prefix=settings.replica_id,
        app=mcp._mcp_server,
        event_store=event_store,
        security_settings=mcp.settings.transport_security,
        max_request_body_size=mcp.settings.max_request_body_size,
        session_idle_timeout=mcp.settings.session_idle_timeout,
        max_sessions=mcp.settings.max_sessions,
    )
