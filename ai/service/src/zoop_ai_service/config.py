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
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import extraction_access, graph_access, grants, handoff_access, relation_access

ANALYSIS_SCOPES = ("analysis.submit", "analysis.read", "analysis.cancel", "analysis.recover")
RELATION_SCOPES = ("relation.submit", "relation.read", "relation.cancel", "relation.recover", "relation.review")
EXTRACTION_SCOPES = ("extraction.submit", "extraction.read", "extraction.cancel", "extraction.recover")
GRAPH_SCOPES = ("graph.read",)
HANDOFF_SCOPES = ("handoff.read", "handoff.exposure")
CHAT_SCOPES = ("chat.invoke",)
PLAN_SCOPES = ("plan.admit", "plan.read", "plan.policy")
SCOPES = (*ANALYSIS_SCOPES, *RELATION_SCOPES, *EXTRACTION_SCOPES, *GRAPH_SCOPES, *HANDOFF_SCOPES, *CHAT_SCOPES, *PLAN_SCOPES)
PRINCIPAL = re.compile(r"[a-z][a-z0-9-]{0,62}")
DIGEST = re.compile(r"[0-9a-f]{64}")
HOST = "127.0.0.1"
DEFAULT_PORT = 8797
# Pass-through: copied into the child environment only when present. Nothing else of the service environment is.
# Stage model/effort settings shape every job's input digest (replay included); the rest exist only for live execution and are
# withheld unless live is available, so a service without the opt-in can never hand the runtime a way to reach a provider.
STAGE_SETTINGS = tuple(f"ZOOP_AI_{stage}_{setting}" for stage in ("DOCUMENT_SUMMARY", "DOCUMENT_SENTIMENT", "VERIFY", "BRIEFING_OUTLOOK")
                       for setting in ("MODEL", "REASONING_EFFORT"))
# The Jev key and endpoint names travel with the other live-only settings: without the live opt-in no child can reach any provider.
LIVE_ONLY = ("ZOOP_AI_LIVE_ENABLED", "ZOOP_AI_GLOBAL_MAX_CALLS", "ZOOP_AI_PROVIDER", "ZOOP_AI_BASE_URL", "ZOOP_AI_API_KEY",
             "ZOOP_AI_VERIFY_PROVIDER", "TYPESAFE_API_KEY", "TYPESAFE_BASE_URL", "TYPESAFE_VALIDATION_MODEL")
CHILD_BASE_ENV = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
                  "PYTHONUNBUFFERED": "1", "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1"}
# S3 relation jobs are an all-or-nothing group: none of these set means the relation routes answer 409 execution_unavailable;
# some but not all (or any invalid one) refuses to start. A request can name none of them.
RELATION_VARS = ("ZOOP_AI_SERVICE_RELATION_COMMAND", "ZOOP_AI_RELATION_STATE_DIR", "ZOOP_AI_EXTRACTION_STATE_DIR",
                 "ZOOP_AI_INGESTION_STATE_DIR", "ZOOP_AI_SERVICE_SOURCES", "ZOOP_AI_SERVICE_RELATION_REPLAY",
                 "ZOOP_AI_SERVICE_RELATION_VERIFIER_REPLAY", "ZOOP_AI_SERVICE_RELATION_UPSTREAMS")
# S2 extraction jobs are a second, separate all-or-nothing group. The three roots/registry variables below are SHARED with the S3 group: both
# families read and write the same operator ingestion/extraction roots through the same registry, so they cannot disagree. The topic fixture
# is the one optional member; naming it alone is an incomplete group.
SHARED_VARS = ("ZOOP_AI_EXTRACTION_STATE_DIR", "ZOOP_AI_INGESTION_STATE_DIR", "ZOOP_AI_SERVICE_SOURCES")
RELATION_OWN = tuple(name for name in RELATION_VARS if name not in SHARED_VARS)
EXTRACTION_OWN = ("ZOOP_AI_SERVICE_EXTRACTION_COMMAND", "ZOOP_AI_SERVICE_EXTRACTION_REPLAY", "ZOOP_AI_SERVICE_EXTRACTION_APPROVALS")
EXTRACTION_TOPIC = "ZOOP_AI_SERVICE_EXTRACTION_TOPIC_REPLAY"
EXTRACTION_VARS = (*EXTRACTION_OWN, *SHARED_VARS)
# The read-only graph door is a third, separate all-or-nothing group. It names its OWN source roots and registry (they are not the S2/S3 group's
# variables, so setting them never switches those groups on); when an S2/S3 group is configured they must be exactly the same paths, because the
# graph reads the very ledgers those groups write. `ZOOP_GRAPH_AUTH` alone never switches the group on (an operator shell may export it for the
# pipeline CLI); once the group is on, it and, for `basic`, the user and password are required. They reach the graph child only.
GRAPH_SWITCH = ("ZOOP_AI_SERVICE_GRAPH_COMMAND", "ZOOP_AI_GRAPH_STATE_DIR", "ZOOP_AI_GRAPH_RELATION_STATE_DIR", "ZOOP_AI_GRAPH_EXTRACTION_STATE_DIR",
                "ZOOP_AI_GRAPH_INGESTION_STATE_DIR", "ZOOP_AI_SERVICE_GRAPH_SOURCES", "ZOOP_AI_SERVICE_GRAPH_CANONICAL", "ZOOP_AI_SERVICE_GRAPH_VERSIONS")
