"""Entry point: ``python -m mcpqueue.worker`` runs one queue worker until SIGTERM."""

import asyncio
import logging
import signal

from mcpqueue.config import WorkerSettings
from mcpqueue.worker.job_consumer import JobConsumer


async def run_worker() -> None:
    settings = WorkerSettings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(name)s %(message)s")
    consumer = JobConsumer(settings)
    event_loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        event_loop.add_signal_handler(stop_signal, consumer.request_stop)
    await consumer.run()


if __name__ == "__main__":
    asyncio.run(run_worker())
