"""Wires the state directory, admin stores and background workers for one app instance."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from .admin_auth import AdminAuth
from .admin_jobs import JobRunner, Launcher, popen_launcher
from .admin_ledger import Ledger, Neo4jProbe, Neo4jReader, PocLedger
from .admin_pipeline import PipelineService
from .admin_usage import UsageService
from .audit import AuditLog, Clock
from .briefing_graph import BriefingGraphs
from .briefing_market import IndicatorHistory, MarketIndicators
from .briefing_rounds import BriefingService
from .config import Settings
from .errors import SourceUnavailable
from .graph_versions import GraphStore
from .market_data import TtlCache
from .quote_yahoo import YahooProvider
from .review import ReviewStore
from .sources import DataProvider, PublishedSource
from .sentiment import SentimentService
from .statedb import StateDb

log = logging.getLogger("zoop_bff.admin")
SCHEDULER_INTERVAL_SECONDS = 15.0


@dataclass
class AdminServices:
    db: StateDb
    clock: Clock
    audit: AuditLog
    auth: AdminAuth
    reviews: ReviewStore
    graphs: GraphStore
    source: PublishedSource
    provider: DataProvider
    ledger: Ledger
    pipeline: PipelineService
    usage: UsageService
    jobs: JobRunner
    briefings: BriefingService
    briefing_graphs: BriefingGraphs
    sentiment: SentimentService


class BriefingScheduler:
    """In-process scheduler: a daemon thread that asks the briefing service what fell due."""

    def __init__(self, briefings: BriefingService, interval: float = SCHEDULER_INTERVAL_SECONDS):
        self._briefings = briefings
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="briefing-scheduler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def _loop(self) -> None:
        while True:
            try:
                made = self._briefings.tick()
                if made:
                    log.info("scheduler generated %s", made)
            except Exception:  # keep the loop alive; a failed pass is retried on the next tick
                log.exception("briefing scheduler pass failed")
            if self._stop.wait(self._interval):
                return


def build_admin_services(
    settings: Settings,
    *,
    clock: Clock | None = None,
    ledger: Ledger | None = None,
    neo4j: Neo4jProbe | None = None,
    sandbox: Any | None = None,
    launcher: Launcher = popen_launcher,
    market: IndicatorHistory | None = None,
) -> AdminServices:
    """Injection points (ledger, Neo4j, sandbox, launcher, market source) exist so tests can replace external systems.

    The briefing's market indicators come from the keyless Yahoo chart endpoint (the quote provider modes ``auto`` and
    ``yahoo``); with the provider off or set to Toss only, rounds store the indicators as not connected."""
    clock = clock or Clock()
    db = StateDb(settings.state_dir)
    audit = AuditLog(db, clock)
    reviews = ReviewStore(db, clock)
    graphs = GraphStore(db, clock, audit, reviews, settings.snapshot_path)
    source = PublishedSource(graphs, reviews)
    provider = DataProvider(settings, source)
    ledger = ledger or PocLedger(settings.admin_poc_dsn, settings.ledger_connect_timeout_seconds)
    neo4j = neo4j or Neo4jReader(settings.admin_neo4j_uri, settings.admin_neo4j_user, settings.admin_neo4j_password)
    pipeline = PipelineService(ledger=ledger, neo4j=neo4j, reviews=reviews, graphs=graphs, audit=audit, clock=clock)
    usage = UsageService(db, clock, ledger)
    sentiment = SentimentService(db, clock, usage)
    jobs = JobRunner(
        settings=settings, db=db, clock=clock, audit=audit, pipeline=pipeline, sandbox=sandbox, launcher=launcher
    )
    if market is None and settings.quote_provider in ("auto", "yahoo"):
        market = YahooProvider(base_url=settings.yahoo_base_url, timeout=settings.quote_timeout_seconds, cache=TtlCache())
    briefings = BriefingService(
        db=db, clock=clock, audit=audit, usage=usage, provider=provider, indicators=MarketIndicators(market), sentiment=sentiment
    )
    jobs.recover()  # settle what the previous process left running (requirement 59)
    briefings.recover()
    try:
        graphs.ensure_seed()  # first start: ZOOP_SNAPSHOT_PATH becomes v1 (a missing file is retried per request)
    except SourceUnavailable as exc:
        log.warning("seed snapshot not registered yet: %s", exc.message)
    return AdminServices(
        db=db,
        clock=clock,
        audit=audit,
        auth=AdminAuth(db, clock, audit, settings.admin_idle_seconds, settings.admin_absolute_seconds),
        reviews=reviews,
        graphs=graphs,
        source=source,
        provider=provider,
        ledger=ledger,
        pipeline=pipeline,
        usage=usage,
        jobs=jobs,
        briefings=briefings,
        briefing_graphs=BriefingGraphs(briefings, provider, reviews),
        sentiment=sentiment,
    )
