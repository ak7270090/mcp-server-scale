"""Polls the queue depth and applies the scaling policy to the worker containers."""

import logging
import time
from typing import Protocol

import anyio

from mcpqueue.autoscaler.scaling_policy import ScalingPolicy
from mcpqueue.config import AutoscalerSettings

logger = logging.getLogger(__name__)


class QueueDepthReader(Protocol):
    async def read_queue_depth(self) -> int: ...


class WorkerScaler(Protocol):
    def count_running_workers(self) -> int: ...

    def scale_to(self, worker_count: int) -> None: ...


class AutoscalerLoop:
    def __init__(
        self,
        settings: AutoscalerSettings,
        depth_reader: QueueDepthReader,
        worker_scaler: WorkerScaler,
        policy: ScalingPolicy,
    ) -> None:
        self._settings = settings
        self._depth_reader = depth_reader
        self._worker_scaler = worker_scaler
        self._policy = policy

    async def run_once(self, now: float) -> int:
        """One poll: returns the worker count after any change."""
        queue_depth = await self._depth_reader.read_queue_depth()
        running_workers = await anyio.to_thread.run_sync(self._worker_scaler.count_running_workers)
        decided_workers = self._policy.decide(queue_depth, running_workers, now)
        if decided_workers != running_workers:
            logger.info(
                "queue_depth=%d running=%d scaling_to=%d",
                queue_depth,
                running_workers,
                decided_workers,
            )
            await anyio.to_thread.run_sync(self._worker_scaler.scale_to, decided_workers)
        return decided_workers

    async def run_forever(self) -> None:
        while True:
            await self.run_once(time.monotonic())
            await anyio.sleep(self._settings.poll_interval_seconds)
