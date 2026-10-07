"""Reads how many jobs are waiting or running on the job consumer."""

from nats.js import JetStreamContext

from mcpqueue.constants import JOB_CONSUMER_NAME, JOB_STREAM_NAME


class QueueDepthMonitor:
    def __init__(self, jetstream: JetStreamContext) -> None:
        self._jetstream = jetstream

    async def read_queue_depth(self) -> int:
        """Jobs not yet delivered plus jobs delivered but not yet acknowledged."""
        consumer_info = await self._jetstream.consumer_info(JOB_STREAM_NAME, JOB_CONSUMER_NAME)
        return (consumer_info.num_pending or 0) + (consumer_info.num_ack_pending or 0)
