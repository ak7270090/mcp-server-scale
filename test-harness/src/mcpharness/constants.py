"""Fixed protocol values and names used across the harness."""

ENV_PREFIX = "HARNESS_"
ENV_FILE_VARIABLE = "HARNESS_ENV_FILE"

JSONRPC_VERSION = "2.0"
SESSION_ID_HEADER = "mcp-session-id"
PROTOCOL_VERSION_HEADER = "mcp-protocol-version"
LAST_EVENT_ID_HEADER = "last-event-id"
ACCEPT_HEADER_VALUE = "application/json, text/event-stream"
SSE_CONTENT_TYPE = "text/event-stream"
JSON_CONTENT_TYPE = "application/json"
DEFAULT_PROTOCOL_VERSION = "2025-11-25"

METHOD_INITIALIZE = "initialize"
METHOD_INITIALIZED = "notifications/initialized"
METHOD_TOOLS_LIST = "tools/list"
METHOD_TOOLS_CALL = "tools/call"
METHOD_PROGRESS = "notifications/progress"

HARNESS_CLIENT_NAME = "mcp-scaling-harness"
HARNESS_CLIENT_VERSION = "0.1.0"

TOOL_GET_REPLICA_ID = "get_replica_id"
TOOL_INCREMENT_COUNTER = "increment_counter"
TOOL_RUN_SLOW_JOB = "run_slow_job"
TOOL_ASK_CONFIRMATION = "ask_confirmation"
STANDARD_TOOL_NAMES = frozenset(
    {TOOL_GET_REPLICA_ID, TOOL_INCREMENT_COUNTER, TOOL_RUN_SLOW_JOB, TOOL_ASK_CONFIRMATION}
)
STRUCTURED_RESULT_KEY = "result"
CONFIRMATION_QUESTION = "Harness check: confirm this action?"
CONFIRMATION_ANSWER_CONFIRMED = "confirmed"

SUITE_CONFORMANCE = "conformance"
SUITE_DISTRIBUTION = "distribution"
SUITE_AFFINITY = "affinity"
SUITE_PINNING = "pinning"
SUITE_FAILOVER = "failover"
SUITE_RESUMABILITY = "resumability"
SUITE_ELICITATION = "elicitation"
ALL_SUITES = frozenset(
    {
        SUITE_CONFORMANCE,
        SUITE_DISTRIBUTION,
        SUITE_AFFINITY,
        SUITE_PINNING,
        SUITE_FAILOVER,
        SUITE_RESUMABILITY,
        SUITE_ELICITATION,
    }
)

REPLICA_ID_PATTERN = r"^[A-Za-z0-9_.-]+$"
DISTRIBUTION_REPORT_FILE = "distribution.md"
LOAD_REPLICA_REPORT_FILE = "load-replica-distribution.md"
