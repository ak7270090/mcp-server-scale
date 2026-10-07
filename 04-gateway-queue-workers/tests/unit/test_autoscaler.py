import pytest

from mcpqueue.autoscaler.scaling_loop import AutoscalerLoop
from mcpqueue.autoscaler.scaling_policy import ScalingPolicy
from mcpqueue.config import AutoscalerSettings

SETTINGS = AutoscalerSettings(
    min_workers=1, max_workers=10, target_jobs_per_worker=2, scale_down_cooldown_seconds=20
)


class FixedDepthReader:
    def __init__(self, queue_depth: int) -> None:
        self.queue_depth = queue_depth

    async def read_queue_depth(self) -> int:
        return self.queue_depth


class RecordingScaler:
    def __init__(self, running_workers: int) -> None:
        self.running_workers = running_workers
        self.scale_requests: list[int] = []

    def count_running_workers(self) -> int:
        return self.running_workers

    def scale_to(self, worker_count: int) -> None:
        self.scale_requests.append(worker_count)
        self.running_workers = worker_count


@pytest.mark.parametrize(
    ("queue_depth", "expected_workers"), [(0, 1), (1, 1), (5, 3), (20, 10), (500, 10)]
)
def test_wanted_workers_follow_depth_within_limits(queue_depth: int, expected_workers: int) -> None:
    assert ScalingPolicy(SETTINGS).wanted_worker_count(queue_depth) == expected_workers


def test_scales_up_immediately_and_down_only_after_cooldown() -> None:
    policy = ScalingPolicy(SETTINGS)

    after_burst = policy.decide(queue_depth=12, running_workers=1, now=0)
    during_cooldown = policy.decide(queue_depth=0, running_workers=after_burst, now=10)
    after_cooldown = policy.decide(queue_depth=0, running_workers=after_burst, now=25)

    assert (after_burst, during_cooldown, after_cooldown) == (6, 6, 1)


def test_restores_minimum_when_workers_disappear() -> None:
    assert ScalingPolicy(SETTINGS).decide(queue_depth=0, running_workers=0, now=0) == 1


@pytest.mark.anyio
async def test_loop_scales_only_when_the_decision_changes() -> None:
    depth_reader = FixedDepthReader(queue_depth=8)
    scaler = RecordingScaler(running_workers=1)
    autoscaler_loop = AutoscalerLoop(SETTINGS, depth_reader, scaler, ScalingPolicy(SETTINGS))

    first_poll = await autoscaler_loop.run_once(now=0)
    second_poll = await autoscaler_loop.run_once(now=1)

    assert (first_poll, second_poll) == (4, 4)
    assert scaler.scale_requests == [4]
