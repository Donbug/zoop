#!/usr/bin/env python3
"""Rebuild the demo briefing rounds in a NEW state directory, through the normal generation path.

    uv run python scripts/rebuild_demo_briefings.py --source var --target /tmp/zoop-state-briefing --from 2026-09-16

A published round is immutable (a SQLite trigger refuses to change or delete it), so rounds that were published
before the market indicators existed cannot be topped up. This script instead builds a new state directory:

1. It copies everything except what is bound to the old rounds from ``--source`` (members, sessions, admin accounts,
   review decisions, graph versions and files, audit log, jobs, chat, ...). Left out: the ``briefing_*`` tables, the
   briefing epoch, votes on briefing rounds and issues, and briefing view/open events (they name round ids that are
   about to mean something else). ``--source`` is only read (SQLite backup API), so a running BFF is not disturbed.
2. It replays the calendar from ``--from`` to the latest started round: for each slot the clock is set to the
   scheduled time plus 90 seconds and ``BriefingService.generate`` (the admin reprocess path) runs. Selection,
   verification, the market indicators (read as of each round's reference point) and publication are the real ones;
   only the clock is moved. Attempts are recorded as ``admin`` / ``demo-replay@zoop.local`` so they are never
   mistaken for what the scheduler did at the time.

``--target`` must not exist or be empty. Nothing in ``--source`` is modified; swapping directories is the operator's
step (see prototype/README.md). Market data needs the network (Yahoo chart; ``ZOOP_QUOTE_PROVIDER=off`` stores every
indicator as not connected). The settings come from the same ``ZOOP_*`` variables the BFF reads
(``ZOOP_SNAPSHOT_PATH``, ``ZOOP_COMPANY_CATALOG``, ...).
"""

from __future__ import annotations

import argparse
import dataclasses
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from zoop_bff.admin_services import build_admin_services
from zoop_bff.audit import Actor, Clock
from zoop_bff.briefing_rounds import Edition, latest_started, round_id, scheduled_at
from zoop_bff.config import Settings
from zoop_bff.errors import ApiError
from zoop_bff.statedb import StateDb

REPLAY = Actor("admin", "demo-replay", "demo-replay@zoop.local")
SKIP_TABLES = {"briefing_rounds", "briefing_attempts", "briefing_corrections"}
# table -> condition on the source rows that are kept (the rest name the old rounds)
KEEP_WHERE = {
    "meta": "key != 'briefing_epoch'",
    "feedback": "feature NOT IN ('briefing_round', 'briefing_issue')",
    "telemetry_events": "round_id IS NULL AND type NOT IN ('briefing_view', 'briefing_issue_open')",
}
AFTER_SCHEDULED = timedelta(seconds=90)


def copy_state(source: Path, target: Path) -> dict[str, tuple[int, int]]:
    """Build ``target`` from ``source``; returns {table: (rows in source, rows copied)}."""
    source_db = source / "zoop-admin.sqlite3"
    if not source_db.is_file():
        raise SystemExit(f"no state database at {source_db}")
    target.mkdir(parents=True, exist_ok=True)
    if (source / "graph").is_dir():
        shutil.copytree(source / "graph", target / "graph")
    StateDb(target).close()  # creates the current schema (tables, indexes, immutability triggers)
    counts: dict[str, tuple[int, int]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "source.sqlite3"
        reader = sqlite3.connect(f"file:{source_db}?mode=ro", uri=True)
        copy = sqlite3.connect(snapshot)
        reader.backup(copy)  # a consistent copy even while the BFF holds the WAL open
        reader.close()
        copy.close()
        conn = sqlite3.connect(target / "zoop-admin.sqlite3")
        conn.execute("ATTACH DATABASE ? AS src", (str(snapshot),))
        tables = [r[0] for r in conn.execute("SELECT name FROM src.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            have = {r[1] for r in conn.execute(f"PRAGMA main.table_info({table})")}
            columns = [r[1] for r in conn.execute(f"PRAGMA src.table_info({table})") if r[1] in have]
            total = conn.execute(f"SELECT COUNT(*) FROM src.{table}").fetchone()[0]
            if table in SKIP_TABLES or not columns:
                counts[table] = (total, 0)
                continue
            names = ", ".join(columns)
            where = f" WHERE {KEEP_WHERE[table]}" if table in KEEP_WHERE else ""
            conn.execute(f"INSERT INTO main.{table} ({names}) SELECT {names} FROM src.{table}{where}")
            counts[table] = (total, conn.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0])
        conn.commit()
        conn.execute("DETACH DATABASE src")
        conn.close()
    return counts


def slots(first: date, last: tuple[date, Edition]) -> list[tuple[date, Edition]]:
    """Every calendar slot from ``first``'s morning round up to and including ``last``."""
    order = {"morning": 0, "evening": 1}
    out: list[tuple[date, Edition]] = []
    day, edition = first, "morning"
    while (day, order[edition]) <= (last[0], order[last[1]]):
        out.append((day, edition))  # type: ignore[arg-type]
        day, edition = (day, "evening") if edition == "morning" else (day + timedelta(days=1), "morning")  # type: ignore[assignment]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, required=True, help="state directory to copy from (read only)")
    parser.add_argument("--target", type=Path, required=True, help="new state directory (must not exist or be empty)")
    parser.add_argument("--from", dest="first", type=date.fromisoformat, required=True, help="first round's date (KST); its morning round is the first")
    parser.add_argument("--pause", type=float, default=0.4, help="seconds between rounds, to stay polite with the market source")
    args = parser.parse_args()

    source, target = args.source.resolve(), args.target.resolve()
    if source == target:
        raise SystemExit("--target must differ from --source")
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"{target} is not empty; choose a new directory")

    counts = copy_state(source, target)
    print("copied (source rows -> kept):")
    for table, (total, kept) in sorted(counts.items()):
        if total:
            print(f"  {table:<22}{total:>8} -> {kept}")

    settings = dataclasses.replace(Settings.from_env(), state_dir=target, briefing_scheduler=False)
    clock = Clock()
    services = build_admin_services(settings, clock=clock)
    try:
        last = latest_started(datetime.now(UTC))
        plan = slots(args.first, last)
        print(f"\nreplaying {len(plan)} rounds from {round_id(*plan[0])} to {round_id(*plan[-1])}, quote provider: {settings.quote_provider}")
        for day, edition in plan:
            clock.travel_to(scheduled_at(day, edition) + AFTER_SCHEDULED)
            rid = round_id(day, edition)
            try:
                services.briefings.generate(day, edition, trigger="admin", actor=REPLAY, blocking=True)
            except ApiError as exc:
                print(f"  {rid}: skipped ({exc.code}: {exc.message})")
                continue
            detail = services.briefings.detail(rid)
            published = detail.published
            market = published.market_variables if published else None
            states = " ".join(f"{i.id}={i.status}" for i in market.indicators) if market else "-"
            print(f"  {rid}: {detail.status:<9} items={detail.item_count if detail.item_count is not None else '-'} {states}")
            time.sleep(args.pause)
    finally:
        services.db.close()

    print(f"\nnew state directory: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
