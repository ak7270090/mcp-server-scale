"""Fixed names and values used across the gateway."""

ENV_PREFIX = "MCP_"

SERVER_NAME = "api-to-mcp-gateway"
SERVER_INSTRUCTIONS = (
    "Tools generated from REST (OpenAPI) and gRPC (reflection) services. "
    "Pass `fields` to receive only the result fields you need."
)
GATEWAY_APP_FACTORY = "apigateway.app:create_gateway_app_from_env"

MCP_PATH = "/mcp"
HEALTH_CHECK_PATH = "/healthz"
REGISTRY_PATH = "/registry"
FACADE_TOOLS_PATH = "/facade/tools"
FACADE_TOOL_PATH = "/facade/tools/{tool_name}"
FACADE_OPENAPI_PATH = "/facade/openapi.json"
HEALTH_CHECK_BODY = {"status": "ok"}

TOOL_NAME_SEPARATOR = "_"
FIELDS_ARGUMENT = "fields"
WRAPPED_RESULT_KEY = "result"
BODY_ARGUMENT = "body"
BODY_ARGUMENT_PREFIX = "body_"
PASSTHROUGH_HEADERS = ("authorization", "traceparent")
HTTP_METHODS = ("get", "post", "put", "patch", "delete")
JSON_MEDIA_TYPE = "application/json"
SUCCESS_STATUS_PATTERN = r"^2\d\d$"
COMPONENT_REFERENCE_PREFIX = "#/"
REDACTED_TEXT = "[REDACTED]"
REFLECTION_SERVICE_PREFIX = "grpc.reflection."
INT64_PATTERN = r"^-?\d+$"
EMPTY_RESULT_TEXT = "OK"

DEFAULT_REDACTION_PATTERNS = {
    "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "phone": r"\+\d[\d\s().-]{7,}\d",
    "card_number": r"\b(?:\d[ -]?){12,15}\d\b",
}

DISCOVERY_SEARCH_TOOL = "search_tools"
DISCOVERY_SCHEMA_TOOL = "get_tool_schema"
DISCOVERY_INVOKE_TOOL = "invoke_tool"
