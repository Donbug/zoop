"""Shared bounded installed verify-plan mechanics for manual installation and online admission."""
from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import time
from pathlib import Path
from typing import Any, Protocol

from . import config, extraction_access, relation_access

FILES = {"approvals.json": extraction_access.MAX_BYTES, "relation-upstreams.json": relation_access.MAX_BYTES,
         "manifest.json": 8_000_000, "receipt.json": 16_000}
MAX_VERIFIER_OUTPUT = 64_000
VERIFIER_TIMEOUT = 60


class Settings(Protocol):
    state: Path
    targets: tuple[Path, ...]
    env: dict[str, str]
    environ: dict[str, str]


class InstallError(Exception):
    """Stable public refusal code; never raw child output or configuration values."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def encode(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def digest(value: Any) -> str:
    return extraction_access.request_digest(value)


def decode(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=relation_access._duplicate_free,
                          parse_constant=relation_access._no_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise InstallError("invalid_json") from None


def read_file(path: Path, maximum: int, *, directory_fd: int | None = None, owned: bool = False) -> bytes:
    """Bounded regular input, optionally relative to a held directory capability."""
    if directory_fd is None and (not path.is_absolute() or os.path.realpath(path) != str(path)):
        raise InstallError("unsafe_path")
    try:
        fd = os.open(path if directory_fd is None else path.name,
                     os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if owned and (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1):
                raise InstallError("target_not_owned_regular")
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                raise InstallError("file_bounds")
            raw = handle.read(maximum + 1)
        if len(raw) > maximum:
            raise InstallError("file_bounds")
        return raw
    except OSError:
        raise InstallError("file_unavailable") from None
def plan_files(path: Path, cfg: Settings) -> tuple[dict[str, bytes], dict, dict]:
    path = config._absolute(str(path), "plan-dir")
    if any(config._overlaps(path, target) for target in cfg.targets) or config._overlaps(path, cfg.state):
        raise InstallError("plan_overlap")
    try:
        if not path.is_dir() or set(p.name for p in path.iterdir()) != set(FILES):
            raise InstallError("plan_files_invalid")
    except OSError:
        raise InstallError("plan_unavailable") from None
    files = {name: read_file(path / name, maximum) for name, maximum in FILES.items()}
    docs = {name: decode(raw) for name, raw in files.items()}
    receipt, manifest = docs["receipt.json"], docs["manifest.json"]
    if not isinstance(receipt, dict) or set(receipt) != {"schemaVersion", "planId", "planDigest", "files"} \
            or receipt["schemaVersion"] != "zoop-extraction-service-plan-receipt-1" \
            or not isinstance(receipt["files"], dict) or set(receipt["files"]) != set(FILES) - {"receipt.json"}:
        raise InstallError("plan_receipt_invalid")
    for name, pin in receipt["files"].items():
        if pin != {"sha256": sha(files[name]), "bytes": len(files[name])}:
            raise InstallError("plan_receipt_mismatch")
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != "zoop-extraction-service-plan-1" \
            or manifest.get("planId") != receipt["planId"] or manifest.get("planDigest") != receipt["planDigest"] \
            or digest({key: value for key, value in manifest.items() if key != "planDigest"}) != receipt["planDigest"]:
        raise InstallError("plan_manifest_invalid")
    return files, manifest, receipt


def verifier_output(argv: list[str], cfg: Settings) -> bytes:
    """Capture a bounded verifier reply through anonymous pipes, without filesystem writes."""
    child = None
    complete = False
    try:
        deadline = time.monotonic() + VERIFIER_TIMEOUT
        child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env=dict(cfg.env), cwd=cfg.state, start_new_session=True, close_fds=True, bufsize=0)
        assert child.stdin is not None and child.stdout is not None and child.stderr is not None
        child.stdin.write(b"{}\n")
        child.stdin.close()
        os.set_blocking(child.stdout.fileno(), False)
        os.set_blocking(child.stderr.fileno(), False)
        raw = bytearray()
        stderr_bytes = 0
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ, "stdout")
            selector.register(child.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise InstallError("plan_verifier_unavailable")
                events = selector.select(remaining)
                if not events:
                    raise InstallError("plan_verifier_unavailable")
                for key, _ in events:
                    size = len(raw) if key.data == "stdout" else stderr_bytes
                    try:
                        chunk = os.read(key.fd, min(65_536, MAX_VERIFIER_OUTPUT + 1 - size))
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if key.data == "stdout":
                        raw.extend(chunk)
                    else:
                        stderr_bytes += len(chunk)
                    if len(raw) > MAX_VERIFIER_OUTPUT or stderr_bytes > MAX_VERIFIER_OUTPUT:
                        raise InstallError("plan_verifier_unavailable")
        code = child.wait(timeout=max(0, deadline - time.monotonic()))
        if code == 2:
            try:
                refused = decode(bytes(raw))
            except InstallError:
                raise InstallError("plan_verifier_unavailable") from None
            if (isinstance(refused, dict) and set(refused) == {"schemaVersion", "error"}
                    and refused["schemaVersion"] == "zoop-extraction-s2-2"
                    and isinstance(refused["error"], dict) and set(refused["error"]) == {"code"}
                    and isinstance(refused["error"]["code"], str)
                    and re.fullmatch(r"[a-z][a-z0-9_]{0,119}", refused["error"]["code"])):
                raise InstallError("plan_verification_failed")
            raise InstallError("plan_verifier_unavailable")
        if code != 0:
            raise InstallError("plan_verifier_unavailable")
        complete = True
        return bytes(raw)
    except (OSError, subprocess.TimeoutExpired):
        raise InstallError("plan_verifier_unavailable") from None
    finally:
        if child is not None:
            if not complete:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
            if child.stdin is not None and not child.stdin.closed:
                child.stdin.close()
            if child.stdout is not None:
                child.stdout.close()
            if child.stderr is not None:
                child.stderr.close()


def verify_plan(path: Path, cfg: Settings, files: dict[str, bytes], manifest: dict, receipt: dict) -> dict:
    env = cfg.environ
    argv = [env["ZOOP_AI_SERVICE_EXTRACTION_COMMAND"], "verify-plan", "--plan-dir", str(path),
            "--expected-receipt-sha256", sha(files["receipt.json"]), "--ingestion-state-dir", env["ZOOP_AI_INGESTION_STATE_DIR"],
            "--sources", env["ZOOP_AI_SERVICE_SOURCES"]]
    if manifest.get("mode") == "replay":
        argv += ["--replay", env["ZOOP_AI_SERVICE_EXTRACTION_REPLAY"]]
        if "topicReplayDigest" in manifest.get("pins", {}):
            if not env.get(config.EXTRACTION_TOPIC):
                raise InstallError("fixture_unavailable")
            argv += ["--topic-replay", env[config.EXTRACTION_TOPIC]]
    elif manifest.get("mode") != "live" or cfg.env.get(config.PIPELINE_LIVE_GATE) != "1":
        raise InstallError("live_unavailable")
    raw = verifier_output(argv, cfg)
    try:
        value = decode(raw)
    except InstallError:
        raise InstallError("plan_verifier_unavailable") from None
    expected = {"schemaVersion": "zoop-extraction-service-plan-verification-1", "planId": receipt["planId"],
                "planDigest": receipt["planDigest"], "receiptSha256": sha(files["receipt.json"]), "principal": manifest.get("principal"),
                "mode": manifest.get("mode"), "pins": manifest.get("pins"), "files": receipt["files"], "counts": manifest.get("counts")}
    if not isinstance(value, dict) or set(value) != {*expected, "sourceRegistrySha256", "sourceBindingsDigest"} \
            or any(value[key] != item for key, item in expected.items()) \
            or any(not isinstance(value[key], str) or not config.DIGEST.fullmatch(value[key]) for key in ("sourceRegistrySha256", "sourceBindingsDigest")) \
            or value["sourceRegistrySha256"] != sha(read_file(Path(env["ZOOP_AI_SERVICE_SOURCES"]), 20_000_000)):
        raise InstallError("plan_verifier_unavailable")
    return value