GRAPH_VARS = (*GRAPH_SWITCH, "ZOOP_GRAPH_AUTH")
GRAPH_CREDENTIALS = ("ZOOP_GRAPH_USER", "ZOOP_GRAPH_PASSWORD")
# The read-only handoff door is a fourth, separate all-or-nothing group (scope `handoff.read`, none of the graph.read variables). It runs the installed
# `zoop-ai-handoff export` only and needs no credential: the handoff reads the S2/S3/ingestion ledgers, the source registry and three operator files, never
# the Neo4j graph, so no ZOOP_GRAPH_* value reaches its child. Its own source roots and registry are named here (naming them never switches the S2/S3
# groups on); when an S2/S3 group is configured they must be exactly the same paths, because the handoff reads the very ledgers those groups write.
HANDOFF_VARS = ("ZOOP_AI_SERVICE_HANDOFF_COMMAND", "ZOOP_AI_HANDOFF_STATE_DIR", "ZOOP_AI_HANDOFF_RELATION_STATE_DIR", "ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR",
                "ZOOP_AI_HANDOFF_INGESTION_STATE_DIR", "ZOOP_AI_SERVICE_HANDOFF_SOURCES", "ZOOP_AI_SERVICE_HANDOFF_CANONICAL",
                "ZOOP_AI_SERVICE_HANDOFF_DECISIONS", "ZOOP_AI_SERVICE_HANDOFF_BINDINGS", "ZOOP_AI_SERVICE_HANDOFF_EXPORTS")
HANDOFF_EXPOSURE_VARS = ("ZOOP_AI_SERVICE_HANDOFF_EXPOSURE_COMMAND", "ZOOP_AI_HANDOFF_EXPOSURE_STATE_DIR",
                         "ZOOP_AI_HANDOFF_EXPOSURE_EXTRACTION_STATE_DIR", "ZOOP_AI_HANDOFF_EXPOSURE_INGESTION_STATE_DIR",
                         "ZOOP_AI_SERVICE_HANDOFF_EXPOSURE_EXPORTS")
# Live S2/S3 children. ONE service-side switch AND the pipeline's own gate are both required; neither alone forwards anything. The names below are
# the complete set the pipeline's live runtime reads (`zoop_ai_pipeline.live_runtime`): nothing else of the service environment ever reaches a
# pipeline child, and replay, dependency, graph, handoff and S1 children never receive any of it. A job-registering child (`submit`) gets only the
# non-secret model/endpoint names; only a child that may send (`resume`) also gets the budget settings and both keys. Values are never logged.
PIPELINE_LIVE_SWITCH = "ZOOP_AI_SERVICE_PIPELINE_LIVE"
PIPELINE_LIVE_GATE = "ZOOP_AI_PIPELINE_LIVE_ENABLED"
PIPELINE_LIVE_PUBLIC_REQUIRED = (PIPELINE_LIVE_GATE, "ZOOP_AI_PIPELINE_LIVE_MODEL", "ZOOP_AI_PIPELINE_LIVE_REASONING_EFFORT", "TYPESAFE_VALIDATION_MODEL")
PIPELINE_LIVE_PUBLIC_OPTIONAL = ("ZOOP_AI_PIPELINE_LIVE_MAX_OUTPUT_TOKENS", "ZOOP_AI_PIPELINE_LIVE_TIMEOUT_SECONDS", "ZOOP_AI_BASE_URL", "TYPESAFE_BASE_URL")
PIPELINE_LIVE_BUDGET = ("ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR", "ZOOP_AI_PIPELINE_LIVE_MAX_USD", "ZOOP_AI_PIPELINE_LIVE_MAX_CALLS")
PIPELINE_LIVE_SECRETS = ("ZOOP_AI_API_KEY", "TYPESAFE_API_KEY")
# The chatbot model stage door (`zoop-ai-chat`) is a fifth, separate all-or-nothing group (scope `chat.invoke`). Its child gets the chat gate, the
# non-secret model and endpoint names, and the two keys only while the chat gate is open (`ZOOP_AI_CHAT_LIVE_ENABLED=1` and a positive
# `ZOOP_AI_CHAT_MAX_CALLS`). The S1 and pipeline gates never open it, and no other child receives any of it. The replay fixture is optional.
CHAT_VARS = ("ZOOP_AI_SERVICE_CHAT_COMMAND", "ZOOP_AI_CHAT_STATE_DIR", "ZOOP_AI_SERVICE_CHAT_GRANTS")
CHAT_REPLAY = "ZOOP_AI_SERVICE_CHAT_REPLAY"
CHAT_GATE = ("ZOOP_AI_CHAT_LIVE_ENABLED", "ZOOP_AI_CHAT_MAX_CALLS")
CHAT_PUBLIC = ("ZOOP_AI_CHAT_ANSWER_MODEL", "ZOOP_AI_CHAT_ANSWER_REASONING_EFFORT", "ZOOP_AI_CHAT_AGENT_MODEL",
               "ZOOP_AI_CHAT_AGENT_REASONING_EFFORT", "ZOOP_AI_CHAT_JEV_MODEL", "ZOOP_AI_BASE_URL", "TYPESAFE_BASE_URL")
CHAT_SECRETS = ("ZOOP_AI_API_KEY", "TYPESAFE_API_KEY")


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
class PipelineLive:
    """The environment a live S2/S3 child may receive, split by what each command needs. Frozen at start; the service never reads it again."""
    public: Mapping[str, str]
    budget: Mapping[str, str]
    secret: Mapping[str, str]

    def freeze_env(self, base: Mapping[str, str]) -> dict[str, str]:
        """A child that registers a live job: the gate, the non-secret model/endpoint settings and the budget DIRECTORY (pinned in the
        runtime binding by its realpath; nothing is created), never a key, a cap, or a budget amount."""
        return {**base, **self.public, "ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR": self.budget["ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR"]}

    def send_env(self, base: Mapping[str, str]) -> dict[str, str]:
        """A child that may send a model call: everything the live runtime reads."""
        return {**base, **self.public, **self.budget, **self.secret}


