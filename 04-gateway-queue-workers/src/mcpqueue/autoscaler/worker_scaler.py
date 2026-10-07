"""Starts and stops the worker containers Compose created (``deploy.replicas`` = the maximum)."""

import docker
from docker.models.containers import Container

from mcpqueue.config import AutoscalerSettings
from mcpqueue.constants import (
    COMPOSE_CONTAINER_NUMBER_LABEL,
    COMPOSE_PROJECT_LABEL,
    COMPOSE_SERVICE_LABEL,
    WORKER_SERVICE_NAME,
)


class DockerWorkerScaler:
    """Blocking Docker SDK calls; the autoscaler loop runs them in a thread."""

    def __init__(self, settings: AutoscalerSettings) -> None:
        self._settings = settings
        self._docker_client = docker.from_env()

    def list_worker_containers(self) -> list[Container]:
        labels = [
            f"{COMPOSE_PROJECT_LABEL}={self._settings.compose_project}",
            f"{COMPOSE_SERVICE_LABEL}={WORKER_SERVICE_NAME}",
        ]
        containers = self._docker_client.containers.list(all=True, filters={"label": labels})
        return sorted(
            containers, key=lambda container: int(container.labels[COMPOSE_CONTAINER_NUMBER_LABEL])
        )

    def count_running_workers(self) -> int:
        return sum(container.status == "running" for container in self.list_worker_containers())

    def scale_to(self, worker_count: int) -> None:
        """Start the lowest-numbered stopped workers, or stop the highest-numbered running ones."""
        containers = self.list_worker_containers()
        running = [container for container in containers if container.status == "running"]
        stopped = [container for container in containers if container.status != "running"]
        for container in stopped[: max(0, worker_count - len(running))]:
            container.start()
        for container in reversed(running[worker_count:]):
            container.stop(timeout=self._settings.worker_stop_timeout_seconds)
