"""Process entry. Always binds 127.0.0.1: bearer tokens must never travel unencrypted, so exposing the service off-host is a
reviewed code change behind a co-located TLS proxy, not a configuration switch."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass

import uvicorn

from . import extraction_access, relation_access
from .app import create_app
from .config import HOST, ConfigError, ServiceConfig, load
from .dispatch import Dispatcher
from .jobs import JobService
from .ledger import ProcessLock, ServiceLedger
from .logs import emit
from .extraction_dispatch import ExtractionDispatcher
from .extraction_jobs import ExtractionJobs
from .extraction_ledger import ExtractionLedger
from .extraction_runtime import ExtractionProcess
from .graph_reads import GraphReads
from .graph_runtime import GraphProcess
from .handoff_reads import HandoffReads
from .handoff_runtime import HandoffProcess
from .relation_dispatch import RelationDispatcher
from .relation_jobs import RelationJobs
from .relation_ledger import RelationLedger
from .relation_runtime import RelationGate, RelationProcess
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
    relation: RelationJobs | None = None
    relation_dispatcher: RelationDispatcher | None = None
    relation_ledger: RelationLedger | None = None
    extraction: ExtractionJobs | None = None
    extraction_dispatcher: ExtractionDispatcher | None = None
    extraction_ledger: ExtractionLedger | None = None
    graph: GraphReads | None = None
    handoff: HandoffReads | None = None


def build_service(config: ServiceConfig, *, deadlines: Deadlines = Deadlines()) -> Service:
    """Startup order: process lock, ledger, worker-ledger binding, then recovery of rows the previous process left in flight.
    The relation family (only when its configuration group is enabled) follows the same order on its own ledger, but a row left in
    flight is ended as `service_restarted` and never run again automatically."""
    lock = ProcessLock(config.state_dir)
    ledger = ServiceLedger(config.state_dir, config.worker_state_dir)
    requeued = ledger.requeue_in_flight()
    worker = WorkerProcess(config, deadlines)
    dispatcher = Dispatcher(config, ledger, worker, emit)
    jobs = JobService(config, ledger, worker, dispatcher)
    relation = relation_dispatcher = relation_ledger = None
    extraction = extraction_dispatcher = extraction_ledger = None
    interrupted = extraction_interrupted = 0
    # ONE gate for both pipeline families: the S2 writer and the S3 reader of its ledger (and each family's own ledger lock, which does not
    # wait) must never have two children at once, so every S2 and S3 child of this process runs behind this single lock.
    gate = RelationGate()
    if config.relation is not None:
        relation_ledger = RelationLedger(config.state_dir, config.relation.state_dir)
        interrupted = relation_ledger.interrupt_in_flight()
        process = RelationProcess(config, deadlines)
        names = [principal.name for principal in config.principals]
        upstreams = config.relation.upstreams_path
        relation_dispatcher = RelationDispatcher(relation_ledger, process, gate, emit,
                                                 lambda owner, job_id, digest: relation_access.refusal(upstreams, names, owner, job_id, digest))
        relation = RelationJobs(config, relation_ledger, process, relation_dispatcher, gate)
    if config.extraction is not None:
        extraction_ledger = ExtractionLedger(config.state_dir, config.extraction.state_dir)
        extraction_interrupted = extraction_ledger.interrupt_in_flight()
        extraction_process = ExtractionProcess(config, deadlines)
        authority = extraction_access.Authority(config.extraction.approvals_path, [principal.name for principal in config.principals],
                                                config.extraction.producer_replay, config.extraction.topic_replay)
        extraction_dispatcher = ExtractionDispatcher(extraction_ledger, extraction_process, gate, emit,
                                                     lambda owner, pins, job_id: authority.refusal(owner, job_id, pins.approval))
        extraction = ExtractionJobs(config, extraction_ledger, extraction_process, extraction_dispatcher, gate, authority)
    # The graph door is read-only and has no ledger of its own. When an S2/S3 group of this process is configured it shares THEIR gate (they write the
    # ledgers the graph reads and a pipeline writer lock does not wait); without one the graph children run side by side behind a small slot limit.
    graph = GraphReads(config, GraphProcess(config, deadlines), gate if config.graph.shared_gate else None) if config.graph is not None else None
    # The handoff door is read-only too and has no ledger of its own; it shares the same S2/S3 gate under the same rule.
    handoff = HandoffReads(config, HandoffProcess(config, deadlines), gate if config.handoff.shared_gate else None) if config.handoff is not None else None
    starting: dict[str, object] = {"event": "service_starting", "principals": len(config.principals), "live": config.live_available,
                                   "replay": config.replay_path is not None, "requeuedInFlight": requeued}
    if config.relation is not None:  # a disabled feature leaves the S1 startup line exactly as it was
        starting["relationInterrupted"] = interrupted
    if config.extraction is not None:
        starting["extractionInterrupted"] = extraction_interrupted
    if config.graph is not None:
        starting["graph"] = True
    if config.handoff is not None:
        starting["handoff"] = True
    emit(starting)
    return Service(config, lock, ledger, worker, dispatcher, jobs, relation, relation_dispatcher, relation_ledger, extraction, extraction_dispatcher,
                   extraction_ledger, graph, handoff)


def serve(service: Service) -> None:
    app = create_app(service.jobs, service.relation, service.extraction, service.graph, service.handoff)
    service.dispatcher.start()
    if service.relation_dispatcher is not None:
        service.relation_dispatcher.start()
    if service.extraction_dispatcher is not None:
        service.extraction_dispatcher.start()
    server = uvicorn.Server(uvicorn.Config(
        app, host=HOST, port=service.config.port, log_config=None, log_level="warning", access_log=False,
        proxy_headers=False, server_header=False, limit_concurrency=64, timeout_keep_alive=5,
        timeout_graceful_shutdown=10, lifespan="off", ws="none"))
    try:
        server.run()
    finally:
        service.dispatcher.stop()
        if service.relation_dispatcher is not None:
            service.relation_dispatcher.stop()
        if service.extraction_dispatcher is not None:
            service.extraction_dispatcher.stop()


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