@dataclass(frozen=True)
class RelationConfig:
    command: Path
    state_dir: Path            # the service is its only writer
    extraction_state_dir: Path  # operator-written; the pipeline opens it read-only
    ingestion_state_dir: Path   # operator-written; the pipeline opens it read-only
    sources_path: Path
    producer_replay: Path
    verifier_replay: Path
    upstreams_path: Path | None
    child_env: Mapping[str, str]


@dataclass(frozen=True)
class ExtractionConfig:
    command: Path
    state_dir: Path             # the pipeline's S2 ledger (its writer is the `zoop-ai-extract` child this service starts)
    ingestion_state_dir: Path   # operator-written; the pipeline opens it read-only
    sources_path: Path
    producer_replay: Path       # the one authored replay fixture; its digest is pinned in every approval
    topic_replay: Path | None   # optional topic fixture; its digest is pinned only in approvals that request a topic stage
    approvals_path: Path | None
    child_env: Mapping[str, str]


@dataclass(frozen=True)
class GraphConfig:
    command: Path
    state_dir: Path             # the graph ledger (graph.sqlite3 + graph.lock): operator-written, the pipeline opens it read-only
    relation_state_dir: Path    # S3 ledger the projected version was frozen from: read-only here
    extraction_state_dir: Path
    ingestion_state_dir: Path
    sources_path: Path
    canonical_path: Path        # server-owned canonical decision registry (zoop-graph-canonical-1), re-read by the pipeline on every read
    versions_path: Path         # server-owned per-principal version allowlist (zoop-ai-graph-versions-1), re-read on every request
    shared_gate: bool           # an S2/S3 group of this process writes ledgers the graph reads: serialize behind their gate (static, never guessed)
    child_env: Mapping[str, str]


@dataclass(frozen=True)
class HandoffConfig:
    command: Path
    state_dir: Path             # the handoff ledger (handoff.sqlite3 + artifacts): operator-written by `freeze`/`recover`, the pipeline opens it read-only
    relation_state_dir: Path    # S3 ledger the handoff was frozen from: read-only here
    extraction_state_dir: Path
    ingestion_state_dir: Path
    sources_path: Path
    canonical_path: Path        # operator files pinned by their sha256 in every manifest; the pipeline re-reads and compares them on every export
    decisions_path: Path
    bindings_path: Path
    exports_path: Path          # server-owned per-principal pin allowlist (zoop-ai-handoff-exports-1), re-read on every request
    shared_gate: bool           # an S2/S3 group of this process writes ledgers the handoff reads: serialize behind their gate (static, never guessed)
    child_env: Mapping[str, str]


@dataclass(frozen=True)
class HandoffExposureConfig:
    command: Path
    state_dir: Path
    extraction_state_dir: Path
    ingestion_state_dir: Path
    exports_path: Path
    shared_gate: bool
    child_env: Mapping[str, str]


@dataclass(frozen=True)
class ChatConfig:
    command: Path
    state_dir: Path             # the chat invocation ledger (chat.sqlite3): the `zoop-ai-chat` child this service starts is its only writer
    grants_path: Path           # operator chat grant registry (zoop-ai-chat-1), separate from the S1 registry
    replay_path: Path | None    # authored replay fixture; without it a replay request answers 409 execution_unavailable
    live_available: bool        # the chat gate is open: the child may send to a provider
    child_env: Mapping[str, str]


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
    relation: RelationConfig | None = None
    extraction: ExtractionConfig | None = None
    graph: GraphConfig | None = None
    handoff: HandoffConfig | None = None
    pipeline_live: PipelineLive | None = None
    handoff_exposure: HandoffExposureConfig | None = None
    chat: ChatConfig | None = None
    plan_root: Path | None = None

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
        if "plan.policy" in scopes and any(s in scopes for s in (*EXTRACTION_SCOPES, *RELATION_SCOPES, "plan.admit")):
            raise ConfigError(field, "policy_scope_separation")
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


CHAT_LEDGER_FILES = ("chat.sqlite3", "chat.sqlite3-wal", "chat.sqlite3-shm")


def _prepare_chat_state(path: Path) -> None:
    """The chat ledger holds raw provider answers and the no-resend and budget records. Like the service state root it must be a real directory
    owned by this user with no group or world access; an existing one is checked, never repaired by chmod, and a symlink is refused. Ledger files
    already in it must be regular private files of this user (the worker creates them 0600)."""
    field = "ZOOP_AI_CHAT_STATE_DIR"
    try:
        if not os.path.lexists(path):
            if not path.parent.is_dir():
                raise ConfigError(field, "parent_missing")
            os.mkdir(path, 0o700)
            os.chmod(path, 0o700)
        info = os.lstat(path)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ConfigError(field, "state_dir_not_private")
        for name in CHAT_LEDGER_FILES:
            entry = path / name
            if not os.path.lexists(entry):
                continue
            item = os.lstat(entry)
            if not stat.S_ISREG(item.st_mode) or item.st_uid != os.getuid() or item.st_mode & 0o077:
                raise ConfigError(field, "ledger_not_private")
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


def _existing_dir(raw: str | None, field: str) -> Path:
    path = _absolute(raw, field)
    if not path.is_dir():
        raise ConfigError(field, "directory_missing")
    return path


def _disjoint(roots: dict[str, Path], reason: str) -> None:
    names = list(roots)
    for index, first in enumerate(names):
        for second in names[index + 1:]:
            if _overlaps(roots[first], roots[second]):
                raise ConfigError(second, reason)


