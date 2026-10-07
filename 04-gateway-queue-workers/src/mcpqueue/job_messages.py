"""Messages exchanged between the gateway and the workers, and the subjects they travel on."""

from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, TypeAdapter

from mcpqueue.constants import (
    ANSWERS_SUBJECT_PREFIX,
    CANCEL_SUBJECT_PREFIX,
    RESULTS_SUBJECT_PREFIX,
)


class ElicitationAnswer(BaseModel):
    """The user's response: ``accept`` (with content), ``decline`` or ``cancel``."""

    action: str
    content: dict[str, Any] | None = None


class Continuation(BaseModel):
    """State a worker saved before asking the user, plus the user's answer."""

    state: dict[str, Any]
    answer: ElicitationAnswer


class JobRequest(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid4().hex)
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    session_key: str
    continuation: Continuation | None = None


class JobStarted(BaseModel):
    kind: Literal["started"] = "started"
    worker_id: str
    delivery_attempt: int


class JobProgress(BaseModel):
    kind: Literal["progress"] = "progress"
    progress: float
    total: float | None = None
    message: str | None = None


class JobInputRequired(BaseModel):
    """The worker needs an answer from the user.

    ``continuation_state`` set: the worker has finished; queue a continuation job with the answer.
    ``continuation_state`` empty: the worker is waiting; publish the answer on the answers subject.
    """

    kind: Literal["input_required"] = "input_required"
    question: str
    continuation_state: dict[str, Any] | None = None


class JobResult(BaseModel):
    kind: Literal["result"] = "result"
    result: Any


class JobFailed(BaseModel):
    kind: Literal["failed"] = "failed"
    error: str


WorkerMessage = Annotated[
    JobStarted | JobProgress | JobInputRequired | JobResult | JobFailed,
    Field(discriminator="kind"),
]
worker_message_adapter: TypeAdapter[WorkerMessage] = TypeAdapter(WorkerMessage)


def parse_worker_message(payload: bytes) -> WorkerMessage:
    return worker_message_adapter.validate_json(payload)


def build_results_subject(job_id: str) -> str:
    return f"{RESULTS_SUBJECT_PREFIX}.{job_id}"


def build_answers_subject(job_id: str) -> str:
    return f"{ANSWERS_SUBJECT_PREFIX}.{job_id}"


def build_cancel_subject(job_id: str) -> str:
    return f"{CANCEL_SUBJECT_PREFIX}.{job_id}"
