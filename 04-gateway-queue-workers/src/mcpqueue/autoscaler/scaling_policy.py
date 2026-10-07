"""Decides how many workers should run for a given queue depth."""

import math

from mcpqueue.config import AutoscalerSettings


class ScalingPolicy:
    """Scale up at once; scale down only after ``scale_down_cooldown_seconds`` without a change."""

    def __init__(self, settings: AutoscalerSettings) -> None:
        self._settings = settings
        self._last_change_at: float | None = None

    def wanted_worker_count(self, queue_depth: int) -> int:
        wanted = math.ceil(queue_depth / self._settings.target_jobs_per_worker)
        return max(self._settings.min_workers, min(self._settings.max_workers, wanted))

    def decide(self, queue_depth: int, running_workers: int, now: float) -> int:
        wanted = self.wanted_worker_count(queue_depth)
        if wanted > running_workers:
            self._last_change_at = now
            return wanted
        is_cooled_down = (
            self._last_change_at is None
            or now - self._last_change_at >= self._settings.scale_down_cooldown_seconds
        )
        if wanted < running_workers and is_cooled_down:
            self._last_change_at = now
            return wanted
        return running_workers
