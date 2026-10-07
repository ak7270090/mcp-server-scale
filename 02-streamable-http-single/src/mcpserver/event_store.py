"""In-memory event store so clients can resume a dropped SSE stream with ``Last-Event-ID``."""

from collections import OrderedDict, deque
from dataclasses import dataclass
from uuid import uuid4

from mcp.server.streamable_http import (
    EventCallback,
    EventId,
    EventMessage,
    EventStore,
    StreamId,
)
from mcp.types import JSONRPCMessage


@dataclass(frozen=True)
class StoredEvent:
    event_id: EventId
    message: JSONRPCMessage | None


class InMemoryEventStore(EventStore):
    """Keeps the most recent events of the most recent streams, in this process only."""

    def __init__(self, max_events_per_stream: int, max_streams: int) -> None:
        self._max_events_per_stream = max_events_per_stream
        self._max_streams = max_streams
        self._streams: OrderedDict[StreamId, deque[StoredEvent]] = OrderedDict()
        self._stream_by_event_id: dict[EventId, StreamId] = {}

    async def store_event(self, stream_id: StreamId, message: JSONRPCMessage | None) -> EventId:
        stream_events = self._get_or_create_stream(stream_id)
        if len(stream_events) == self._max_events_per_stream:
            dropped_event = stream_events.popleft()
            del self._stream_by_event_id[dropped_event.event_id]
        event_id = uuid4().hex
        stream_events.append(StoredEvent(event_id=event_id, message=message))
        self._stream_by_event_id[event_id] = stream_id
        return event_id

    async def replay_events_after(
        self, last_event_id: EventId, send_callback: EventCallback
    ) -> StreamId | None:
        stream_id = self._stream_by_event_id.get(last_event_id)
        if stream_id is None:
            return None
        has_passed_last_event = False
        for stored_event in self._streams[stream_id]:
            if has_passed_last_event and stored_event.message is not None:
                await send_callback(EventMessage(stored_event.message, stored_event.event_id))
            if stored_event.event_id == last_event_id:
                has_passed_last_event = True
        return stream_id

    def _get_or_create_stream(self, stream_id: StreamId) -> deque[StoredEvent]:
        if stream_id in self._streams:
            self._streams.move_to_end(stream_id)
            return self._streams[stream_id]
        if len(self._streams) == self._max_streams:
            _, evicted_events = self._streams.popitem(last=False)
            for evicted_event in evicted_events:
                del self._stream_by_event_id[evicted_event.event_id]
        self._streams[stream_id] = deque()
        return self._streams[stream_id]
