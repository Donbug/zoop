"""`zoop-ai-chat invoke --state-dir DIR [--grants FILE] [--replay FILE]`: one chatbot model stage.
`zoop-ai-chat probe-mcp`: whether the operator's ZOOP MCP server answers at its configured URL (`chat_probe`).

invoke: stdin is one `StageRequest` JSON, stdout is one canonical `StageResult` JSON. Exit 0 when the stage succeeded, 2 when it
failed (the result says why and whether anything was sent), 64 for a request that is not a valid `StageRequest`. The grant
registry is the operator's chat registry, never part of the request; replay requests need `--replay`, live requests use the
environment.

probe-mcp: stdin is ignored, stdout is one canonical probe result. Exit 0 when the server is reachable, 2 when it is not (the
result names why), 64 when the URL is missing or invalid.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from . import chat_probe
from .chat_contracts import ChatGrantRegistry, StageRequest
from .chat_runtime import LiveSender, ReplaySender, invoke
from .contracts import canonical
from .provider import ProviderError


def _fail(code: str, status: int) -> int:
    print(canonical({"error": code}))
    return status


def _probe() -> int:
    try:
        result = chat_probe.probe()
    except ProviderError as error:
        return _fail(error.code, 64)
    print(canonical(result))
    return 0 if result["mcp"] == "reachable" else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zoop-ai-chat")
    parser.add_argument("command", choices=["invoke", "probe-mcp"])
    parser.add_argument("--state-dir", type=Path, help="The chat invocation ledger directory; required by invoke")
    parser.add_argument("--grants", type=Path, help="Operator-owned chat grant registry (zoop-ai-chat-1)")
    parser.add_argument("--replay", type=Path, help="Authored replay fixture; required for replay requests")
    args = parser.parse_args(argv)

    if args.command == "probe-mcp":
        return _probe()
    if args.state_dir is None or not args.state_dir.is_absolute() or not args.state_dir.is_dir():
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