def _child_env(app_state: Path, worker_state: Path) -> dict[str, str]:
    # The installed pipeline refuses a ledger that overlaps the application or S1 worker roots unless both are named. No provider variable,
    # key, URL or model setting is ever copied: the S2/S3 pipelines are replay only and have no way to reach a network.
    return {**CHILD_BASE_ENV, "ZOOP_STATE_DIR": str(app_state), "ZOOP_AI_WORKER_STATE_DIR": str(worker_state)}


def _relation(environ: Mapping[str, str], principals: tuple[Principal, ...], state_dir: Path, worker_state: Path,
              enabled: bool) -> RelationConfig | None:
    """All-or-nothing: no relation variable means the feature is off; any one means every one must be valid. The variables shared with the S2
    group do not by themselves switch the relation group on when the S2 group is configured."""
    if not enabled:
        return None
    online = environ.get("ZOOP_AI_SERVICE_PLAN_ADMISSION") == "1"
    for name in (n for n in RELATION_VARS if not online or n != "ZOOP_AI_SERVICE_RELATION_UPSTREAMS"):
        if name not in environ:
            raise ConfigError(name, "relation_group_incomplete")
    command = _file(environ["ZOOP_AI_SERVICE_RELATION_COMMAND"], "ZOOP_AI_SERVICE_RELATION_COMMAND", executable=True)
    app_state = _absolute(environ.get("ZOOP_STATE_DIR"), "ZOOP_STATE_DIR")  # the installed pipeline fails closed without it
    relation_state = _absolute(environ["ZOOP_AI_RELATION_STATE_DIR"], "ZOOP_AI_RELATION_STATE_DIR")
    if not relation_state.exists() and not relation_state.parent.is_dir():
        raise ConfigError("ZOOP_AI_RELATION_STATE_DIR", "parent_missing")
    if relation_state.exists() and not relation_state.is_dir():
        raise ConfigError("ZOOP_AI_RELATION_STATE_DIR", "not_a_directory")
    extraction = _existing_dir(environ["ZOOP_AI_EXTRACTION_STATE_DIR"], "ZOOP_AI_EXTRACTION_STATE_DIR")
    ingestion = _existing_dir(environ["ZOOP_AI_INGESTION_STATE_DIR"], "ZOOP_AI_INGESTION_STATE_DIR")
    _disjoint({"ZOOP_AI_SERVICE_STATE_DIR": state_dir, "ZOOP_AI_WORKER_STATE_DIR": worker_state, "ZOOP_STATE_DIR": app_state,
               "ZOOP_AI_RELATION_STATE_DIR": relation_state, "ZOOP_AI_EXTRACTION_STATE_DIR": extraction,
               "ZOOP_AI_INGESTION_STATE_DIR": ingestion}, "relation_roots_overlap")
    sources = _file(environ["ZOOP_AI_SERVICE_SOURCES"], "ZOOP_AI_SERVICE_SOURCES")
    producer = _file(environ["ZOOP_AI_SERVICE_RELATION_REPLAY"], "ZOOP_AI_SERVICE_RELATION_REPLAY")
    verifier = _file(environ["ZOOP_AI_SERVICE_RELATION_VERIFIER_REPLAY"], "ZOOP_AI_SERVICE_RELATION_VERIFIER_REPLAY")
    upstreams = None
    if not online:
        upstreams = _file(environ["ZOOP_AI_SERVICE_RELATION_UPSTREAMS"], "ZOOP_AI_SERVICE_RELATION_UPSTREAMS")
        try:
            relation_access.load(upstreams, [p.name for p in principals])
        except relation_access.AccessError as error:
            raise ConfigError("ZOOP_AI_SERVICE_RELATION_UPSTREAMS", error.code) from None
    return RelationConfig(command, relation_state, extraction, ingestion, sources, producer, verifier, upstreams, _child_env(app_state, worker_state))


def _extraction(environ: Mapping[str, str], principals: tuple[Principal, ...], state_dir: Path, worker_state: Path) -> ExtractionConfig | None:
    """All-or-nothing, like the relation group. The approvals file is validated completely here (shape, digests, topic pins against the optional
    topic fixture); the fixture digests themselves are checked against the pins on every use, not at start."""
    if not any(name in environ for name in (*EXTRACTION_OWN, EXTRACTION_TOPIC)):
        return None
    online = environ.get("ZOOP_AI_SERVICE_PLAN_ADMISSION") == "1"
    for name in (n for n in EXTRACTION_VARS if not online or n != "ZOOP_AI_SERVICE_EXTRACTION_APPROVALS"):
        if name not in environ:
            raise ConfigError(name, "extraction_group_incomplete")
    command = _file(environ["ZOOP_AI_SERVICE_EXTRACTION_COMMAND"], "ZOOP_AI_SERVICE_EXTRACTION_COMMAND", executable=True)
    app_state = _absolute(environ.get("ZOOP_STATE_DIR"), "ZOOP_STATE_DIR")
    extraction = _existing_dir(environ["ZOOP_AI_EXTRACTION_STATE_DIR"], "ZOOP_AI_EXTRACTION_STATE_DIR")
    ingestion = _existing_dir(environ["ZOOP_AI_INGESTION_STATE_DIR"], "ZOOP_AI_INGESTION_STATE_DIR")
    _disjoint({"ZOOP_AI_SERVICE_STATE_DIR": state_dir, "ZOOP_AI_WORKER_STATE_DIR": worker_state, "ZOOP_STATE_DIR": app_state,
               "ZOOP_AI_EXTRACTION_STATE_DIR": extraction, "ZOOP_AI_INGESTION_STATE_DIR": ingestion}, "extraction_roots_overlap")
    sources = _file(environ["ZOOP_AI_SERVICE_SOURCES"], "ZOOP_AI_SERVICE_SOURCES")
    producer = _file(environ["ZOOP_AI_SERVICE_EXTRACTION_REPLAY"], "ZOOP_AI_SERVICE_EXTRACTION_REPLAY")
    topic = _file(environ[EXTRACTION_TOPIC], EXTRACTION_TOPIC) if EXTRACTION_TOPIC in environ else None
    approvals = None
    if not online:
        approvals = _file(environ["ZOOP_AI_SERVICE_EXTRACTION_APPROVALS"], "ZOOP_AI_SERVICE_EXTRACTION_APPROVALS")
        live_available = environ.get(PIPELINE_LIVE_SWITCH) == "1" and environ.get(PIPELINE_LIVE_GATE) == "1"
        try:
            extraction_access.load(approvals, [p.name for p in principals], topic_available=topic is not None, live_available=live_available)
        except extraction_access.AccessError as error:
            raise ConfigError("ZOOP_AI_SERVICE_EXTRACTION_APPROVALS", error.code) from None
    return ExtractionConfig(command, extraction, ingestion, sources, producer, topic, approvals, _child_env(app_state, worker_state))


