"""Structured tool inputs and outputs."""

from pydantic import BaseModel, Field


class ReplicaIdentity(BaseModel):
    """Which server process answered a tool call."""

    replica_id: str = Field(description="Replica name (container hostname unless configured)")
    process_id: int = Field(description="Operating-system process ID of the worker")


class ConfirmationAnswer(BaseModel):
    """Form the user fills in when the server asks for confirmation."""

    confirmed: bool = Field(description="True to confirm, false to decline")
