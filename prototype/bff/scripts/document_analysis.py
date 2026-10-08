#!/usr/bin/env python3
"""Import stored worker results or register a current visibility deny. Never calls a model."""
from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

from zoop_bff.admin_services import build_admin_services
from zoop_bff.ai_worker import AiWorkerClient
from zoop_bff.config import Settings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("import", "deny"))
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--worker-state", type=Path)
    parser.add_argument("--grants", type=Path)
    parser.add_argument("--job-id", action="append", default=[])
    parser.add_argument("--document-id")
    parser.add_argument("--reason")
    args = parser.parse_args()
    settings = dataclasses.replace(Settings.from_env(), state_dir=args.state_dir,
                                   briefing_scheduler=False, quote_provider="off")
    services = None
    try:
        services = build_admin_services(settings)
        store = services.sentiment.analysis_store
        if args.command == "deny":
            if not args.document_id or not args.reason:
                parser.error("deny requires --document-id and --reason")
            store.deny(args.document_id, args.reason)
            print(json.dumps({"documentId": args.document_id, "status": "withheld"}))
        else:
            if not args.worker_state or not args.job_id or not args.grants:
                parser.error("import requires --worker-state, --job-id and server-owned --grants")
            registry = json.loads(args.grants.read_text(encoding="utf-8"))
            if registry.get("schemaVersion") != "zoop-ai-s1-1" or not isinstance(registry.get("grants"), list):
                raise ValueError("current_grant_registry_invalid")
            store.replace_current_grants(registry["grants"])
            client = AiWorkerClient(state_dir=args.state_dir, worker_state=args.worker_state)
            ds = services.provider.get()
            print(json.dumps({"imports": [store.import_job(ds, client.get(j)) for j in args.job_id]}, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, OSError):
        print(json.dumps({"error": {"code": "analysis_import_rejected"}}))
        return 2
    finally:
        if services:
            services.db.close()


if __name__ == "__main__":
    raise SystemExit(main())