def _graph(environ: Mapping[str, str], principals: tuple[Principal, ...], state_dir: Path, worker_state: Path,
           relation: RelationConfig | None, extraction: ExtractionConfig | None) -> GraphConfig | None:
    """All-or-nothing, like the S2/S3 groups. Every root is validated here; the allowlist file is validated completely (the same strict rules apply
    again on every request). The graph root must exist: only the operator's `zoop-ai-graph init` creates it and the child opens it read-only."""
    if not any(name in environ for name in GRAPH_SWITCH):
        return None
    for name in GRAPH_VARS:
        if name not in environ:
            raise ConfigError(name, "graph_group_incomplete")
    command = _file(environ["ZOOP_AI_SERVICE_GRAPH_COMMAND"], "ZOOP_AI_SERVICE_GRAPH_COMMAND", executable=True)
    app_state = _absolute(environ.get("ZOOP_STATE_DIR"), "ZOOP_STATE_DIR")
    roots = {name: _existing_dir(environ[name], name) for name in ("ZOOP_AI_GRAPH_STATE_DIR", "ZOOP_AI_GRAPH_RELATION_STATE_DIR",
                                                                   "ZOOP_AI_GRAPH_EXTRACTION_STATE_DIR", "ZOOP_AI_GRAPH_INGESTION_STATE_DIR")}
    _disjoint({"ZOOP_AI_SERVICE_STATE_DIR": state_dir, "ZOOP_AI_WORKER_STATE_DIR": worker_state, "ZOOP_STATE_DIR": app_state, **roots}, "graph_roots_overlap")
    sources = _file(environ["ZOOP_AI_SERVICE_GRAPH_SOURCES"], "ZOOP_AI_SERVICE_GRAPH_SOURCES")
    canonical = _file(environ["ZOOP_AI_SERVICE_GRAPH_CANONICAL"], "ZOOP_AI_SERVICE_GRAPH_CANONICAL")
    versions = _file(environ["ZOOP_AI_SERVICE_GRAPH_VERSIONS"], "ZOOP_AI_SERVICE_GRAPH_VERSIONS")
    try:
        graph_access.load(versions, [p.name for p in principals])
    except graph_access.AccessError as error:
        raise ConfigError("ZOOP_AI_SERVICE_GRAPH_VERSIONS", error.code) from None
    # The graph reads the very ledgers an S2/S3 group of this process writes: the same roots and registry or nothing. A group that is not configured
    # names nothing to compare with.
    same: list[tuple[str, Path, Path]] = []
    if relation is not None:
        same += [("ZOOP_AI_GRAPH_RELATION_STATE_DIR", roots["ZOOP_AI_GRAPH_RELATION_STATE_DIR"], relation.state_dir),
                 ("ZOOP_AI_GRAPH_EXTRACTION_STATE_DIR", roots["ZOOP_AI_GRAPH_EXTRACTION_STATE_DIR"], relation.extraction_state_dir),
                 ("ZOOP_AI_GRAPH_INGESTION_STATE_DIR", roots["ZOOP_AI_GRAPH_INGESTION_STATE_DIR"], relation.ingestion_state_dir),
                 ("ZOOP_AI_SERVICE_GRAPH_SOURCES", sources, relation.sources_path)]
    if extraction is not None:
        same += [("ZOOP_AI_GRAPH_EXTRACTION_STATE_DIR", roots["ZOOP_AI_GRAPH_EXTRACTION_STATE_DIR"], extraction.state_dir),
                 ("ZOOP_AI_GRAPH_INGESTION_STATE_DIR", roots["ZOOP_AI_GRAPH_INGESTION_STATE_DIR"], extraction.ingestion_state_dir),
                 ("ZOOP_AI_SERVICE_GRAPH_SOURCES", sources, extraction.sources_path)]
    for name, mine, theirs in same:
        if mine != theirs:
            raise ConfigError(name, "graph_source_inconsistent")
    mode = environ["ZOOP_GRAPH_AUTH"]
    secrets: dict[str, str] = {}
    if mode == "basic":
        for name, limit in (("ZOOP_GRAPH_USER", 200), ("ZOOP_GRAPH_PASSWORD", 2000)):   # the installed pipeline's own limits
            value = environ.get(name)
            if not value:
                raise ConfigError(name, "missing")
            if len(value) > limit:
                raise ConfigError(name, "invalid")
            secrets[name] = value
    elif mode == "none":
        for name in GRAPH_CREDENTIALS:
            if name in environ:
                raise ConfigError(name, "graph_auth_unexpected")
    else:
        raise ConfigError("ZOOP_GRAPH_AUTH", "invalid")
    # Credentials go into this child's environment and no other: the S1/S2/S3 child environments are built from `_child_env` alone.
    return GraphConfig(command, roots["ZOOP_AI_GRAPH_STATE_DIR"], roots["ZOOP_AI_GRAPH_RELATION_STATE_DIR"], roots["ZOOP_AI_GRAPH_EXTRACTION_STATE_DIR"],
                       roots["ZOOP_AI_GRAPH_INGESTION_STATE_DIR"], sources, canonical, versions, relation is not None or extraction is not None,
                       {**_child_env(app_state, worker_state), "ZOOP_GRAPH_AUTH": mode, **secrets})


