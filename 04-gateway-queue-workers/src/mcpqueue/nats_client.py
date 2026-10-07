"""NATS connection and the JetStream streams, consumer and key-value bucket the services share."""

import logging

import nats
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext
from nats.js.api import (
    AckPolicy,
    ConsumerConfig,
    DiscardPolicy,
    KeyValueConfig,
    RetentionPolicy,
    StreamConfig,
)
from nats.js.errors import BadRequestError
from nats.js.kv import KeyValue

from mcpqueue.config import QueueSettings
from mcpqueue.constants import (
    DEAD_LETTER_STREAM_NAME,
    DEAD_LETTER_SUBJECT,
    JOB_CONSUMER_NAME,
    JOB_STREAM_NAME,
    JOB_SUBJECT,
    SESSION_COUNTER_BUCKET,
)

logger = logging.getLogger(__name__)


async def create_nats_connection(settings: QueueSettings) -> NatsClient:
    return await nats.connect(settings.nats_url, max_reconnect_attempts=-1)


def build_job_consumer_config(settings: QueueSettings) -> ConsumerConfig:
    """One extra delivery so a worker can move a job that kept crashing workers to dead letters."""
    return ConsumerConfig(
        durable_name=JOB_CONSUMER_NAME,
        ack_policy=AckPolicy.EXPLICIT,
        ack_wait=settings.job_ack_wait_seconds,
        max_deliver=settings.job_max_deliveries + 1,
        filter_subject=JOB_SUBJECT,
    )


async def ensure_job_streams(jetstream: JetStreamContext, settings: QueueSettings) -> None:
    """Create or update the job queue, its consumer and the dead-letter stream (idempotent)."""
    job_stream = StreamConfig(
        name=JOB_STREAM_NAME,
        subjects=[JOB_SUBJECT],
        retention=RetentionPolicy.WORK_QUEUE,
        max_msgs=settings.queue_max_pending,
        discard=DiscardPolicy.NEW,
    )
    dead_letter_stream = StreamConfig(name=DEAD_LETTER_STREAM_NAME, subjects=[DEAD_LETTER_SUBJECT])
    for stream_config in (job_stream, dead_letter_stream):
        try:
            await jetstream.add_stream(stream_config)
        except BadRequestError:
            await jetstream.update_stream(stream_config)
    try:
        await jetstream.add_consumer(JOB_STREAM_NAME, build_job_consumer_config(settings))
    except BadRequestError as error:
        logger.warning("job consumer exists with a different config: %s", error.description)


async def open_session_counter_bucket(
    jetstream: JetStreamContext, settings: QueueSettings
) -> KeyValue:
    return await jetstream.create_key_value(
        KeyValueConfig(bucket=SESSION_COUNTER_BUCKET, ttl=settings.session_counter_ttl_seconds)
    )
