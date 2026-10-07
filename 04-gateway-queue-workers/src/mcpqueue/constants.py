"""Fixed names shared by the gateway, the workers and the autoscaler."""

ENV_PREFIX = "MCP_"

SERVER_NAME = "mcp-scaling-lab"
SERVER_INSTRUCTIONS = (
    "Test server for the MCP scaling lab. Tool calls run on a pool of queue workers."
)
GATEWAY_APP_FACTORY = "mcpqueue.gateway.app:create_gateway_app_from_env"
HEALTH_CHECK_PATH = "/healthz"
HEALTH_CHECK_BODY = {"status": "ok"}
SESSION_ID_HEADER = "mcp-session-id"
LOCAL_SESSION_KEY_PREFIX = "local-"

JOB_STREAM_NAME = "JOBS"
JOB_SUBJECT = "jobs.submit"
JOB_CONSUMER_NAME = "workers"
DEAD_LETTER_STREAM_NAME = "DEAD_JOBS"
DEAD_LETTER_SUBJECT = "jobs.dead"
RESULTS_SUBJECT_PREFIX = "jobs.results"
ANSWERS_SUBJECT_PREFIX = "jobs.answers"
CANCEL_SUBJECT_PREFIX = "jobs.cancel"
MESSAGE_ID_HEADER = "Nats-Msg-Id"
SESSION_COUNTER_BUCKET = "session_counters"

TOOL_GET_REPLICA_ID = "get_replica_id"
TOOL_INCREMENT_COUNTER = "increment_counter"
TOOL_RUN_SLOW_JOB = "run_slow_job"
TOOL_ASK_CONFIRMATION = "ask_confirmation"

CONFIRMATION_ANSWER_CONFIRMED = "confirmed"
CONFIRMATION_ANSWER_DECLINED = "declined"
ELICITATION_ACTION_ACCEPT = "accept"

WORKER_SERVICE_NAME = "worker"
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"
COMPOSE_CONTAINER_NUMBER_LABEL = "com.docker.compose.container-number"
