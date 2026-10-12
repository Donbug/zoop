"""Process entry. Always binds 127.0.0.1: bearer tokens must never travel unencrypted, so exposing the service off-host is a
reviewed code change behind a co-located TLS proxy, not a configuration switch."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

import uvicorn

from .app import create_app
from .config import HOST, ConfigError, ServiceConfig, load
from .dispatch import Dispatcher
from .jobs import JobService
from .ledger import ProcessLock, ServiceLedger
from .logs import emit
from .runtime import Deadlines, WorkerProcess

CONFIG_EXIT = 78


@dataclass
class Service:
    config: ServiceConfig
    lock: ProcessLock
    ledger: ServiceLedger
    worker: WorkerProcess
    dispatcher: Dispatcher
    jobs: JobService


def build_service(config: ServiceConfig, *, deadlines: Deadlines = Deadlines()) -> Service:
    """Startup order: process lock, ledger, worker-ledger binding, then recovery of rows the previous process left in flight."""
    lock = ProcessLock(config.state_dir)
    ledger = ServiceLedger(config.state_dir, config.worker_state_dir)
    requeued = ledger.requeue_in_flight()
    worker = WorkerProcess(config, deadlines)
    dispatcher = Dispatcher(config, ledger, worker, emit)
    emit({"event": "service_starting", "principals": len(config.principals), "live": config.live_available,
          "replay": config.replay_path is not None, "requeuedInFlight": requeued})
    return Service(config, lock, ledger, worker, dispatcher, JobService(config, ledger, worker, dispatcher))


def serve(service: Service) -> None:
    app = create_app(service.jobs)
    service.dispatcher.start()
    server = uvicorn.Server(uvicorn.Config(
        app, host=HOST, port=service.config.port, log_config=None, log_level="warning", access_log=False,
        proxy_headers=False, server_header=False, limit_concurrency=64, timeout_keep_alive=5,
        timeout_graceful_shutdown=10, lifespan="off", ws="none"))
    try:
        server.run()
    finally:
        service.dispatcher.stop()


def refuse(error: ConfigError) -> int:
    # Field name and a stable reason code only: never a configured value.
    print(json.dumps({"error": "service_config_invalid", "field": error.field, "reason": error.reason}, separators=(",", ":")))
    return CONFIG_EXIT


def main() -> int:
    try:
        service = build_service(load(os.environ))
    except ConfigError as error:
        return refuse(error)
    serve(service)
    return 0


if __name__ == "__main__":
    sys.exit(main())
