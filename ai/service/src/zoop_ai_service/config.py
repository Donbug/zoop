"""Server-owned configuration. Read once at start, validated completely, and failing closed with a field name only.

A request can never choose a path, command, environment value, provider URL, model, fixture or grant registry: all of them
come from here, and none of the values is ever printed or logged.
"""
from __future__ import annotations

import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from . import grants

SCOPES = ("analysis.submit", "analysis.read", "analysis.cancel", "analysis.recover")
PRINCIPAL = re.compile(r"[a-z][a-z0-9-]{0,62}")
DIGEST = re.compile(r"[0-9a-f]{64}")
HOST = "127.0.0.1"
DEFAULT_PORT = 8797
# Pass-through: copied into the child environment only when present. Nothing else of the service environment is.
# Stage model/effort settings shape every job's input digest (replay included); the rest exist only for live execution and are
# withheld unless live is available, so a service without the opt-in can never hand the runtime a way to reach a provider.
STAGE_SETTINGS = tuple(f"ZOOP_AI_{stage}_{setting}" for stage in ("DOCUMENT_SUMMARY", "DOCUMENT_SENTIMENT", "VERIFY", "BRIEFING_OUTLOOK")
                       for setting in ("MODEL", "REASONING_EFFORT"))
LIVE_ONLY = ("ZOOP_AI_LIVE_ENABLED", "ZOOP_AI_GLOBAL_MAX_CALLS", "ZOOP_AI_PROVIDER", "ZOOP_AI_BASE_URL", "ZOOP_AI_API_KEY")
CHILD_BASE_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
                  "PYTHONUNBUFFERED": "1", "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1"}


class ConfigError(Exception):
    """Names the offending variable and a stable reason code; never a value."""

    def __init__(self, field: str, reason: str = "invalid"):
        self.field, self.reason = field, reason
        super().__init__(field)


@dataclass(frozen=True)
class Principal:
    name: str
    digests: tuple[str, ...]
    scopes: frozenset[str]


@dataclass(frozen=True)
class ServiceConfig:
    principals: tuple[Principal, ...]
    state_dir: Path
    worker_state_dir: Path
    worker_command: Path
    grants_path: Path
    replay_path: Path | None
    port: int
    live_available: bool
    child_env: Mapping[str, str]

    @property
    def transport_dir(self) -> Path:
        return self.state_dir / "transport"


def _principals(raw: str | None) -> tuple[Principal, ...]:
    field = "ZOOP_AI_SERVICE_PRINCIPALS"
    if not raw:
        raise ConfigError(field, "missing")
    try:
        entries = json.loads(raw)
    except ValueError:
        raise ConfigError(field, "not_json") from None
    if not isinstance(entries, list) or not entries:
        raise ConfigError(field, "empty")
    principals, names, digests = [], set(), set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"principal", "tokenSha256", "scopes"}:
            raise ConfigError(field, "entry_shape")
        name, hashes, scopes = entry["principal"], entry["tokenSha256"], entry["scopes"]
        if not isinstance(name, str) or not PRINCIPAL.fullmatch(name) or name in names:
            raise ConfigError(field, "principal_invalid")
        if (not isinstance(hashes, list) or not 1 <= len(hashes) <= 2
                or not all(isinstance(h, str) and DIGEST.fullmatch(h) for h in hashes)
                or len(set(hashes)) != len(hashes) or digests & set(hashes)):
            raise ConfigError(field, "digest_invalid")
        if (not isinstance(scopes, list) or not scopes or not all(isinstance(s, str) and s in SCOPES for s in scopes)
                or len(set(scopes)) != len(scopes)):
            raise ConfigError(field, "scope_invalid")
        names.add(name)
        digests.update(hashes)
        principals.append(Principal(name, tuple(hashes), frozenset(scopes)))
    return tuple(principals)


def _normalized(raw: str | None, field: str) -> str:
    if not raw:
        raise ConfigError(field, "missing")
    if not os.path.isabs(raw) or raw != os.path.normpath(raw) or "\0" in raw:
        raise ConfigError(field, "not_absolute_normalized")
    return raw


