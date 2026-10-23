"""`zoop-ai-chat invoke --state-dir DIR [--grants FILE] [--replay FILE]`: one chatbot model stage.

stdin is one `StageRequest` JSON, stdout is one canonical `StageResult` JSON. Exit 0 when the stage succeeded, 2 when it failed
(the result says why and whether anything was sent), 64 for a request that is not a valid `StageRequest`. The grant registry is
the operator's chat registry, never part of the request; replay requests need `--replay`, live requests use the environment.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from .chat_contracts import ChatGrantRegistry, StageRequest
from .chat_runtime import LiveSender, ReplaySender, invoke
from .contracts import canonical
from .provider import ProviderError


def _fail(code: str, status: int) -> int:
    print(canonical({"error": code}))
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zoop-ai-chat")
    parser.add_argument("command", choices=["invoke"])
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--grants", type=Path, help="Operator-owned chat grant registry (zoop-ai-chat-1)")
    parser.add_argument("--replay", type=Path, help="Authored replay fixture; required for replay requests")
    args = parser.parse_args(argv)

    if not args.state_dir.is_absolute() or not args.state_dir.is_dir():
        return _fail("state_dir_invalid", 64)
    try:
        request = StageRequest.model_validate_json(sys.stdin.read())
        request.parsed()
    except (ValidationError, ValueError):
        return _fail("request_invalid", 64)
    try:
        registry = (ChatGrantRegistry.model_validate_json(args.grants.read_text(encoding="utf-8"))
                    if args.grants else None)
    except (OSError, ValidationError, ValueError):
        return _fail("grant_registry_invalid", 64)
    try:
        if request.mode == "replay":
            if args.replay is None:
                return _fail("replay_fixture_required", 64)
            sender = ReplaySender(args.replay)
        else:
            sender = LiveSender()
    except (OSError, ValueError, KeyError, ProviderError):
        return _fail("replay_fixture_invalid", 64)

    result = invoke(request, state_dir=args.state_dir, registry=registry, sender=sender)
    print(canonical(result.wire()))
    return 0 if result.status == "succeeded" else 2


if __name__ == "__main__":
    sys.exit(main())