def _handoff(environ: Mapping[str, str], principals: tuple[Principal, ...], state_dir: Path, worker_state: Path, relation: RelationConfig | None,
             extraction: ExtractionConfig | None, graph: GraphConfig | None) -> HandoffConfig | None:
    """All-or-nothing, like the other groups, and without any credential. Every root and file is validated here; the allowlist is validated completely
    (the same strict rules apply again on every request). The handoff root must exist: only the operator's `zoop-ai-handoff freeze` creates it."""
    if not any(name in environ for name in HANDOFF_VARS):
        return None
    for name in HANDOFF_VARS:
        if name not in environ:
            raise ConfigError(name, "handoff_group_incomplete")
    command = _file(environ["ZOOP_AI_SERVICE_HANDOFF_COMMAND"], "ZOOP_AI_SERVICE_HANDOFF_COMMAND", executable=True)
    app_state = _absolute(environ.get("ZOOP_STATE_DIR"), "ZOOP_STATE_DIR")
    roots = {name: _existing_dir(environ[name], name) for name in ("ZOOP_AI_HANDOFF_STATE_DIR", "ZOOP_AI_HANDOFF_RELATION_STATE_DIR",
                                                                   "ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR", "ZOOP_AI_HANDOFF_INGESTION_STATE_DIR")}
    _disjoint({"ZOOP_AI_SERVICE_STATE_DIR": state_dir, "ZOOP_AI_WORKER_STATE_DIR": worker_state, "ZOOP_STATE_DIR": app_state, **roots}, "handoff_roots_overlap")
    if graph is not None and _overlaps(roots["ZOOP_AI_HANDOFF_STATE_DIR"], graph.state_dir):
        raise ConfigError("ZOOP_AI_HANDOFF_STATE_DIR", "handoff_roots_overlap")
    sources = _file(environ["ZOOP_AI_SERVICE_HANDOFF_SOURCES"], "ZOOP_AI_SERVICE_HANDOFF_SOURCES")
    files = {name: _file(environ[name], name) for name in ("ZOOP_AI_SERVICE_HANDOFF_CANONICAL", "ZOOP_AI_SERVICE_HANDOFF_DECISIONS",
                                                           "ZOOP_AI_SERVICE_HANDOFF_BINDINGS")}
    exports = _file(environ["ZOOP_AI_SERVICE_HANDOFF_EXPORTS"], "ZOOP_AI_SERVICE_HANDOFF_EXPORTS")
    try:
        handoff_access.load(exports, [p.name for p in principals])
    except handoff_access.AccessError as error:
        raise ConfigError("ZOOP_AI_SERVICE_HANDOFF_EXPORTS", error.code) from None
    same: list[tuple[str, Path, Path]] = []
    if relation is not None:
        same += [("ZOOP_AI_HANDOFF_RELATION_STATE_DIR", roots["ZOOP_AI_HANDOFF_RELATION_STATE_DIR"], relation.state_dir),
                 ("ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR", roots["ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR"], relation.extraction_state_dir),
                 ("ZOOP_AI_HANDOFF_INGESTION_STATE_DIR", roots["ZOOP_AI_HANDOFF_INGESTION_STATE_DIR"], relation.ingestion_state_dir),
                 ("ZOOP_AI_SERVICE_HANDOFF_SOURCES", sources, relation.sources_path)]
    if extraction is not None:
        same += [("ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR", roots["ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR"], extraction.state_dir),
                 ("ZOOP_AI_HANDOFF_INGESTION_STATE_DIR", roots["ZOOP_AI_HANDOFF_INGESTION_STATE_DIR"], extraction.ingestion_state_dir),
                 ("ZOOP_AI_SERVICE_HANDOFF_SOURCES", sources, extraction.sources_path)]
    for name, mine, theirs in same:
        if mine != theirs:
            raise ConfigError(name, "handoff_source_inconsistent")
    # The child environment is the plain ownership environment: no graph credential, provider key or token digest is ever copied into it.
    return HandoffConfig(command, roots["ZOOP_AI_HANDOFF_STATE_DIR"], roots["ZOOP_AI_HANDOFF_RELATION_STATE_DIR"], roots["ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR"],
                         roots["ZOOP_AI_HANDOFF_INGESTION_STATE_DIR"], sources, files["ZOOP_AI_SERVICE_HANDOFF_CANONICAL"],
                         files["ZOOP_AI_SERVICE_HANDOFF_DECISIONS"], files["ZOOP_AI_SERVICE_HANDOFF_BINDINGS"], exports,
                         relation is not None or extraction is not None, _child_env(app_state, worker_state))


