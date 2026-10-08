#!/usr/bin/env python3
"""Explicit existing briefing-outlook production through the durable worker; GET remains read-only."""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
from datetime import datetime
from pathlib import Path

from zoop_bff.admin_services import build_admin_services
from zoop_bff.ai_worker import AiWorkerClient
from zoop_bff.audit import Actor
from zoop_bff.briefing_rounds import latest_started, parse_round_id, round_id
from zoop_bff.config import Settings
from zoop_bff.errors import ApiError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--replay", type=Path)
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--worker-state", type=Path, required=True)
    parser.add_argument("--grants", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--grant-id", required=True)
    parser.add_argument("--grant-revision", required=True)
    parser.add_argument("--round", action="append", dest="rounds")
    parser.add_argument("--synthetic-now", help="Reproducible synthetic replay only; real/live clock is never overridden")
    args = parser.parse_args()
    services = None
    try:
        settings = dataclasses.replace(Settings.from_env(), state_dir=args.state_dir,
            quote_provider="off", metrics_enabled=False, briefing_scheduler=False)
        services = build_admin_services(settings)
        synthetic = services.provider.get().synthetic
        if args.replay and not synthetic:
            parser.error("authored replay requires synthetic source/state")
        if args.synthetic_now:
            at = datetime.fromisoformat(args.synthetic_now)
            if args.live or not synthetic or at.tzinfo is None:
                parser.error("--synthetic-now requires synthetic replay and timezone")
            services.clock.travel_to(at)
        mode = "live" if args.live else "replay"
        # Only this explicit operator command forwards approved model settings. No dotenv file is opened.
        names = ("ZOOP_AI_BRIEFING_OUTLOOK_MODEL", "ZOOP_AI_BRIEFING_OUTLOOK_REASONING_EFFORT", "ZOOP_AI_PROVIDER",
                 "ZOOP_AI_BASE_URL", "ZOOP_AI_API_KEY", "ZOOP_AI_LIVE_ENABLED", "ZOOP_AI_GLOBAL_MAX_CALLS")
        worker_env = {n: os.environ[n] for n in names if n in os.environ} if args.live else {
            n: os.environ[n] for n in names[:2] if n in os.environ}
        worker = AiWorkerClient(state_dir=args.state_dir, worker_state=args.worker_state,
                                grants=args.grants, replay=args.replay, env=worker_env)
        services.sentiment.configure_outlook(worker, {"mode": mode, "sourceKind": "synthetic" if synthetic else "actual",
            "sourceId": args.source_id, "grantId": args.grant_id, "grantRevision": args.grant_revision})
        rounds = list(dict.fromkeys(args.rounds or [round_id(*latest_started(services.clock.now()))]))
        outcomes = []
        for rid in rounds:
            preview = services.briefings.sentiment_preview(rid)
            if not preview["eligible"]:
                record = services.briefings.record(rid)
                outcomes.append({"roundId": rid, "status": "unchanged", "reason": preview["reason"],
                                 "outlook": record.payload.get("outlook") if record and record.payload else None})
                continue
            parsed = parse_round_id(rid)
            assert parsed is not None
            services.briefings.generate(*parsed, trigger="admin",
                actor=Actor("admin", "outlook-cli", "outlook-cli@zoop.local"), blocking=True)
            record = services.briefings.record(rid)
            if not record or not record.payload:
                raise ValueError("outlook round did not publish")
            outcomes.append({"roundId": rid, "status": "published", "issueCount": len(record.payload["items"]),
                             "outlook": record.payload["outlook"]})
        print(json.dumps({"schemaVersion": "zoop-ai-s1-1", "mode": mode, "rounds": outcomes,
                          "workerJobs": list(services.sentiment.outlook_runs.values())}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, ApiError):
        print(json.dumps({"error": {"code": "outlook_generation_failed"}}))
        return 2
    finally:
        if services:
            services.db.close()


if __name__ == "__main__":
    raise SystemExit(main())
