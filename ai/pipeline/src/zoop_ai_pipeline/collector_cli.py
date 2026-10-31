"""`zoop-ai-collector`: the single container entry. `run` is the default command of the image."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import sys
import time
import uuid
from pathlib import Path

from . import collector_checkpoint as cp
from . import collector_runtime as rt

SUMMARY_KEYS = ("state", "coverage", "stopCode", "reason", "counts", "usage", "sourceRequests", "sourceBytes",
                "unknownRequests", "unknownByteUpperBound", "retainedInWindow", "pendingCandidates", "pendingPartitions",
                "candidates", "prerequisites")


def _print(value: dict) -> None:
    print(json.dumps(value, sort_keys=True, indent=2), flush=True)


def _worker(name: str, stopped: bool) -> int:
    from pydantic import ValidationError
    from .collector_control import PipeControl
    from .ingestion_contracts import IngestionFailure
    settings = rt.settings_from_env()
    spec = settings.paths[name]
    control = PipeControl(0, int(os.environ["ZOOP_COLLECTOR_EVENT_FD"]), stopping=stopped)
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda *_: control.request_stop())
    try:
        config = rt.load_path_config(name, spec.config_path)
        resume = (Path(config.state_dir) / "PLAN.json").exists()
        if name == "private":
            from .private_intake import run
            result = run(config, "resume" if resume else "run", control)
        elif name == "korea":
            from .korea_corpus import run
            result = run(config, control)
        else:
            from .official_source_intake import run
            key = os.environ.get("OPENDART_API_KEY") if config.source_id == "opendart" else None
            result = run(config, "resume" if resume else "run", runtime_key=key, control=control)
        if result["state"] == "prerequisite":
            control.emit({"event": "result", "state": "refused", "error": "official_prerequisite"})
            return 2
        control.emit({"event": "result", "summary": {k: result[k] for k in SUMMARY_KEYS if k in result}, "state": result["state"]})
        return 0
    except rt.ConfigError as exc:
        control.emit({"event": "result", "state": "refused", "error": exc.code})
    except IngestionFailure as exc:
        control.emit({"event": "result", "state": "refused", "error": exc.code})
    except (OSError, ValueError, ValidationError, TypeError, KeyError):
        control.emit({"event": "result", "state": "refused", "error": f"{name}_input_or_state_invalid"})
    return 2


def _controller_running(settings: rt.Settings) -> bool:
    lock = settings.state_root / "controller.lock"
    try:
        descriptor = os.open(lock, os.O_RDWR | os.O_NOFOLLOW)
    except FileNotFoundError:
        return False
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(descriptor)
    return False


def _checkpoint(timeout: float) -> int:
    settings = rt.settings_from_env(require_run=False)
    if not _controller_running(settings):
        _print({"ok": False, "error": "no_controller"})
        return rt.EXIT_NO_CONTROLLER
    identifier = uuid.uuid4().hex
    request = settings.control_dir / "requests" / f"{identifier}.json"
    rt._atomic_write(request, json.dumps({"id": identifier, "kind": "checkpoint", "requestedAt": cp.utc_now()}).encode(), 0o644)
    response = settings.control_dir / "responses" / f"{identifier}.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if response.exists():
            result = json.loads(response.read_bytes())
            _print(result)
            return rt.EXIT_OK if result["ok"] else rt.EXIT_CHECKPOINT
        time.sleep(0.2)
    request.unlink(missing_ok=True)
    _print({"ok": False, "error": "request_timeout"})
    return rt.EXIT_REQUEST


def _restore(selector: str) -> int:
    settings = rt.settings_from_env()
    if settings.s3_uri is None:
        _print({"ok": False, "error": "setting_missing", "detail": "ZOOP_COLLECTOR_S3_URI"})
        return rt.EXIT_CONFIG
    settings.state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    holder = os.open(settings.state_root / "controller.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        _print({"ok": False, "error": "controller_running"})
        return rt.EXIT_BUSY
    try:
        from .collector_s3 import open_store
        store, prefix = open_store(settings.s3_uri)
        prefix = cp.run_prefix(prefix, settings.run_id)
        found = cp.find_checkpoint(store, prefix, settings.run_id, selector)
        if found is None:
            _print({"ok": False, "error": "checkpoint_not_found"})
            return rt.EXIT_RESTORE
        for entry in found[0]["paths"]:
            if entry["stateDir"] != str(settings.state_dir(entry["name"])):
                _print({"ok": False, "error": "restore_state_dir_mismatch", "detail": entry["name"]})
                return rt.EXIT_RESTORE
        manifest = cp.restore(store, prefix, settings.run_id, settings.state_root, selector=selector)
    except cp.CheckpointError as exc:
        _print({"ok": False, "error": exc.code, "detail": str(exc)})
        return rt.EXIT_RESTORE
    finally:
        os.close(holder)
    _print({"ok": True, "seq": manifest["seq"], "checkpointId": manifest["checkpointId"], "files": len(manifest["files"]),
            "unknownOutcomes": manifest["unknownOutcomes"], "paths": [p["name"] for p in manifest["paths"]]})
    return rt.EXIT_OK


def _status(remote: bool) -> int:
    settings = rt.settings_from_env(require_run=remote)
    status = settings.control_dir / "status.json"
    output = {"controller": "running" if _controller_running(settings) else "none"}
    if status.exists():
        output["status"] = json.loads(status.read_bytes())
    if remote:
        from .collector_s3 import open_store
        store, prefix = open_store(settings.s3_uri)
        output["latest"] = cp.read_pointer(store, cp.run_prefix(prefix, settings.run_id), settings.run_id)
    _print(output)
    return rt.EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zoop-ai-collector", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run", help="collect under one controller, checkpoint to S3, drain on SIGTERM")
    request = commands.add_parser("checkpoint", help="ask the live controller for a checkpoint and wait")
    request.add_argument("--timeout", type=float, default=300)
    restore = commands.add_parser("restore", help="download and verify a checkpoint into empty state directories")
    restore.add_argument("--checkpoint", default="latest", help="latest or <seq>-<checkpointId>")
    status = commands.add_parser("status", help="controller status from the control directory")
    status.add_argument("--remote", action="store_true", help="also read the latest checkpoint pointer from S3")
    worker = commands.add_parser("worker", help=argparse.SUPPRESS)
    worker.add_argument("path", choices=sorted(rt.KINDS))
    worker.add_argument("--stopped", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return rt.run()
        if args.command == "checkpoint":
            return _checkpoint(args.timeout)
        if args.command == "restore":
            return _restore(args.checkpoint)
        if args.command == "status":
            return _status(args.remote)
        return _worker(args.path, args.stopped)
    except rt.ConfigError as exc:
        _print({"ok": False, "error": exc.code, "detail": str(exc)})
        return rt.EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())
