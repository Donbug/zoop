"""Durable finite-set queue for official protocols. Never a native HTTP receipt.

The original response/container, extraction proof and derived UTF-8 body are separate
immutable files. Missing credentials/contact are prerequisites, not failed adapters.
A resource stop keeps unattempted tasks; a new pinned successor imports settled work
without re-fetching it. An interrupted request is never automatically retried.
"""
from __future__ import annotations

import base64
import fcntl
import json
import os
import stat
import time
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from . import official_source_adapters as adapters
from .ingestion_contracts import IngestionFailure, Wire, byte_hash, canonical, digest, now, reserved_state_roots
from .private_intake import _directory, _json, _publish, _read

RESOURCE_STOPS = {"request_budget", "byte_budget", "timeout", "rate_limit"}
USE = {"rights": "unconfirmed", "modelSend": False, "publicUse": False,
       "usage": "private-local-experiment-only; no redistribution or external model transmission"}


class Predecessor(Wire):
    state_dir: str
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class OfficialConfig(Wire):
    schema_version: Literal["zoop-official-source-config-1"]
    plan_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
    state_dir: str
    source_id: Literal["fsc-press", "federal-register-bis", "opendart", "sec-edgar"]
    from_day: str
    through_day: str
    operator_approval_ref: str = Field(min_length=1, max_length=1000)
    policy: adapters.OfficialPolicy
    tickers: list[str] = Field(default_factory=list)
    ciks: list[str] = Field(default_factory=list)
    sec_company: str | None = None
    sec_contact: str | None = None
    synthetic_base_url: str | None = None
    predecessor: Predecessor | None = None

    @model_validator(mode="after")
    def checked(self):
        path = Path(self.state_dir)
        if not path.is_absolute() or str(path) != os.path.abspath(path):
            raise ValueError("absolute canonical stateDir required")
        if any(path == root or path.is_relative_to(root) or root.is_relative_to(path) for root in reserved_state_roots()):
            raise ValueError("reserved state namespace")
        if bool(self.synthetic_base_url) != self.policy.synthetic_loopback:
            raise ValueError("explicit synthetic policy and origin required together")
        if not self.policy.synthetic_loopback and self.policy.min_interval_seconds < 0.1:
            raise ValueError("public official requests must be paced at most ten per second")
        if self.predecessor is not None:
            previous = Path(self.predecessor.state_dir)
            if (not previous.is_absolute() or str(previous) != os.path.abspath(previous) or previous == path or
                    previous.is_relative_to(path) or path.is_relative_to(previous)):
                raise ValueError("distinct canonical predecessor namespace required")
        adapters.plan(self.source_id, self.from_day, self.through_day, tickers=tuple(self.tickers), ciks=tuple(self.ciks),
                      synthetic_origin=self.synthetic_base_url)
        return self


def load_config(path):
    target = Path(os.path.abspath(path))
    fd = _directory(target.parent)
    try:
        return OfficialConfig.model_validate(_json(_read(fd, target.name)))
    finally:
        os.close(fd)


def _binding(config):
    return config.model_dump(mode="json", by_alias=True)


def _identity(config):
    values = _binding(config)
    for key in ("planId", "stateDir", "predecessor"):
        values.pop(key)
    for key in ("maxRequests", "maxTotalBytes", "maxTotalSeconds"):
        values["policy"].pop(key)
    return values


def _record_id(config, task):
    return "official-source-" + digest([config.plan_id, config.source_id, task.context["candidateId"], task.url])


def _entry(task, status="pending"):
    return {"task": asdict(task), "status": status, "code": None}


