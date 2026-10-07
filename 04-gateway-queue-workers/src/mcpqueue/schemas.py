"""Structured tool inputs and outputs, identical to the earlier phases."""

from pydantic import BaseModel, Field


class ReplicaIdentity(BaseModel):
    """Which worker process ran a tool call."""

    replica_id: str = Field(description="Worker name (container hostname unless configured)")
    process_id: int = Field(description="Operating-system process ID of the worker")


class ConfirmationAnswer(BaseModel):
    """Form the user fills in when a worker asks for confirmation."""

    confirmed: bool = Field(description="True to confirm, false to decline")