def _absolute(raw: str | None, field: str) -> Path:
    """Absolute, normalized and free of symlinked components (the existing prefix is compared by real path)."""
    path = _normalized(raw, field)
    if os.path.realpath(path) != path:
        raise ConfigError(field, "symlinked_component")
    return Path(path)


def _overlaps(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _prepare_state_dir(path: Path) -> None:
    field = "ZOOP_AI_SERVICE_STATE_DIR"
    try:
        if not path.exists():
            if not path.parent.is_dir():
                raise ConfigError(field, "parent_missing")
            os.mkdir(path, 0o700)
            os.chmod(path, 0o700)
        info = path.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ConfigError(field, "state_dir_not_private")
        transport = path / "transport"
        transport.mkdir(mode=0o700, exist_ok=True)
        os.chmod(transport, 0o700)
    except OSError:
        raise ConfigError(field, "state_dir_unusable") from None


def _file(raw: str | None, field: str, *, executable: bool = False) -> Path:
    path = Path(_normalized(raw, field))
    if not path.is_file() or not os.access(path, os.X_OK if executable else os.R_OK):
        raise ConfigError(field, "file_unusable")
    return path


def _port(raw: str | None) -> int:
    if raw is None:
        return DEFAULT_PORT
    if not re.fullmatch(r"[0-9]{1,5}", raw) or not 1024 <= int(raw) <= 65535:
        raise ConfigError("ZOOP_AI_SERVICE_PORT", "out_of_range")
    return int(raw)


def _live(environ: Mapping[str, str]) -> bool:
    raw = environ.get("ZOOP_AI_GLOBAL_MAX_CALLS")
    ceiling = 0
    if raw is not None:
        try:
            ceiling = int(raw)
        except ValueError:
            raise ConfigError("ZOOP_AI_GLOBAL_MAX_CALLS", "not_integer") from None
    return environ.get("ZOOP_AI_LIVE_ENABLED") == "1" and ceiling > 0


def load(environ: Mapping[str, str]) -> ServiceConfig:
    principals = _principals(environ.get("ZOOP_AI_SERVICE_PRINCIPALS"))
    state_dir = _absolute(environ.get("ZOOP_AI_SERVICE_STATE_DIR"), "ZOOP_AI_SERVICE_STATE_DIR")
    worker_state = _absolute(environ.get("ZOOP_AI_WORKER_STATE_DIR"), "ZOOP_AI_WORKER_STATE_DIR")
    if _overlaps(state_dir, worker_state):
        raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "overlaps_worker_state")
    if environ.get("ZOOP_STATE_DIR"):
        app_state = _absolute(environ["ZOOP_STATE_DIR"], "ZOOP_STATE_DIR")
        if _overlaps(state_dir, app_state):
            raise ConfigError("ZOOP_AI_SERVICE_STATE_DIR", "overlaps_app_state")
        if _overlaps(worker_state, app_state):
            raise ConfigError("ZOOP_AI_WORKER_STATE_DIR", "overlaps_app_state")
    command = _file(environ.get("ZOOP_AI_SERVICE_WORKER_COMMAND"), "ZOOP_AI_SERVICE_WORKER_COMMAND", executable=True)
    grants_path = _file(environ.get("ZOOP_AI_SERVICE_GRANTS"), "ZOOP_AI_SERVICE_GRANTS")
    try:
        grants.load(grants_path)
    except grants.GrantRegistryError as error:
        raise ConfigError("ZOOP_AI_SERVICE_GRANTS", error.code) from None
    replay = _file(environ["ZOOP_AI_SERVICE_REPLAY"], "ZOOP_AI_SERVICE_REPLAY") if environ.get("ZOOP_AI_SERVICE_REPLAY") else None
    port = _port(environ.get("ZOOP_AI_SERVICE_PORT"))
    live = _live(environ)
    _prepare_state_dir(state_dir)
    child = dict(CHILD_BASE_ENV)
    for key in (*STAGE_SETTINGS, *(LIVE_ONLY if live else ())):
        if key in environ:
            child[key] = environ[key]
    return ServiceConfig(principals, state_dir, worker_state, command, grants_path, replay, port, live, child)
