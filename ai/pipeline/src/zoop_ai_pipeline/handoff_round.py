"""Cumulative round freeze (`zoop-ai-handoff freeze-round`): one explicit command that recomputes the S3 job window from the AI ledgers, narrows the operator's master
files to it and runs the ordinary strict `Handoff.freeze` over the result. One bundle is one inactive app version; its sources are the window, never the previous bundle.

Selection (recomputed at every freeze from the three ledgers, master canonical registry and current delivery authority):
  * candidates: S3 jobs in state `ready` whose S2 upstream (jobId + inputDigest) has at least one master canonical entry and a declared round slot. A `ready` job without
    a mapping is `awaiting_mapping`; a mapped job without a slot is `unavailable` (`round_slot_unavailable`). Neither takes a window slot.
    A job in any other state is `not_ready` (`cancelled` is reported as such);
  * order: the slot (`window.through`) of the S2 incoming observation's ingestion round, newest first, then sourceId, page, ordinal, then the S3 jobId. Historical
    processing-ineligible jobs report `withheld/analysis_contract_changed` and take no slot. Check current delivery until `WINDOW` (= MAX_SOURCES) jobs are selected;
    withheld jobs also take no slot. Remaining eligible candidates are `out_of_window`. An empty deliverable window fails with `window_empty`;
  * own-round gate: every S3 job admitted for the requested round (the jobs whose S2 upstream was observed in that round, plus every unit of the optional plan) must be
    `ready` or `cancelled`, else `analysis_incomplete` and nothing is written. Earlier rounds are never waited for.

Narrowing (mechanical): the handoff's canonical registry and decisions are the master's entries selected byte-for-byte (no entry is created, merged or reworded). The only
text that differs from the master is a shorter `fieldVerdicts` array or a `null` `summary` of an issue entry, each made of unchanged elements. The files are staged privately,
frozen through the unchanged strict path and installed in `--files-dir` only when the handoff is ready.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from .extraction import Store as ExtractionStore
from .extraction_contracts import ExtractionFailure
from .extraction_contracts import Submit as ExtractionSubmit
from .extraction_plan import read_plan
from .graph_projection import Paths as SourcePaths
from .graph_projection import Registry, Source, gate, load_registry, review_state
from .graph_projection_contracts import Withheld
from .handoff import Handoff, HandoffPaths, IgnoredSummaries, LedgerSummaries, Loaded, Operator, Planner, Store, load_operator, load_source
from .handoff_contracts import MAX_OPERATOR_FILE, MAX_SOURCES, SCHEMA, Bindings, Decisions, Manifest
from .ingestion import Store as IngestionStore
from .ingestion_contracts import IngestionFailure, byte_hash, canonical, digest, read_file, timestamp
from .issue_summary_contracts import deterministic_code, summary_basis
from .relation_contracts import Submit as RelationSubmit

WINDOW = MAX_SOURCES
SELECTION_SCHEMA = "zoop-ai-handoff-selection-1"
STATUS_ORDER = ("selected", "withheld", "unavailable", "out_of_window", "awaiting_mapping", "not_ready", "cancelled")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_SPACE = " \t\n\r"
_JSON = json.JSONDecoder()
_PLACEHOLDER = "0" * 64


# ---------------------------------------------------------------------------------------------- ledgers ------------------------------

@dataclass(frozen=True)
class Job:
    """One S3 job of the relation ledger with the S2 observation it analysed. `slot` is the ingestion round's `window.through` (None when that round declared no window)."""
    job_id: str
    input_digest: str
    state: str
    upstream: tuple
    round_id: str
    source_id: str
    page: int
    ordinal: int
    slot: str | None

    def order(self) -> tuple:
        """Newest slot first, then source, page, ordinal ascending, then the S3 job id."""
        when = (timestamp(self.slot) - _EPOCH) // timedelta(microseconds=1)
        return (-when, self.source_id, self.page, self.ordinal, self.job_id)


def _invalid(job_id: str) -> ExtractionFailure:
    return ExtractionFailure("round_selection_invalid", {"jobId": job_id})


