#!/usr/bin/env python3
"""Count targets without calls, or explicitly judge and publish unissued rounds with a hard call ceiling."""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

from zoop_bff.admin_services import build_admin_services
from zoop_bff.audit import Actor
from zoop_bff.briefing_rounds import latest_started, parse_round_id, round_id
from zoop_bff.config import Settings
from zoop_bff.sentiment import (
    CallLimitReached, ModelReply, OpenAICompatibleProvider, ProviderFailure, ReplayProvider,
    document_input, document_pairs,
)


def snapshot_state(source: Path, target: Path) -> None:
    """Consistent read-only SQLite backup; dry-run bookkeeping touches only a temporary copy."""
    if not (source / "zoop-admin.sqlite3").is_file():
        raise ValueError("state database not found")
    with sqlite3.connect(f"file:{source / 'zoop-admin.sqlite3'}?mode=ro", uri=True) as reader:
        with sqlite3.connect(target / "zoop-admin.sqlite3") as writer:
            reader.backup(writer)
    if (source / "graph").is_dir():
        shutil.copytree(source / "graph", target / "graph")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--dry-run", action="store_true")
    modes.add_argument("--live", action="store_true")
    modes.add_argument("--replay", type=Path, help="JSON array of exact responses (test inputs only)")
    parser.add_argument("--max-calls", type=int, help="hard ceiling across documents, rounds and retries")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--model", default=os.environ.get("ZOOP_SENTIMENT_MODEL"))
    parser.add_argument("--round", action="append", dest="rounds", help="unpublished round id; default: latest due slot")
    args = parser.parse_args()
    if not args.dry_run and (args.max_calls is None or args.max_calls <= 0):
        parser.error("--live/--replay requires --max-calls > 0")
    if args.live and not args.model:
        parser.error("--live requires --model or ZOOP_SENTIMENT_MODEL")
    settings = dataclasses.replace(Settings.from_env(), briefing_scheduler=False)
    if not args.live:
        settings = dataclasses.replace(settings, quote_provider="off")
    if args.state_dir:
        settings = dataclasses.replace(settings, state_dir=args.state_dir)
    provider = None
    temporary = tempfile.TemporaryDirectory(prefix="zoop-sentiment-dry-") if args.dry_run else None
    services = None
    try:
        if temporary:
            target = Path(temporary.name)
            snapshot_state(settings.state_dir, target)
            settings = dataclasses.replace(settings, state_dir=target)
        services = build_admin_services(settings)
        ds = services.provider.get()
        pairs = document_pairs(ds)
        sendable = [(aid, cid) for aid, cid in pairs if ds.article_for(aid).poc.allow_model_send]
        model = args.model
        uncached = sum(1 for aid, cid in sendable if not model or not services.sentiment.cached(
            "document-sentiment", document_input(ds, aid, cid), model))
        rounds = list(dict.fromkeys(args.rounds or [round_id(*latest_started(services.clock.now()))]))
        previews = [services.briefings.sentiment_preview(rid) for rid in rounds]
        eligible = [p for p in previews if p["eligible"]]
        round_calls = sum(bool(p["items"]) for p in eligible)
        report = {
            "mode": "dry-run" if args.dry_run else "live" if args.live else "replay",
            "documentPairs": len(pairs), "sendableDocumentPairs": len(sendable),
            "permissionBlockedPairs": len(pairs) - len(sendable), "uncachedDocumentCalls": uncached,
            "rounds": len(rounds), "eligibleRounds": len(eligible), "nonemptyRoundCalls": round_calls,
            "expectedCalls": uncached + round_calls,
            "estimateBasis": "initial attempts only; round count is an upper bound before fixed market inputs; no credentials read in dry-run",
            "roundDetails": [{"id": p["id"], "eligible": p["eligible"], "issueCount": len(p["items"]), "reason": p["reason"]} for p in previews],
        }
        if args.dry_run:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if args.live:
            provider = OpenAICompatibleProvider(base_url=os.environ.get("ZOOP_SENTIMENT_BASE_URL", "https://api.openai.com/v1"),
                api_key=os.environ.get("ZOOP_SENTIMENT_API_KEY", ""), model=args.model)
        else:
            entries = json.loads(args.replay.read_text(encoding="utf-8"))
            provider = ReplayProvider([ProviderFailure(e["error"], transient=e.get("transient", False)) if "error" in e
                                       else ModelReply(json.dumps(e["response"], ensure_ascii=False), e.get("inputTokens", 0), e.get("outputTokens", 0))
                                       for e in entries], model=args.model or "replay-sentiment")
        sentiment = services.sentiment
        sentiment.provider = provider
        sentiment.max_calls = args.max_calls
        accepted = 0
        limit_reached = False
        try:
            for aid, cid in (sendable if args.live else pairs):
                accepted += sentiment.judge_document(ds, aid, cid) is not None
        except CallLimitReached:
            limit_reached = True
        # Only this command attaches a provider; the HTTP app always builds a read-only service.
        briefings = services.briefings
        published = []
        if not limit_reached:
            for preview in eligible:
                parsed = parse_round_id(preview["id"])
                assert parsed is not None
                briefings.generate(*parsed, trigger="admin", actor=Actor("admin", "sentiment-cli", "sentiment-cli@zoop.local"), blocking=True)
                record = briefings.record(preview["id"])
                if record and record.payload:
                    published.append(record.id)
                elif sentiment.calls >= args.max_calls:
                    limit_reached = True
                    break
        report.update(attempts=sentiment.calls, acceptedDocumentPairs=accepted, publishedRounds=published,
                      callLimit=args.max_calls, limitReached=limit_reached)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2 if limit_reached else 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        # Never expose request URLs, credentials or raw model output in CLI errors.
        parser.exit(1, f"sentiment setup failed ({type(exc).__name__})\n")
    finally:
        if isinstance(provider, OpenAICompatibleProvider):
            provider.close()
        if services:
            services.db.close()
        if temporary:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