def _handoff_exposure(environ: Mapping[str, str], principals: tuple[Principal, ...], state_dir: Path, worker_state: Path,
                      relation: RelationConfig | None, extraction: ExtractionConfig | None, graph: GraphConfig | None,
                      handoff: HandoffConfig | None) -> HandoffExposureConfig | None:
    if not any(name in environ for name in HANDOFF_EXPOSURE_VARS):
        return None
    for name in HANDOFF_EXPOSURE_VARS:
        if name not in environ:
            raise ConfigError(name, "handoff_exposure_group_incomplete")
    command = _file(environ[HANDOFF_EXPOSURE_VARS[0]], HANDOFF_EXPOSURE_VARS[0], executable=True)
    app_state = _absolute(environ.get("ZOOP_STATE_DIR"), "ZOOP_STATE_DIR")
    roots = {name: _existing_dir(environ[name], name) for name in HANDOFF_EXPOSURE_VARS[1:4]}
    _disjoint({"ZOOP_AI_SERVICE_STATE_DIR": state_dir, "ZOOP_AI_WORKER_STATE_DIR": worker_state, "ZOOP_STATE_DIR": app_state, **roots},
              "handoff_exposure_roots_overlap")
    root, extracted, ingested = (roots[name] for name in HANDOFF_EXPOSURE_VARS[1:4])
    for group in (relation, graph):
        if group is not None and any(_overlaps(path, group.state_dir) for path in roots.values()):
            raise ConfigError(HANDOFF_EXPOSURE_VARS[1], "handoff_exposure_roots_overlap")
    exports = _file(environ[HANDOFF_EXPOSURE_VARS[4]], HANDOFF_EXPOSURE_VARS[4])
    try:
        handoff_access.load(exports, [p.name for p in principals])
    except handoff_access.AccessError as error:
        raise ConfigError(HANDOFF_EXPOSURE_VARS[4], error.code) from None
    same: list[tuple[str, Path, Path]] = []
    for group in (relation, graph, handoff):
        if group is not None:
            same += [(HANDOFF_EXPOSURE_VARS[2], extracted, group.extraction_state_dir),
                     (HANDOFF_EXPOSURE_VARS[3], ingested, group.ingestion_state_dir)]
    if extraction is not None:
        same += [(HANDOFF_EXPOSURE_VARS[2], extracted, extraction.state_dir),
                 (HANDOFF_EXPOSURE_VARS[3], ingested, extraction.ingestion_state_dir)]
    if handoff is not None:
        same += [(HANDOFF_EXPOSURE_VARS[1], root, handoff.state_dir), (HANDOFF_EXPOSURE_VARS[4], exports, handoff.exports_path)]
        if any(_overlaps(path, handoff.relation_state_dir) for path in roots.values()):
            raise ConfigError(HANDOFF_EXPOSURE_VARS[1], "handoff_exposure_roots_overlap")
    for name, mine, theirs in same:
        if mine != theirs:
            raise ConfigError(name, "handoff_exposure_source_inconsistent")
    return HandoffExposureConfig(command, root, extracted, ingested, exports, relation is not None or extraction is not None,
                                 _child_env(app_state, worker_state))


def _pipeline_live(environ: Mapping[str, str], state_dir: Path, relation: RelationConfig | None, extraction: ExtractionConfig | None) -> PipelineLive | None:
    """Off unless BOTH the service switch and the pipeline gate are `1`. When on: an S2 or S3 group must exist and every required name must be set
    and valid, otherwise start fails with the offending name only (never a value)."""
    if environ.get(PIPELINE_LIVE_SWITCH) != "1":
        return None
    if environ.get(PIPELINE_LIVE_GATE) != "1":
        raise ConfigError(PIPELINE_LIVE_GATE, "pipeline_live_gate_missing")
    if relation is None and extraction is None:
        raise ConfigError(PIPELINE_LIVE_SWITCH, "pipeline_live_without_group")
    for name in (*PIPELINE_LIVE_PUBLIC_REQUIRED, *PIPELINE_LIVE_BUDGET, *PIPELINE_LIVE_SECRETS):
        if not environ.get(name):
            raise ConfigError(name, "pipeline_live_incomplete")
    for name in (*PIPELINE_LIVE_PUBLIC_REQUIRED, *PIPELINE_LIVE_PUBLIC_OPTIONAL, *PIPELINE_LIVE_BUDGET, *PIPELINE_LIVE_SECRETS):
        value = environ.get(name)
        if value is not None and (value != value.strip() or any(ord(char) < 32 for char in value)):
            raise ConfigError(name, "pipeline_live_invalid")
    try:
        ceiling = Decimal(environ["ZOOP_AI_PIPELINE_LIVE_MAX_USD"])
        calls = int(environ["ZOOP_AI_PIPELINE_LIVE_MAX_CALLS"])
    except (InvalidOperation, ValueError):
        raise ConfigError("ZOOP_AI_PIPELINE_LIVE_MAX_USD", "pipeline_live_invalid") from None
    if not ceiling.is_finite() or ceiling <= 0:
        raise ConfigError("ZOOP_AI_PIPELINE_LIVE_MAX_USD", "pipeline_live_invalid")
    if calls <= 0:
        raise ConfigError("ZOOP_AI_PIPELINE_LIVE_MAX_CALLS", "pipeline_live_invalid")
    budget = _absolute(environ["ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR"], "ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR")
    roots = [state_dir, *(group.state_dir for group in (relation, extraction) if group is not None)]
    if any(_overlaps(budget, root) for root in roots):
        raise ConfigError("ZOOP_AI_PIPELINE_LIVE_BUDGET_DIR", "pipeline_live_budget_overlaps_state")
    return PipelineLive({name: environ[name] for name in (*PIPELINE_LIVE_PUBLIC_REQUIRED, *PIPELINE_LIVE_PUBLIC_OPTIONAL) if name in environ},
                        {name: environ[name] for name in PIPELINE_LIVE_BUDGET}, {name: environ[name] for name in PIPELINE_LIVE_SECRETS})