def read_jobs(source: Source, extraction: Path, ingestion: Path) -> list[Job]:
    """Every S3 job, read-only: its frozen S2 upstream, that job's incoming observation and the declared slot of the observation's ingestion round."""
    s2, rounds = ExtractionStore(extraction, ingestion, existing=True), IngestionStore(ingestion, existing=True)
    try:
        slots: dict = {}
        jobs = []
        for row in source.store.all("SELECT job_id,input_digest,state,request FROM jobs ORDER BY job_id"):
            try:
                upstream = RelationSubmit.model_validate_json(row["request"]).upstream
                parent = s2.one("SELECT input_digest,request FROM jobs WHERE job_id=?", (upstream.job_id,))
                if parent is None or parent["input_digest"] != upstream.input_digest:
                    raise _invalid(row["job_id"])
                incoming = ExtractionSubmit.model_validate_json(parent["request"]).incoming
                key = (incoming.round_id, incoming.source_id)
                if key not in slots:
                    found = rounds.one("SELECT request FROM rounds WHERE id=? AND source=?", key)
                    window = json.loads(found["request"]).get("window") if found is not None else None
                    slots[key] = window["through"] if window else None
            except (ValidationError, ValueError, KeyError, TypeError):
                raise _invalid(row["job_id"]) from None
            jobs.append(Job(row["job_id"], row["input_digest"], row["state"], (upstream.job_id, upstream.input_digest), incoming.round_id, incoming.source_id,
                            incoming.page, incoming.ordinal, slots[key]))
        return jobs
    finally:
        s2.close()
        rounds.close()


def frozen_jobs(store: Store) -> set:
    """The S3 jobs pinned by any `ready` handoff of this ledger (any bundle contract: the job was delivered to an importer once)."""
    try:
        return {s["relation"]["jobId"] for row in store.db.execute("SELECT manifest FROM handoffs WHERE state='ready'") for s in json.loads(row["manifest"])["sources"]}
    except (ValueError, KeyError, TypeError):
        raise ExtractionFailure("handoff_state_invalid") from None


def plan_units(plan_root: Path, plan_id: str, round_id: str) -> set:
    """The (S2 jobId, inputDigest) of every unit of one immutable plan, which must be the plan of the requested round."""
    manifest = read_plan(plan_root / plan_id)
    try:
        if manifest["planId"] != plan_id or manifest["round"]["roundId"] != round_id:
            raise ExtractionFailure("plan_round_mismatch")
        return {(unit["jobId"], unit["inputDigest"]) for unit in manifest["units"]}
    except (KeyError, TypeError):
        raise ExtractionFailure("plan_input_invalid") from None


# ---------------------------------------------------------------------------------------------- selection ----------------------------

def entry(job: Job | None, status: str, code: str | None = None, **more) -> dict:
    base = {"jobId": job.job_id if job else None, "status": status, "code": code, "roundId": job.round_id if job else None,
            "sourceId": job.source_id if job else None, "slot": job.slot if job else None, "page": job.page if job else None,
            "ordinal": job.ordinal if job else None, "upstreamJobId": job.upstream[0] if job else None}
    return {**base, **more}


def own_round_gate(jobs: list[Job], round_id: str, units: set) -> list[dict]:
    """The S3 jobs admitted for `round_id` that are not done: a job of that round (by its S2 observation) still not `ready`/`cancelled`, or a plan unit without any S3 job."""
    by_upstream: dict = {}
    for job in jobs:
        by_upstream.setdefault(job.upstream, []).append(job)
    admitted = units | {job.upstream for job in jobs if job.round_id == round_id}
    blocking = []
    for upstream in sorted(admitted):
        found = by_upstream.get(upstream, [])
        if not found:
            blocking.append({"jobId": None, "upstreamJobId": upstream[0], "code": "relation_job_missing"})
        blocking.extend({"jobId": job.job_id, "upstreamJobId": upstream[0], "code": job.state} for job in found if job.state not in ("ready", "cancelled"))
    return blocking


def classify(jobs: list[Job], mapped: set) -> tuple[list[Job], list[dict]]:
    """Ordered candidates for delivery checks, plus one report entry for each job excluded by state, mapping or missing slot."""
    report, candidates = [], []
    for job in jobs:
        if job.state == "cancelled":
            report.append(entry(job, "cancelled", "cancelled"))
        elif job.state != "ready":
            report.append(entry(job, "not_ready", job.state))
        elif job.upstream not in mapped:
            report.append(entry(job, "awaiting_mapping", "canonical_mapping_missing"))
        elif job.slot is None:
            report.append(entry(job, "unavailable", "round_slot_unavailable"))
        else:
            candidates.append(job)
    candidates.sort(key=Job.order)
    return candidates, report


