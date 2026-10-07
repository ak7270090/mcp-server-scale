"""Backend failures (HTTP status, gRPC status, transport) → what the MCP client is told."""

import json
from dataclasses import dataclass

import grpc

RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 502, 503, 504})
RETRYABLE_GRPC_CODES = frozenset(
    {
        grpc.StatusCode.UNAVAILABLE,
        grpc.StatusCode.DEADLINE_EXCEEDED,
        grpc.StatusCode.RESOURCE_EXHAUSTED,
        grpc.StatusCode.ABORTED,
    }
)
RETRYABLE_SUFFIX = " (temporary failure; retrying may succeed)"


@dataclass(frozen=True)
class BackendFailure:
    message: str
    is_retryable: bool

    def to_tool_error_text(self) -> str:
        return self.message + (RETRYABLE_SUFFIX if self.is_retryable else "")


class BackendCallError(Exception):
    """A backend call failed; becomes an ``isError`` tool result the model can act on."""

    def __init__(self, failure: BackendFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


def read_error_detail(body_text: str) -> str:
    """FastAPI-style ``{"detail": ...}`` when present, else the raw body."""
    try:
        body = json.loads(body_text)
    except ValueError:
        return body_text.strip()
    if isinstance(body, dict) and "detail" in body:
        detail = body["detail"]
        return detail if isinstance(detail, str) else json.dumps(detail)
    return json.dumps(body)


def map_http_failure(status_code: int, body_text: str) -> BackendFailure:
    return BackendFailure(
        message=f"backend returned HTTP {status_code}: {read_error_detail(body_text)}",
        is_retryable=status_code in RETRYABLE_HTTP_STATUSES,
    )


def map_grpc_failure(code: grpc.StatusCode, details: str | None) -> BackendFailure:
    return BackendFailure(
        message=f"backend returned gRPC {code.name}: {details or ''}".rstrip(),
        is_retryable=code in RETRYABLE_GRPC_CODES,
    )


def map_transport_failure(error: Exception) -> BackendFailure:
    return BackendFailure(
        message=f"backend unreachable: {type(error).__name__} {error}".rstrip(),
        is_retryable=True,
    )
