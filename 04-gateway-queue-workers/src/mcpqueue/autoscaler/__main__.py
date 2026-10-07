"""Entry point: ``python -m mcpqueue.autoscaler`` (needs the Docker socket)."""

import asyncio
import logging

from mcpqueue.autoscaler.queue_depth_monitor import QueueDepthMonitor
from mcpqueue.autoscaler.scaling_loop import AutoscalerLoop
from mcpqueue.autoscaler.scaling_policy import ScalingPolicy
from mcpqueue.autoscaler.worker_scaler import DockerWorkerScaler
from mcpqueue.config import AutoscalerSettings
from mcpqueue.nats_client import create_nats_connection, ensure_job_streams


async def run_autoscaler() -> None:
    settings = AutoscalerSettings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(name)s %(message)s")
    connection = await create_nats_connection(settings)
    jetstream = connection.jetstream()
    await ensure_job_streams(jetstream, settings)
    autoscaler_loop = AutoscalerLoop(
        settings,
        QueueDepthMonitor(jetstream),
        DockerWorkerScaler(settings),
        ScalingPolicy(settings),
    )
    await autoscaler_loop.run_forever()


if __name__ == "__main__":
    asyncio.run(run_autoscaler())