def report_order(report: list[dict]) -> list[dict]:
    """Grouped by status (`STATUS_ORDER`); inside a group the window order for candidates and the ledger's job-id order for the rest (the sort is stable)."""
    return sorted(report, key=lambda item: STATUS_ORDER.index(item["status"]))


# ---------------------------------------------------------------------------------------------- narrowing -------------------------------

def _end() -> ValueError:
    return ValueError("json shape")


def _skip(text: str, i: int) -> int:
    while i < len(text) and text[i] in _SPACE:
        i += 1
    return i


def _members(text: str, opener: str, closer: str, keyed: bool) -> list:
    """The members of one JSON object (`(key, raw value)`) or array (`raw element`) as the exact source text, in file order. Strict: one top-level value, unique keys."""
    try:
        i = _skip(text, 0)
        if text[i] != opener:
            raise _end()
        i = _skip(text, i + 1)
        found, seen = [], set()
        if text[i] == closer:
            i += 1
        else:
            while True:
                key = None
                if keyed:
                    key, i = _JSON.raw_decode(text, i)
                    i = _skip(text, i)
                    if not isinstance(key, str) or key in seen or text[i] != ":":
                        raise _end()
                    seen.add(key)
                    i = _skip(text, i + 1)
                start = i
                _, i = _JSON.raw_decode(text, i)
                found.append((key, text[start:i]) if keyed else text[start:i])
                i = _skip(text, i)
                if text[i] == ",":
                    i = _skip(text, i + 1)
                elif text[i] == closer:
                    i += 1
                    break
                else:
                    raise _end()
        if _skip(text, i) != len(text):
            raise _end()
        return found
    except (IndexError, json.JSONDecodeError):
        raise _end() from None


def split_object(text: str) -> list[tuple[str, str]]:
    return _members(text, "{", "}", True)


def split_array(text: str) -> list[str]:
    return _members(text, "[", "]", False)


def join_object(members: list[tuple[str, str]]) -> str:
    return "{" + ",".join(f"{json.dumps(key, ensure_ascii=False)}:{raw}" for key, raw in members) + "}"


def join_array(elements: list[str]) -> str:
    return "[" + ",".join(elements) + "]"


def narrow_registry(raw: bytes, upstreams: set) -> tuple[bytes, int]:
    """The master registry with exactly the entries of the given S2 upstreams, each entry's own text unchanged; and how many were kept."""
    members, kept = split_object(raw.decode("utf-8")), []
    for n, (key, value) in enumerate(members):
        if key == "entries":
            kept = [text for text in split_array(value) if (json.loads(text)["upstream"]["jobId"], json.loads(text)["upstream"]["inputDigest"]) in upstreams]
            members[n] = (key, join_array(kept))
    return join_object(members).encode("utf-8"), len(kept)


def _spans(text: str, keep) -> tuple[list[str], int]:
    """The elements of a JSON array that `keep` (given the parsed element) accepts, and how many were dropped."""
    elements = split_array(text)
    kept = [element for element in elements if keep(json.loads(element))]
    return kept, len(elements) - len(kept)


@dataclass
class Narrowed:
    raw: bytes
    issues: list
    dropped_issues: list
    verdicts_dropped: int


def narrow_decisions(raw: bytes, mentions: dict, documents: set) -> Narrowed:
    """The master decisions limited to the window. `mentions` maps each canonical issue id that has members in the window to the original mention identities
    (documentId, documentVersion, mentionId) its in-window members carry; `documents` are the document versions the window's S2 jobs bound.

    Kept: every company; issues with at least one in-window member (their `fieldVerdicts` limited to in-window mentions); structural decisions of a kept issue; FOLLOWS decisions
    whose two issues are both kept; origins of in-window documents. Everything kept is the master's own text."""
    members, issues, dropped, verdicts = split_object(raw.decode("utf-8")), [], [], 0
    for n, (key, value) in enumerate(members):
        if key == "issues":
            kept = []
            for text in split_array(value):
                decision = json.loads(text)
                identities = mentions.get(decision["canonicalId"])
                if identities is None:
                    dropped.append(decision["canonicalId"])
                    continue
                issues.append(decision["canonicalId"])
                fields = split_object(text)
                held = split_array(dict(fields)["fieldVerdicts"])
                survivors = [e for e in held if tuple(json.loads(e)[k] for k in ("documentId", "documentVersion", "mentionId")) in identities]
                if len(survivors) != len(held):
                    verdicts += len(held) - len(survivors)
                    text = join_object([(k, join_array(survivors) if k == "fieldVerdicts" else v) for k, v in fields])
                kept.append(text)
            members[n] = (key, join_array(kept))
    kept_issues = set(issues)
    for n, (key, value) in enumerate(members):
        if key == "structural":
            members[n] = (key, join_array(_spans(value, lambda d: d["issue"] in kept_issues)[0]))
        elif key == "follows":
            members[n] = (key, join_array(_spans(value, lambda d: d["from"] in kept_issues and d["to"] in kept_issues)[0]))
        elif key == "origins":
            members[n] = (key, join_array(_spans(value, lambda d: (d["documentId"], d["documentVersion"]) in documents)[0]))
    return Narrowed(join_object(members).encode("utf-8"), sorted(kept_issues), sorted(dropped), verdicts)


