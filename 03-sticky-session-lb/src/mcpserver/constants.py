"""Fixed values shared by the server modules."""

SERVER_NAME = "mcp-scaling-lab"
SERVER_INSTRUCTIONS = (
    "Test server for the MCP scaling lab. Every tool reveals one scaling behaviour."
)
ENV_PREFIX = "MCP_"
ASGI_APP_FACTORY = "mcpserver.app:create_asgi_app"

HEALTH_CHECK_PATH = "/healthz"
HEALTH_CHECK_BODY = {"status": "ok"}
SESSION_ID_HEADER = b"mcp-session-id"
SESSION_ID_SEPARATOR = "."

TRACE_SERVICE_NAME = "mcp-scaling-lab"
TRACE_EXPORT_PATH = "/v1/traces"
SPAN_ATTRIBUTE_SESSION_ID = "mcp.session_id"

CONFIRMATION_ANSWER_CONFIRMED = "confirmed"
CONFIRMATION_ANSWER_DECLINED = "declined"
ELICITATION_ACTION_ACCEPT = "accept"
