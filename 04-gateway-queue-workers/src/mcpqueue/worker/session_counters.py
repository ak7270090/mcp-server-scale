"""Per-session counters in a NATS key-value bucket, so any worker can increment any session's."""

from typing import Protocol

from nats.js.errors import KeyDeletedError, KeyNotFoundError, KeyWrongLastSequenceError
from nats.js.kv import KeyValue
from pydantic import BaseModel


class CounterRecord(BaseModel):
    value: int
    last_job_id: str


class CounterBucket(Protocol):
    async def get(self, key: str) -> KeyValue.Entry: ...

    async def create(self, key: str, value: bytes) -> int: ...

    async def update(self, key: str, value: bytes, last: int | None = None) -> int: ...


class SessionCounterStore:
    """Compare-and-set increments; a redelivered job ID returns the stored value unchanged."""

    def __init__(self, bucket: CounterBucket) -> None:
        self._bucket = bucket

    async def increment(self, session_key: str, job_id: str) -> int:
        while True:
            try:
                entry = await self._bucket.get(session_key)
            except (KeyNotFoundError, KeyDeletedError):
                entry = None
            if entry is None:
                first_record = CounterRecord(value=1, last_job_id=job_id)
                try:
                    await self._bucket.create(session_key, first_record.model_dump_json().encode())
                except KeyWrongLastSequenceError:
                    continue
                return first_record.value
            stored_record = CounterRecord.model_validate_json(entry.value)
            if stored_record.last_job_id == job_id:
                return stored_record.value
            next_record = CounterRecord(value=stored_record.value + 1, last_job_id=job_id)
            try:
                await self._bucket.update(
                    session_key, next_record.model_dump_json().encode(), last=entry.revision
                )
            except KeyWrongLastSequenceError:
                continue
            return next_record.value