def drop_summary_pins(raw: bytes, public_ids: set) -> bytes:
    """The decisions with the `summary` pin of the given public issue ids replaced by `null` (the unpinned state); every other byte of every entry is unchanged."""
    members = split_object(raw.decode("utf-8"))
    for n, (key, value) in enumerate(members):
        if key == "issues":
            rewritten = []
            for text in split_array(value):
                if json.loads(text)["publicId"] in public_ids:
                    text = join_object([(k, "null" if k == "summary" else v) for k, v in split_object(text)])
                rewritten.append(text)
            members[n] = (key, join_array(rewritten))
    return join_object(members).encode("utf-8")


def stale_pins(decisions: Decisions, bundle: dict, summaries: LedgerSummaries | None) -> dict:
    """public issue id -> why its summary pin cannot be frozen with this window: the issue is not published, a deterministic rule (`temporal-review-pending`,
    `input-too-large`) decides its summary, or the summarised basis changed. Any other disagreement (a wrong pin, another mode) is left for the strict freeze to refuse."""
    published = {issue["id"]: issue for issue in bundle["issues"]}
    evidence = {e["id"]: e for e in bundle["evidence"]}
    articles = {(a["articleId"], a["articleVersion"]): a for a in bundle["articles"]}
    execution = (bundle["provenance"]["executionMode"], bundle["provenance"]["recordingKind"])
    stale = {}
    for decision in decisions.issues:
        if decision.summary is None:
            continue
        issue = published.get(decision.public_id)
        if issue is None:
            stale[decision.public_id] = "issue_not_public"
            continue
        basis = summary_basis(issue, evidence, articles)
        code = deterministic_code(issue, basis)
        if code is not None:
            stale[decision.public_id] = code
        elif summaries is not None:
            try:
                summaries.result(issue, basis, decision.summary, execution, bundle["provenance"]["observedSourceKind"])
            except ExtractionFailure as exc:
                if exc.code != "issue_summary_basis_changed":
                    raise
                stale[decision.public_id] = exc.code
    return stale


# ---------------------------------------------------------------------------------------------- the command ----------------------------

@dataclass(frozen=True)
class RoundPaths:
    relation: Path
    extraction: Path
    ingestion: Path
    sources: Path
    canonical: Path           # the operator's MASTER registry (read only)
    decisions: Path           # the operator's MASTER decisions (read only)
    bindings: Path
    files_dir: Path           # where the narrowed canonical.json / decisions.json of the handoff are installed (what export reads)
    plan_root: Path | None = None
    summaries: Path | None = None


def _staging() -> tempfile.TemporaryDirectory:
    """A private 0700 scratch directory under the REAL temporary root (the operator-file reader refuses every symlink component, and `/tmp` is one on macOS)."""
    return tempfile.TemporaryDirectory(prefix="zoop-handoff-round-", dir=os.path.realpath(tempfile.gettempdir()))


