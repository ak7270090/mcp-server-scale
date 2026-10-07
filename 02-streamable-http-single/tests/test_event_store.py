import pytest
from mcp.server.streamable_http import EventMessage
from mcp.types import JSONRPCMessage, JSONRPCNotification

from mcpserver.event_store import InMemoryEventStore

pytestmark = pytest.mark.anyio


class ReplayRecorder:
    """Collects the events an event store replays."""

    def __init__(self) -> None:
        self.replayed_event_ids: list[str] = []

    async def record(self, event_message: EventMessage) -> None:
        self.replayed_event_ids.append(event_message.event_id)


def build_message(sequence_number: int) -> JSONRPCMessage:
    return JSONRPCMessage(
        JSONRPCNotification(
            jsonrpc="2.0", method="notifications/progress", params={"n": sequence_number}
        )
    )


async def test_replays_only_events_after_the_given_event() -> None:
    event_store = InMemoryEventStore(max_events_per_stream=10, max_streams=10)
    event_ids = [await event_store.store_event("stream-a", build_message(n)) for n in range(4)]
    recorder = ReplayRecorder()

    replayed_stream_id = await event_store.replay_events_after(event_ids[1], recorder.record)

    assert replayed_stream_id == "stream-a"
    assert recorder.replayed_event_ids == event_ids[2:]


async def test_skips_priming_events_without_a_message() -> None:
    event_store = InMemoryEventStore(max_events_per_stream=10, max_streams=10)
    priming_event_id = await event_store.store_event("stream-a", None)
    message_event_id = await event_store.store_event("stream-a", build_message(1))
    await event_store.store_event("stream-a", None)
    recorder = ReplayRecorder()

    await event_store.replay_events_after(priming_event_id, recorder.record)

    assert recorder.replayed_event_ids == [message_event_id]


async def test_unknown_event_id_replays_nothing() -> None:
    event_store = InMemoryEventStore(max_events_per_stream=10, max_streams=10)
    recorder = ReplayRecorder()

    assert await event_store.replay_events_after("unknown", recorder.record) is None
    assert recorder.replayed_event_ids == []


async def test_drops_oldest_event_when_stream_is_full() -> None:
    event_store = InMemoryEventStore(max_events_per_stream=2, max_streams=10)
    oldest_event_id = await event_store.store_event("stream-a", build_message(1))
    await event_store.store_event("stream-a", build_message(2))
    await event_store.store_event("stream-a", build_message(3))
    recorder = ReplayRecorder()

    assert await event_store.replay_events_after(oldest_event_id, recorder.record) is None


async def test_evicts_least_recently_used_stream_when_full() -> None:
    event_store = InMemoryEventStore(max_events_per_stream=10, max_streams=2)
    evicted_event_id = await event_store.store_event("stream-a", build_message(1))
    kept_event_id = await event_store.store_event("stream-b", build_message(1))
    await event_store.store_event("stream-c", build_message(1))
    recorder = ReplayRecorder()

    assert await event_store.replay_events_after(evicted_event_id, recorder.record) is None
    assert await event_store.replay_events_after(kept_event_id, recorder.record) == "stream-b"