class State:
    def __init__(self, config, command):
        self.config, self.fd, self.lock = config, None, None
        root = Path(config.state_dir)
        if command != "status":
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.fd = _directory(root)
        try:
            info = os.fstat(self.fd)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise IngestionFailure("official_state_permissions")
            flags = os.O_RDONLY if command == "status" else os.O_CREAT | os.O_RDWR
            self.lock = os.open(".lock", flags | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            try:
                fcntl.flock(self.lock, (fcntl.LOCK_SH if command == "status" else fcntl.LOCK_EX) | fcntl.LOCK_NB)
            except BlockingIOError:
                raise IngestionFailure("official_state_busy") from None
            try:
                retained_plan = _read(self.fd, "PLAN.json")
            except FileNotFoundError:
                if command == "status":
                    raise IngestionFailure("official_state_missing") from None
                with os.scandir(self.fd) as entries:
                    if any(entry.name != ".lock" for entry in entries):
                        raise IngestionFailure("official_state_conflict")
                _publish(self.fd, "PLAN.json", canonical(_binding(config)).encode(), immutable=True)
                initial = adapters.plan(config.source_id, config.from_day, config.through_day,
                    tickers=tuple(config.tickers), ciks=tuple(config.ciks), synthetic_origin=config.synthetic_base_url)
                self.data = {"schemaVersion": "zoop-official-source-state-1", "planDigest": digest(_binding(config)),
                    "tasks": {task.key: _entry(task) for task in initial.tasks}, "candidates": {}, "records": {},
                    "requests": 0, "bytes": 0, "unknownRequests": 0, "unknownByteUpperBound": 0,
                    "pendingRequest": None, "stopCode": None, "startedAt": now(), "inheritedRecords": [],
                    "inheritedRequests": 0, "inheritedBytes": 0, "prerequisites": [], "responses": {},
                    "blocked": [], "delays": {}, "nextAllowedAt": {}}
                if config.predecessor is not None:
                    self.inherit()
                self.save()
            else:
                if _json(retained_plan) != _binding(config):
                    raise IngestionFailure("official_plan_conflict")
                wrapper = _json(_read(self.fd, "STATE.json"))
                self.data = wrapper["state"]
                if wrapper["sha256"] != digest(self.data) or self.data["planDigest"] != digest(_binding(config)):
                    raise IngestionFailure("official_state_corrupt")
            for key, item in self.data["tasks"].items():
                task = adapters.OfficialTask(**item["task"])
                if key != task.key or task.source_id != config.source_id:
                    raise IngestionFailure("official_state_corrupt")
                adapters.validate_task(task, synthetic_origin=config.synthetic_base_url)
        except BaseException:
            self.close()
            raise

    def inherit(self):
        previous = self.config.predecessor
        fd = _directory(previous.state_dir)
        lock = None
        try:
            lock = os.open(".lock", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                raise IngestionFailure("official_predecessor_busy") from None
            plan_raw, state_raw = _read(fd, "PLAN.json"), _read(fd, "STATE.json")
            if byte_hash(plan_raw) != previous.plan_sha256 or byte_hash(state_raw) != previous.state_sha256:
                raise IngestionFailure("official_predecessor_pin_mismatch")
            before_config = OfficialConfig.model_validate(_json(plan_raw))
            wrapper = _json(state_raw)
            before = wrapper["state"]
            if wrapper["sha256"] != digest(before) or before["planDigest"] != digest(_binding(before_config)):
                raise IngestionFailure("official_predecessor_corrupt")
            if (_identity(before_config) != _identity(self.config) or before["pendingRequest"] is not None or
                    any(item["status"] in {"attempting", "unknown"} for item in before["tasks"].values()) or
                    before["unknownRequests"] or before["stopCode"] not in RESOURCE_STOPS):
                raise IngestionFailure("official_predecessor_not_continuable")
            self.data["tasks"] = before["tasks"]
            self.data["candidates"] = before["candidates"]
            self.data["inheritedRecords"] = before["inheritedRecords"] + list(before["records"].values())
            self.data["inheritedRequests"] = before["inheritedRequests"] + before["requests"]
            self.data["inheritedBytes"] = before["inheritedBytes"] + before["bytes"]
            for field in ("responses", "blocked", "delays", "nextAllowedAt"):
                self.data[field] = before[field]
        finally:
            if lock is not None:
                os.close(lock)
            os.close(fd)

    def save(self):
        _publish(self.fd, "STATE.json", canonical({"state": self.data, "sha256": digest(self.data)}).encode())

    def close(self):
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class TrackedFetcher(adapters.OfficialFetcher):
    def __init__(self, config, state):
        super().__init__(config.policy, config.source_id, synthetic_origin=config.synthetic_base_url,
                         sec_company=config.sec_company, sec_contact=config.sec_contact)
        self.state = state
        self.requests = state.data["requests"]
        self.downloaded = state.data["bytes"]
        self._blocked = set(state.data["blocked"])
        self._delay = dict(state.data["delays"])
        for host, instant in state.data["nextAllowedAt"].items():
            self._last[host] = time.monotonic() + max(0, instant - time.time()) - max(
                self.policy.min_interval_seconds, self._delay.get(host, 0))

    def _get(self, url, host, deadline, limit):
        # Before reservation, mirror deterministic no-send budget checks. The base
        # transport still checks them again immediately before opening a connection.
        if self.requests >= self.policy.max_requests:
            raise IngestionFailure("request_budget")
        if self.downloaded >= self.policy.max_total_bytes:
            raise IngestionFailure("byte_budget")
        self._remaining(deadline)
        self.state.data["pendingRequest"] = {"startedAt": now(), "byteUpperBound": min(limit, self.policy.max_total_bytes - self.downloaded)}
        self.state.save()
        try:
            result = super()._get(url, host, deadline, limit)
        except Exception:
            self.settle(host)
            raise
        # BaseException/kill deliberately leaves the reservation durable.
        self.settle(host)
        return result

    def settle(self, host):
        self.state.data["requests"], self.state.data["bytes"] = self.requests, self.downloaded
        self.state.data["pendingRequest"] = None
        self.state.data["blocked"] = sorted(self._blocked)
        self.state.data["delays"] = dict(self._delay)
        delay = max(self.policy.min_interval_seconds, self._delay.get(host, 0))
        self.state.data["nextAllowedAt"][host] = time.time() + max(0, self._last.get(host, 0) + delay - time.monotonic())
        self.state.save()


def _prerequisites(config, runtime_key):
    needs = []
    if config.source_id == "opendart" and runtime_key is None:
        needs.append("runtime OPENDART_API_KEY required; no credential read or request performed")
    if config.source_id == "sec-edgar":
        if not config.sec_company or not config.sec_contact:
            needs.append("operator-declared SEC company/contact User-Agent required")
        if not config.ciks:
            needs.append("operator-selected actual CIK identifiers required")
    return needs


def _retain(config, state, task, result):
    private_id = _record_id(config, task)
    body_raw = result.prepared["text"].encode("utf-8")
    extraction = result.extraction()
    extraction["task"] = asdict(task)
    extraction["syntheticOrigin"] = config.synthetic_base_url
    parent = state.data["responses"][task.context["discoverySha256"]]
    fd = _directory(parent["stateDir"])
    try:
        proof_raw = _read(fd, "response-" + parent["taskKey"] + ".raw")
        proof_meta = _json(_read(fd, "response-" + parent["taskKey"] + ".json"))
    finally:
        os.close(fd)
    if byte_hash(proof_raw) != task.context["discoverySha256"]:
        raise IngestionFailure("official_discovery_proof_mismatch")
    extraction["discoveryProof"] = {"task": proof_meta["task"], "response": proof_meta["response"],
                                    "rawBase64": base64.b64encode(proof_raw).decode("ascii")}
    extraction_raw = canonical(extraction).encode()
    publication = task.context["publication"]
    record = {"schemaVersion": "zoop-official-source-record-1", "privateId": private_id,
        "planId": config.plan_id, "planDigest": digest(_binding(config)), "source": config.source_id,
        "provenance": "synthetic-official-loopback" if config.policy.synthetic_loopback else "official-public-api",
        "requestUrl": result.response.request_url, "finalUrl": result.response.final_url,
        "originalUrl": _issued_candidate(extraction["discoveryProof"], task, config.synthetic_base_url).url,
        "observedAt": result.response.observed_at, "candidateId": task.context["candidateId"],
        "title": task.context.get("title"), "publisher": None, "publication": publication,
        "publicationDay": publication["day"], "rawSha256": result.response.raw_sha256,
        "rawBytes": result.response.raw_bytes, "textSha256": byte_hash(body_raw), "prepared": result.prepared,
        "parserProfile": adapters.PROFILE, "task": asdict(task),
        "extractionArtifact": {"file": private_id + ".extraction.json", "sha256": byte_hash(extraction_raw)},
        "bodyArtifact": {"file": private_id + ".body.md", "sha256": byte_hash(body_raw), "mediaType": "text/markdown", "bytes": len(body_raw)},
        "extractionBackend": "official-source", "representation": result.response.media_type, **USE}
    verify_record(record, result.raw, extraction_raw=extraction_raw, body_raw=body_raw)
    # Publish originals first. State only names a complete verified record set.
    for suffix, content in ((".raw", result.raw), (".body.md", body_raw), (".extraction.json", extraction_raw),
                            (".json", canonical(record).encode())):
        _publish(state.fd, private_id + suffix, content, immutable=True)
    state.data["records"][private_id] = {"sourceId": config.source_id, "stateDir": config.state_dir,
        "recordPath": str(Path(config.state_dir) / (private_id + ".json")), "recordSha256": digest(record),
        "privateId": private_id, "planId": config.plan_id}


def _issued_candidate(proof, task, synthetic):
    raw = base64.b64decode(proof["rawBase64"], validate=True)
    response = proof["response"]
    if (byte_hash(raw) != task.context["discoverySha256"] or response["raw_sha256"] != byte_hash(raw) or
            response["source_id"] != task.source_id):
        raise IngestionFailure("official_discovery_proof_mismatch")
    previous = adapters.OfficialTask(**proof["task"])
    fetched = adapters.Fetched(response["request_url"], response["final_url"], 200, response["media_type"],
        response["media_type"], raw, {}, [], response["robots"], 0, response["observed_at"])
    result = adapters.parse_response(previous, fetched, synthetic_origin=synthetic)
    matches = [candidate for candidate in result.candidates if candidate.body_task == task]
    if len(matches) != 1:
        raise IngestionFailure("official_discovery_proof_mismatch")
    return matches[0]


def verify_record(record: dict, raw: bytes, *, extraction_raw: bytes, body_raw: bytes) -> dict:
    """Verify original container separately from exact derived UTF-8 ingestion body."""
    try:
        if record["schemaVersion"] != "zoop-official-source-record-1" or any(record[key] != value for key, value in USE.items()):
            raise ValueError
        identifier = record["privateId"]
        task = adapters.OfficialTask(**record["task"])
        if (identifier != "official-source-" + digest([record["planId"], record["source"], record["candidateId"], task.url]) or
                record["source"] != task.source_id or record["candidateId"] != task.context["candidateId"] or
                record["rawSha256"] != byte_hash(raw) or record["rawBytes"] != len(raw) or
                record["textSha256"] != byte_hash(body_raw) or record["prepared"]["text"].encode("utf-8") != body_raw or
                record["bodyArtifact"] != {"file": identifier + ".body.md", "sha256": byte_hash(body_raw),
                                           "mediaType": "text/markdown", "bytes": len(body_raw)} or
                record["extractionArtifact"] != {"file": identifier + ".extraction.json", "sha256": byte_hash(extraction_raw)}):
            raise ValueError
        envelope = _json(extraction_raw)
        if envelope["task"] != record["task"]:
            raise ValueError
        synthetic = envelope["syntheticOrigin"]
        core = {key: value for key, value in envelope.items() if key not in {"task", "syntheticOrigin", "discoveryProof"}}
        candidate = _issued_candidate(envelope["discoveryProof"], task, synthetic)
        if record["originalUrl"] != candidate.url:
            raise ValueError
        prepared = adapters.verify_extraction(core, raw, task, synthetic_origin=synthetic)
        response = core["response"]
        if (prepared != record["prepared"] or core["normalizationProfile"] != record["parserProfile"] or
                record["extractionBackend"] != "official-source" or record["representation"] != response["media_type"] or
                record["requestUrl"] != response["request_url"] or record["finalUrl"] != response["final_url"] or
                record["observedAt"] != response["observed_at"] or record["publisher"] is not None or
                record["publication"] != task.context["publication"] or
                record["publicationDay"] != record["publication"]["day"] or
                not task.from_day <= record["publicationDay"] <= task.through_day or
                record["title"] != task.context.get("title") or
                record["provenance"] != ("synthetic-official-loopback" if synthetic else "official-public-api")):
            raise ValueError
        return record
    except (KeyError, ValueError, TypeError, AttributeError, UnicodeError):
        raise IngestionFailure("official_record_corrupt") from None


def summary(config, state):
    data = state.data
    pending = sum(item["status"] == "pending" for item in data["tasks"].values())
    unknown = data["unknownRequests"] or any(item["status"] in {"attempting", "unknown"} for item in data["tasks"].values())
    refused = sum(item["status"] == "refused" for item in data["tasks"].values())
    artifacts = 0
    with os.scandir(state.fd) as entries:
        for entry in entries:
            info = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise IngestionFailure("official_state_permissions")
            artifacts += info.st_size
    return {"schemaVersion": "zoop-official-source-summary-1", "planDigest": data["planDigest"],
        "sourceId": config.source_id, "state": "prerequisite" if data["prerequisites"] else "partial" if pending or unknown or refused else "completed",
        "sourceRequests": data["requests"], "sourceBytes": data["bytes"], "unknownRequests": data["unknownRequests"],
        "unknownByteUpperBound": data["unknownByteUpperBound"], "retainedInWindow": len(data["records"]),
        "inheritedRetainedInWindow": len(data["inheritedRecords"]), "currentDiscoveredCandidates": len(data["candidates"]),
        "pendingCandidates": pending, "refusedTasks": refused, "stopCode": data["stopCode"],
        "prerequisites": data["prerequisites"], "continuationEligible": bool(pending and not unknown and data["stopCode"] in RESOURCE_STOPS),
        "coverage": "configured API window only; not whole publisher or filing-attachment coverage",
        "artifactBytes": artifacts, "discoveredCorpusExhausted": not (pending or unknown or refused or data["prerequisites"]), **USE}


def run(config, command="run", *, runtime_key=None):
    if command not in {"run", "resume", "status"}:
        raise IngestionFailure("official_command_invalid")
    state = State(config, command)
    try:
        if command == "status":
            return summary(config, state)
        if command == "run" and (state.data["requests"] or state.data["records"] or state.data["pendingRequest"]):
            raise IngestionFailure("official_explicit_resume_required")
        if state.data["pendingRequest"] is not None:
            state.data["unknownRequests"] += 1
            state.data["unknownByteUpperBound"] += state.data["pendingRequest"]["byteUpperBound"]
            state.data["pendingRequest"] = None
        for item in state.data["tasks"].values():
            if item["status"] == "attempting":
                item.update(status="unknown", code="interrupted_task_no_retry")
        state.data["prerequisites"] = _prerequisites(config, runtime_key)
        if state.data["prerequisites"] or state.data["unknownRequests"]:
            state.save()
            return summary(config, state)
        if state.data["stopCode"] is not None:
            state.save()
            return summary(config, state)
        client = TrackedFetcher(config, state)
        while True:
            selected = next(((key, item) for key, item in state.data["tasks"].items() if item["status"] == "pending"), None)
            if selected is None:
                break
            key, item = selected
            task = adapters.OfficialTask(**item["task"])
            item.update(status="attempting", code=None)
            state.save()
            request_start = client.requests
            try:
                result = adapters.execute(task, client, runtime_key=runtime_key)
                _publish(state.fd, "response-" + key + ".raw", result.raw, immutable=True)
                evidence = {"response": asdict(result.response), "task": asdict(task),
                    "candidates": [asdict(candidate) for candidate in result.candidates],
                    "nextTasks": [asdict(next_task) for next_task in result.next_tasks], "limitations": list(result.limitations)}
                _publish(state.fd, "response-" + key + ".json", canonical(evidence).encode(), immutable=True)
                state.data["responses"][result.response.raw_sha256] = {"stateDir": config.state_dir, "taskKey": key}
                next_tasks = list(result.next_tasks)
                for candidate in result.candidates:
                    if task.kind != "dart-corps":
                        state.data["candidates"][candidate.candidate_id] = asdict(candidate)
                    if candidate.body_task is not None:
                        next_tasks.append(candidate.body_task)
                for following in next_tasks:
                    state.data["tasks"].setdefault(following.key, _entry(following))
                if result.prepared is not None:
                    _retain(config, state, task, result)
                item.update(status="done", code=result.status)
            except IngestionFailure as exc:
                if exc.code in RESOURCE_STOPS:
                    sent_incomplete = exc.code in {"timeout", "byte_budget"} and client.requests > request_start
                    item.update(status="unknown" if sent_incomplete else "pending", code=exc.code)
                    if sent_incomplete:
                        state.data["unknownRequests"] += 1
                        state.data["unknownByteUpperBound"] += config.policy.max_response_bytes
                    state.data["stopCode"] = exc.code
                    state.save()
                    break
                item.update(status="refused", code=exc.code)
                if exc.code.startswith(("http_401", "http_403", "http_429", "opendart_auth_or_quota_")):
                    state.data["stopCode"] = exc.code
                    state.save()
                    break
            state.save()
        return summary(config, state)
    finally:
        state.close()


def status(config):
    return run(config, "status")


def retained_items(config):
    state = State(config, "status")
    try:
        for item in [*state.data["inheritedRecords"], *state.data["records"].values()]:
            yield dict(item)
    finally:
        state.close()