def _install(directory: Path, name: str, raw: bytes) -> None:
    """The handoff's operator file, replaced atomically (a reader sees the old or the new bytes, never a mixture)."""
    target = directory / name
    if os.path.lexists(target) and (target.is_symlink() or not target.is_file()):
        raise ExtractionFailure("state_namespace_conflict")
    if target.is_file() and target.read_bytes() == raw:
        return
    temporary = directory / f".tmp-{uuid.uuid4().hex}"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view, written = memoryview(raw), 0
        while written < len(raw):
            written += os.write(fd, view[written:])
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(temporary, target)
    dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def check_files_dir(directory: Path, state: Path, canonical_path: Path, decisions_path: Path) -> Path:
    """Validate both install targets against the state and master paths before opening writable state or staging files."""
    directory, state = Path(os.path.abspath(directory)), Path(os.path.abspath(state))
    masters = (Path(os.path.abspath(canonical_path)), Path(os.path.abspath(decisions_path)))
    if directory == state or directory.is_relative_to(state) or state.is_relative_to(directory):
        raise ExtractionFailure("state_namespace_conflict")
    for parent in [*reversed(directory.parents), directory]:
        if parent.is_symlink():
            raise ExtractionFailure("state_namespace_invalid")
        if parent.exists() and not parent.is_dir():
            raise ExtractionFailure("state_namespace_conflict")
    for name in ("canonical.json", "decisions.json"):
        target = directory / name
        if os.path.lexists(target) and (target.is_symlink() or not target.is_file()):
            raise ExtractionFailure("state_namespace_conflict")
        if any(target == master or (target.exists() and master.exists() and target.samefile(master)) for master in masters):
            raise ExtractionFailure("state_namespace_conflict")
    return directory


def read_master(paths: RoundPaths) -> tuple[Registry, bytes, Decisions]:
    registry = load_registry(paths.canonical)
    try:
        raw = read_file(paths.decisions, MAX_OPERATOR_FILE)
        return registry, raw, Decisions.model_validate_json(raw)
    except (IngestionFailure, OSError, ValueError):
        raise ExtractionFailure("decisions_invalid") from None


def bindings_hash(path: Path) -> str:
    try:
        raw = read_file(path, MAX_OPERATOR_FILE)
        Bindings.model_validate_json(raw)
        return byte_hash(raw)
    except (IngestionFailure, OSError, ValueError):
        raise ExtractionFailure("bindings_invalid") from None


def _select_window(source: Source, paths: RoundPaths, registry: Registry, round_id: str, plan_id: str | None):
    """Read-only selection shared by pre-writer admission and the locked freeze."""
    units = plan_units(paths.plan_root, plan_id, round_id) if plan_id else set()
    jobs = read_jobs(source, paths.extraction, paths.ingestion)
    blocking = own_round_gate(jobs, round_id, units)
    if blocking:
        raise ExtractionFailure("analysis_incomplete", {"roundId": round_id, "jobs": blocking})
    mapped = {(job_id, input_digest) for job_id, input_digest, _, _ in registry.entries}
    candidates, report = classify(jobs, mapped)
    selection = {"schemaVersion": SELECTION_SCHEMA, "roundId": round_id, "planId": plan_id, "limit": WINDOW}
    window, pins, kinds = [], [], []
    for job in candidates:
        try:
            source.require_current_analysis(job.job_id)
        except ExtractionFailure as exc:
            report.append(entry(job, "withheld", exc.code))
            continue
        if len(window) == WINDOW:
            report.append(entry(job, "out_of_window", "window_full"))
            continue
        relation = {"jobId": job.job_id, "inputDigest": job.input_digest}
        try:
            result = gate(source, relation, None)
        except Withheld as exc:
            report.append(entry(job, "withheld", exc.code))
            continue
        window.append(job)
        report.append(entry(job, "selected"))
        kinds.append(result["provenance"]["sourceKind"])
        pins.append({"relation": relation, "upstream": result["binding"]["upstream"], "reviewDigest": digest(review_state(result))})
    selection["jobs"] = report_order(report)
    if not window:
        raise ExtractionFailure("window_empty", {"selection": selection})
    return window, pins, kinds, selection


def preflight_round(paths: RoundPaths, round_id: str, plan_id: str | None) -> None:
    """Require a current-eligible deliverable window before any handoff writer or staging."""
    registry, _, _ = read_master(paths)
    bindings_hash(paths.bindings)
    source_paths = SourcePaths(paths.relation, paths.extraction, paths.ingestion, paths.sources, paths.canonical)
    with Source(source_paths) as source:
        _select_window(source, paths, registry, round_id, plan_id)