def _chat(environ: Mapping[str, str], state_dir: Path, worker_state: Path, *,
          relation: RelationConfig | None, extraction: ExtractionConfig | None, graph: GraphConfig | None,
          handoff: HandoffConfig | None, exposure: HandoffExposureConfig | None) -> ChatConfig | None:
    """All-or-nothing, like the other groups. The chat state root may not exist yet (the child creates its ledger file), but its parent must."""
    if not any(name in environ for name in (*CHAT_VARS, CHAT_REPLAY)):
        return None
    for name in CHAT_VARS:
        if name not in environ:
            raise ConfigError(name, "chat_group_incomplete")
    command = _file(environ["ZOOP_AI_SERVICE_CHAT_COMMAND"], "ZOOP_AI_SERVICE_CHAT_COMMAND", executable=True)
    chat_state = _absolute(environ["ZOOP_AI_CHAT_STATE_DIR"], "ZOOP_AI_CHAT_STATE_DIR")
    roots = {"ZOOP_AI_SERVICE_STATE_DIR": state_dir, "ZOOP_AI_WORKER_STATE_DIR": worker_state, "ZOOP_AI_CHAT_STATE_DIR": chat_state}
    if environ.get("ZOOP_STATE_DIR"):
        roots["ZOOP_STATE_DIR"] = _absolute(environ["ZOOP_STATE_DIR"], "ZOOP_STATE_DIR")
    _disjoint(roots, "chat_roots_overlap")
    # Read-only doors still name operator ledgers: chat must never write into them, even without the ordinary handoff door.
    for group in (relation, extraction, graph, handoff, exposure):
        if group is None:
            continue
        for name in ("state_dir", "relation_state_dir", "extraction_state_dir", "ingestion_state_dir"):
            root = getattr(group, name, None)
            if root is not None and _overlaps(chat_state, root):
                raise ConfigError("ZOOP_AI_CHAT_STATE_DIR", "chat_roots_overlap")
    _prepare_chat_state(chat_state)
    grants_path = _file(environ["ZOOP_AI_SERVICE_CHAT_GRANTS"], "ZOOP_AI_SERVICE_CHAT_GRANTS")
    try:
        registry = json.loads(grants_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ConfigError("ZOOP_AI_SERVICE_CHAT_GRANTS", "not_json") from None
    if not isinstance(registry, dict) or registry.get("schemaVersion") != "zoop-ai-chat-1" or not isinstance(registry.get("grants"), list):
        raise ConfigError("ZOOP_AI_SERVICE_CHAT_GRANTS", "schema_invalid")
    replay = _file(environ[CHAT_REPLAY], CHAT_REPLAY) if environ.get(CHAT_REPLAY) else None
    raw_ceiling = environ.get("ZOOP_AI_CHAT_MAX_CALLS")
    try:
        ceiling = int(raw_ceiling) if raw_ceiling is not None else 0
    except ValueError:
        raise ConfigError("ZOOP_AI_CHAT_MAX_CALLS", "not_integer") from None
    live = environ.get("ZOOP_AI_CHAT_LIVE_ENABLED") == "1" and ceiling > 0
    child = {**CHILD_BASE_ENV}
    for name in CHAT_PUBLIC:
        if name in environ:
            child[name] = environ[name]
    if live:
        for name in (*CHAT_GATE, *CHAT_SECRETS):
            if name in environ:
                child[name] = environ[name]
    return ChatConfig(command, chat_state, grants_path, replay, live, child)


def load(environ: Mapping[str, str]) -> ServiceConfig:
    principals = _principals(environ.get("ZOOP_AI_SERVICE_PRINCIPALS"))
    admission = environ.get("ZOOP_AI_SERVICE_PLAN_ADMISSION")
    root = environ.get("ZOOP_AI_SERVICE_PLAN_ROOT")
    if (admission is not None or root is not None) and (admission != "1" or not root):
        raise ConfigError("ZOOP_AI_SERVICE_PLAN_ADMISSION", "plan_group_incomplete")
    plan_root = _existing_dir(root, "ZOOP_AI_SERVICE_PLAN_ROOT") if admission == "1" else None
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
    extraction_enabled = any(name in environ for name in (*EXTRACTION_OWN, EXTRACTION_TOPIC))
    # The S3 group is on when any variable of its own is set, or (as before this group existed) when only the shared ones are set and the
    # S2 group does not claim them.
    relation_enabled = any(name in environ for name in RELATION_OWN) or (not extraction_enabled and any(name in environ for name in SHARED_VARS))
    relation = _relation(environ, principals, state_dir, worker_state, relation_enabled)
    extraction = _extraction(environ, principals, state_dir, worker_state)
    if plan_root is not None:
        if extraction is None or relation is None:
            raise ConfigError("ZOOP_AI_SERVICE_PLAN_ADMISSION", "plan_execution_groups_required")
        if any(_overlaps(plan_root, p) for p in (state_dir, worker_state, extraction.state_dir, extraction.ingestion_state_dir, relation.state_dir)):
            raise ConfigError("ZOOP_AI_SERVICE_PLAN_ROOT", "plan_roots_overlap")
    graph = _graph(environ, principals, state_dir, worker_state, relation, extraction)
    handoff = _handoff(environ, principals, state_dir, worker_state, relation, extraction, graph)
    pipeline_live = _pipeline_live(environ, state_dir, relation, extraction)
    exposure = _handoff_exposure(environ, principals, state_dir, worker_state, relation, extraction, graph, handoff)
    chat = _chat(environ, state_dir, worker_state, relation=relation, extraction=extraction, graph=graph, handoff=handoff, exposure=exposure)
    return ServiceConfig(principals, state_dir, worker_state, command, grants_path, replay, port, live, child, relation, extraction, graph, handoff,
                         pipeline_live, handoff_exposure=exposure, chat=chat, plan_root=plan_root)
