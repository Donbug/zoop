"""Explicit operator command: python -m zoop_ai_service.plan_install_cli."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .config import ConfigError
from . import plan_install as core


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline reviewed exact-plan registry installer; never starts or dispatches work.")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Read-only proposal and review digest")
    inspect.add_argument("--plan-dir", type=Path, required=True)
    install = commands.add_parser("install", help="Install the exact reviewed proposal while the service is stopped")
    install.add_argument("--plan-dir", type=Path, required=True)
    install.add_argument("--expected-current-digest", required=True)
    install.add_argument("--expected-review-digest", required=True)
    status = commands.add_parser("status", help="Read-only durable transaction status")
    status.add_argument("--installation-id", required=True)
    recover = commands.add_parser("recover", help="Explicit rollback or committed-transaction bookkeeping")
    recover.add_argument("--installation-id", required=True)
    recover.add_argument("--expected-transaction-digest", required=True)
    args = parser.parse_args()
    try:
        cfg = core.settings(os.environ, recovery=args.command != "inspect")
        if args.command == "inspect":
            result = core.inspect(cfg, args.plan_dir)
        elif args.command == "install":
            result = core.install(cfg, args.plan_dir, args.expected_current_digest, args.expected_review_digest)
        elif args.command == "status":
            result = core.status(cfg, args.installation_id)
        else:
            result = core.recover(cfg, args.installation_id, args.expected_transaction_digest)
    except (core.InstallError, ConfigError) as error:
        code = error.code if isinstance(error, core.InstallError) else error.reason
        print(json.dumps({"schemaVersion": core.SCHEMA, "error": {"code": code}}, sort_keys=True))
        return 78
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print(json.dumps({"schemaVersion": core.SCHEMA, "error": {"code": "installation_invalid"}}, sort_keys=True))
        return 78
    except core.relation_access.AccessError as error:
        print(json.dumps({"schemaVersion": core.SCHEMA, "error": {"code": error.code}}, sort_keys=True))
        return 78
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 78 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