def freeze_round(store: Store, paths: RoundPaths, round_id: str, plan_id: str | None, recovery_attempt_id: str | None = None) -> dict:
    """Select, narrow and freeze; install only ready results. An explicit recovery attempt selects a separate deterministic handoff identity."""
    files_dir = check_files_dir(paths.files_dir, store.root, paths.canonical, paths.decisions)
    registry, decisions_raw, decisions = read_master(paths)
    bindings = bindings_hash(paths.bindings)
    source_paths = SourcePaths(paths.relation, paths.extraction, paths.ingestion, paths.sources, paths.canonical)
    with Source(source_paths) as source:
        window, pins, kinds, selection = _select_window(source, paths, registry, round_id, plan_id)
        previously_frozen = frozen_jobs(store)
        for item in selection["jobs"]:
            if item["status"] == "out_of_window":
                item["neverFrozen"] = item["jobId"] not in previously_frozen
        with _staging() as stage_name:
            stage = Path(stage_name)
            upstreams = {job.upstream for job in window}
            canonical_raw, kept = narrow_registry(registry.raw, upstreams)
            (stage / "canonical.json").write_bytes(canonical_raw)
            probe = HandoffPaths(paths.relation, paths.extraction, paths.ingestion, paths.sources, stage / "canonical.json", stage / "decisions.json", paths.bindings)
            (stage / "decisions.json").write_bytes(decisions_raw)
            files = {"canonical": byte_hash(canonical_raw), "decisions": _PLACEHOLDER, "bindings": bindings}
            provisional = Manifest.model_validate_json(canonical({"schemaVersion": SCHEMA, "handoffId": "round-probe", "sourceKind": kinds[0],
                                                                  "policyVersion": decisions.policy_version, "sources": pins, "files": files}))
            contexts = probe.contexts()
            readers = {contexts.routes[0].context_id: source}
            loaded: list[Loaded] = [load_source(readers, contexts, provisional, pin, strict=True)
                                    for pin in sorted(provisional.sources, key=lambda p: p.relation.job_id)]
            operator = load_operator(probe)
            groups = Planner(provisional, "round-probe", _PLACEHOLDER, loaded, operator).groups()
            mentions = {canonical_id: {(m.doc[0], m.doc[1], m.mention_id) for m in members} for canonical_id, members in groups.items()}
            narrowed = narrow_decisions(decisions_raw, mentions, {key for item in loaded for key in item.docs})
            decisions_final, dropped_pins = narrowed.raw, {}
            if any(d.summary is not None for d in Decisions.model_validate_json(narrowed.raw).issues):
                (stage / "decisions.json").write_bytes(narrowed.raw)
                narrowed_decisions = Decisions.model_validate_json(narrowed.raw)
                dry = Planner(provisional, "round-probe", _PLACEHOLDER, loaded,
                              Operator(operator.registry, narrowed_decisions, narrowed.raw, operator.bindings, operator.bindings_raw), IgnoredSummaries()).run()
                ledger = LedgerSummaries(paths.summaries, paths.relation, paths.extraction, paths.ingestion, store.root) if paths.summaries else None
                dropped_pins = stale_pins(narrowed_decisions, dry, ledger)
                decisions_final = drop_summary_pins(narrowed.raw, set(dropped_pins))

    final = Decisions.model_validate_json(decisions_final)
    files = {"canonical": byte_hash(canonical_raw), "decisions": byte_hash(decisions_final), "bindings": bindings}
    body = {"schemaVersion": SCHEMA, "sourceKind": kinds[0], "policyVersion": decisions.policy_version,
            "sources": sorted(pins, key=lambda p: p["relation"]["jobId"]), "files": files}
    identity = body if recovery_attempt_id is None else {**body, "recoveryAttemptId": recovery_attempt_id}
    manifest = Manifest.model_validate_json(canonical({**body, "handoffId": "hr-" + digest(identity)}))
    pinned = any(d.summary is not None for d in final.issues)
    with _staging() as stage_name:
        stage = Path(stage_name)
        (stage / "canonical.json").write_bytes(canonical_raw)
        (stage / "decisions.json").write_bytes(decisions_final)
        hp = HandoffPaths(paths.relation, paths.extraction, paths.ingestion, paths.sources, stage / "canonical.json", stage / "decisions.json", paths.bindings,
                          summaries=paths.summaries if pinned else None)
        frozen = Handoff(store, hp).freeze(manifest)
    if frozen["state"] == "ready":
        files_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        _install(files_dir, "canonical.json", canonical_raw)
        _install(files_dir, "decisions.json", decisions_final)
    return {"schemaVersion": SCHEMA, "roundId": round_id, "handoffId": manifest.handoff_id, "freeze": frozen, "selection": selection, "files": files,
            "narrowing": {"registryEntries": kept, "issuesKept": narrowed.issues, "issuesDropped": narrowed.dropped_issues, "fieldVerdictsDropped": narrowed.verdicts_dropped,
                          "summaryPinsDropped": [{"issueId": k, "code": v} for k, v in sorted(dropped_pins.items())]}}
