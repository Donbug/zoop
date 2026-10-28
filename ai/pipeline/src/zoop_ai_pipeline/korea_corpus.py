"""Operator-owned bounded retrospective collection. No scheduler, model call or automatic retry."""
from __future__ import annotations

import fcntl
import json
import os
import re
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from .collection import Fetched, Fetcher, collect
from .collection_contracts import Policy, Request
from .ingestion import Ingestor, Store
from .ingestion_contracts import Authority, Export, Grant, IngestionFailure, Run, Wire, byte_hash, canonical, digest, now, read_file, reserved_state_roots
from .korea_portal import BODY_XPATH, listing_url, parse_listing, validate_article

MAX_STATE = 8_000_000


class CorpusPolicy(Policy):
    # Only this operator wrapper accepts a larger cumulative cap. The one-shot collector schema is unchanged.
    max_requests: int = Field(ge=1, le=5000)


class Channel(Wire):
    name: Literal["policy-news", "press-release", "clarifications"]
    max_pages: int = Field(ge=1, le=60)
    max_documents: int = Field(ge=1, le=400)


class Evidence(Wire):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Config(Wire):
    schema_version: Literal["zoop-korea-corpus-1"]
    plan_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,60}$")
    state_dir: str
    from_day: str
    through_day: str
    listing_origin: str
    article_origin: str
    exact_hosts: list[str] = Field(min_length=1, max_length=2)
    channels: list[Channel] = Field(min_length=1, max_length=3)
    max_listing_pages: int = Field(ge=1, le=60)
    max_candidates: int = Field(ge=1, le=800)
    max_documents: int = Field(ge=1, le=400)
    policy: CorpusPolicy
    grant: Grant
    rights_evidence: Evidence
    exclusion_manifest: Evidence

    @model_validator(mode="after")
    def pins(self):
        if date.fromisoformat(self.from_day).isoformat() != self.from_day or date.fromisoformat(self.through_day).isoformat() != self.through_day or self.from_day > self.through_day:
            raise ValueError("calendar days required")
        if not Path(self.state_dir).is_absolute() or self.state_dir != os.path.abspath(self.state_dir):
            raise ValueError("absolute state directory required")
        if len(set(c.name for c in self.channels)) != len(self.channels) or len(set(self.exact_hosts)) != len(self.exact_hosts):
            raise ValueError("duplicate channel or host")
        if self.policy.allowed_media_types != ["text/html"] or self.policy.max_redirects != 0:
            raise ValueError("HTML only; redirects are not portal article identity")
        expected = {"www.korea.kr", "m.korea.kr"}
        for origin in (self.listing_origin, self.article_origin):
            p = urlsplit(origin)
            if p.path or p.query or p.fragment or p.username or p.password:
                raise ValueError("exact origin required")
            if self.policy.synthetic_loopback:
                if p.hostname not in {"127.0.0.1", "localhost"} or p.scheme != "http":
                    raise ValueError("synthetic loopback only")
            elif p.scheme != "https" or p.hostname not in expected or p.port is not None:
                raise ValueError("official HTTPS origin required")
        if set(self.exact_hosts) != {urlsplit(o).hostname for o in (self.listing_origin, self.article_origin)}:
            raise ValueError("origins must bind exact hosts")
        if not self.policy.synthetic_loopback and self.policy.min_interval_seconds < 2:
            raise ValueError("real per-host pacing must be at least two seconds")
        if self.grant.source_id != "korea-portal" or set(self.grant.allowed_operations) != {"read", "store", "quote-display"} or self.grant.recipients or self.grant.purposes or not self.grant.enabled or self.grant.rights != "known" or not any(e.strip() for e in self.grant.evidence):
            raise ValueError("explicit read/store/quote grant required; never model-send")
        return self


def load_config(path):
    return Config.model_validate_json(read_file(Path(path), 200_000))


def load_evidence(ref):
    raw = read_file(Path(ref.path), 2_000_000)
    if byte_hash(raw) != ref.sha256:
        raise IngestionFailure("corpus_evidence_changed")
    return raw


def exclusions(config):
    data = json.loads(load_evidence(config.exclusion_manifest))
    # Explicit IDs only. Preparing this manifest never reads or modifies the previous acquisition ledger.
    if set(data) != {"schemaVersion", "newsIds"} or data["schemaVersion"] != "zoop-korea-exclusions-1" or not isinstance(data["newsIds"], list) or len(data["newsIds"]) > 10000:
        raise IngestionFailure("corpus_exclusions_invalid")
    import re
    if any(not isinstance(i, str) or not re.fullmatch(r"\d{9}", i) for i in data["newsIds"]) or len(set(data["newsIds"])) != len(data["newsIds"]):
        raise IngestionFailure("corpus_exclusions_invalid")
    return set(data["newsIds"])


def safe_directory(path, *, create=False):
    path = Path(path)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, part in enumerate(path.parts[1:]):
            if create and index == len(path.parts) - 2:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def atomic(path, value, *, immutable=False, guard=None):
    """Private staged bytes, fsync, no-clobber link (records) or rename (snapshot), directory fsync."""
    raw = canonical(value).encode()
    if len(raw) > MAX_STATE:
        raise IngestionFailure("corpus_state_size")
    if immutable and path.exists():
        if read_file(path, MAX_STATE) != raw:
            raise IngestionFailure("corpus_record_conflict")
        if guard is not None:
            guard()
        return
    directory = safe_directory(path.parent)
    name = ".stage-" + uuid.uuid4().hex
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        if guard is not None:
            guard()
        if immutable:
            staged = os.stat(name, dir_fd=directory, follow_symlinks=False)
            os.link(name, path.name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
            try:
                os.fsync(directory)
                if guard is not None:
                    guard()
                os.unlink(name, dir_fd=directory)
                os.fsync(directory)
                if guard is not None:
                    guard()
            except BaseException:
                try:
                    visible = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
                except FileNotFoundError:
                    visible = None
                if visible and (staged.st_dev, staged.st_ino) == (visible.st_dev, visible.st_ino):
                    os.unlink(path.name, dir_fd=directory)
                    os.fsync(directory)
                raise
        else:
            os.replace(name, path.name, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
    finally:
        try:
            os.unlink(name, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)


class State:
    def __init__(self, config, binding):
        self.root = Path(config.state_dir)
        checkout = Path(__file__).resolve().parents[4]
        for reserved in [checkout, *reserved_state_roots()]:
            if self.root == reserved or self.root.is_relative_to(reserved) or reserved.is_relative_to(self.root):
                raise IngestionFailure("corpus_namespace_conflict")
        self.fd = safe_directory(self.root, create=True)
        self.lock = None
        try:
            entries = list(self.root.iterdir())
            if entries:
                previous = json.loads(read_file(self.root / "PLAN.json", MAX_STATE))
                if previous != binding:
                    raise IngestionFailure("corpus_configuration_conflict")
                # No adoption or cleanup of foreign names or symlinks, including nested owned paths.
                allowed = {"PLAN.json", "STATE.json", "PACKAGE.json", ".lock", "native", "items", "exports"}
                for base, dirs, files in os.walk(self.root, followlinks=False):
                    for name in [*dirs, *files]:
                        p = Path(base) / name
                        if p.is_symlink() or not (p.is_dir() or p.is_file()):
                            raise IngestionFailure("corpus_namespace_conflict")
                        if Path(base) == self.root and name not in allowed and not name.startswith(".stage-"):
                            raise IngestionFailure("corpus_namespace_conflict")
                self.data = json.loads(read_file(self.root / "STATE.json", MAX_STATE))
            else:
                self.data = {"startedAt": now(), "requests": 0, "bytes": 0, "unknownRequests": 0, "unknownByteUpperBound": 0,
                             "pendingRequest": None, "blocked": [], "delays": {}, "items": {}, "channels": {c.name: {"page": 1, "done": False, "reason": None, "pages": 0, "signatures": [], "oldest": None} for c in config.channels},
                             "listingPages": 0, "candidateCount": 0, "duplicates": 0, "exclusions": 0, "pendingListing": None, "reason": None}
            self.lock = os.open(".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise IngestionFailure("corpus_busy") from exc
            if not entries:
                atomic(self.root / "PLAN.json", binding, immutable=True)
                for child in ("items", "native", "exports"):
                    os.mkdir(child, 0o700, dir_fd=self.fd)
                self.save()
            else:
                # The lock winner may have committed after our read-only binding check.
                self.data = json.loads(read_file(self.root / "STATE.json", MAX_STATE))
        except BaseException:
            self.close()
            raise

    def save(self):
        atomic(self.root / "STATE.json", self.data)

    def close(self):
        if self.lock is not None:
            os.close(self.lock)
        os.close(self.fd)


class DurableFetcher(Fetcher):
    """One transport for listing and native collection, with write-ahead request reservations."""
    def __init__(self, config, state, guard):
        super().__init__(config.policy, config.exact_hosts, authority_guard=guard)
        self.state = state
        data = state.data
        self.requests = data["requests"] + data["unknownRequests"]
        self.downloaded = data["bytes"] + data["unknownByteUpperBound"]
        elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(data["startedAt"])).total_seconds()
        self.run_deadline = time.monotonic() + max(0, config.policy.max_total_seconds - elapsed)
        self._blocked.update(data["blocked"])
        self._delay.update(data["delays"])
        # Cross-process pacing is conservative; robots are rechecked on restart and count again.
        for host in config.exact_hosts:
            self._last[host] = time.monotonic()

    def fetch(self, value):
        try:
            fetched = super().fetch(value)
            if self.authority_guard is not None:
                self.authority_guard()
            return fetched
        finally:
            self.state.data["delays"] = self._delay
            self.state.data["blocked"] = sorted(self._blocked)
            self.state.save()

    def _get(self, url, host, deadline, limit):
        self._remaining(deadline)
        if self.requests >= self.policy.max_requests:
            raise IngestionFailure("request_budget")
        if self.downloaded >= self.policy.max_total_bytes:
            raise IngestionFailure("byte_budget")
        data = self.state.data
        before_requests, before_bytes = self.requests, self.downloaded
        data["pendingRequest"] = {"url": url, "host": host, "byteUpperBound": self.policy.max_total_bytes - self.downloaded, "startedAt": now()}
        self.state.save()
        try:
            return super()._get(url, host, deadline, limit)
        finally:
            data["requests"] += self.requests - before_requests
            data["bytes"] += self.downloaded - before_bytes
            data["blocked"] = sorted(self._blocked)
            data["pendingRequest"] = None
            self.state.save()


def registry(config, state, candidate):
    scope = candidate["newsId"]
    return {"schemaVersion": "zoop-ingestion-s2-1", "revision": config.plan_id, "sources": [{
        "sourceId": "korea-portal", "adapter": "collected-http", "inputRoot": str(state.root / "native"), "allowedHosts": config.exact_hosts,
        "scopes": [{"scopeId": scope, "selection": f"{config.plan_id}: {candidate['channel']} newsId={scope}; {config.from_day} through {config.through_day}; per-item KOGL1 text gate",
                    "initialCursor": None, "articleXPath": BODY_XPATH,
                    "timestampLimitations": ["visible calendar day only; no timezone or midnight inference", "bounded retrospective selection; no full period coverage"]}],
        "grant": config.grant.wire()}]}


def acquire_item(config, state, fetcher, record, guard, *, recovering=False):
    candidate = record["candidate"]
    identifier = candidate["newsId"]
    item_dir = state.root / "items" / identifier
    if not item_dir.exists():
        item_dir.mkdir(mode=0o700)
    sources = item_dir / "sources.json"
    atomic(sources, registry(config, state, candidate), immutable=True)
    if not recovering:
        record["phase"] = "collection-intent"
        state.save()
    target = {"candidateId": identifier, "url": candidate["url"], "supplierDocumentId": identifier, "title": candidate["title"],
              "publisher": candidate["publisher"], "publishedAt": candidate["publicationDay"], "documentKind": "news"}
    request = Request.model_validate({"schemaVersion": "zoop-collection-1", "collectionId": "item-" + identifier,
                                     "sourceId": "korea-portal", "scopeId": identifier, "targets": [target]})

    def validate(target, response):
        guard()
        rights = validate_article(response, candidate, config)
        guard()
        # The actual native response is the sole rights input; the immutable facts precede native publication.
        atomic(item_dir / "rights.json", rights, immutable=True)

    guard()

    result = collect(sources, config.policy, request, fetcher=fetcher, validate_response=validate)
    if result["state"] == "complete":
        guard()
        try:
            rights = json.loads(read_file(item_dir / "rights.json", MAX_STATE))
            native = state.root / "native" / "collections" / ("item-" + identifier)
            target_result = result["targets"][0]
            body_hash, receipt_hash = target_result["bodySha256"], target_result["receiptSha256"]
            if (not isinstance(rights, dict) or not isinstance(body_hash, str) or not isinstance(receipt_hash, str)
                    or not re.fullmatch(r"[a-f0-9]{64}", body_hash) or not re.fullmatch(r"[a-f0-9]{64}", receipt_hash)
                    or rights.get("bodySha256") != body_hash):
                raise IngestionFailure("corpus_rights_receipt_mismatch")
            body = read_file(native / "bodies" / (body_hash + ".bin"), config.policy.max_response_bytes)
            if byte_hash(body) != body_hash:
                raise IngestionFailure("corpus_rights_receipt_mismatch")
            receipt_raw = read_file(native / "receipts" / (receipt_hash + ".json"), MAX_STATE)
            if byte_hash(receipt_raw) != receipt_hash:
                raise IngestionFailure("corpus_rights_receipt_mismatch")
            receipt = json.loads(receipt_raw)
            if (not isinstance(receipt, dict) or receipt.get("bodySha256") != body_hash
                    or receipt.get("candidateId") != identifier or receipt.get("requestedUrl") != candidate["url"]):
                raise IngestionFailure("corpus_rights_receipt_mismatch")
            # Recheck every saved rights fact against the published native body, never another GET.
            saved = Fetched(receipt["requestedUrl"], receipt["finalUrl"], receipt["httpStatus"],
                            receipt["contentType"], receipt["mediaType"], body, {}, [], [], 0,
                            fetched_at=receipt["fetchedAt"])
            if canonical(rights) != canonical(validate_article(saved, candidate, config)):
                raise IngestionFailure("corpus_rights_receipt_mismatch")
        except (OSError, ValueError, TypeError, KeyError, IndexError, IngestionFailure) as exc:
            raise IngestionFailure("corpus_rights_receipt_mismatch") from exc
        guard()
        record["rights"] = rights
    if result["state"] != "complete":
        raise IngestionFailure(result["targets"][0]["code"] or "corpus_collection_failed")
    atomic(item_dir / "collection-result.json", result | {"replayed": False}, immutable=True)
    guard()
    record["phase"] = "ingestion"
    state.save()
    guard()
    store = Store(item_dir / "ingestion")
    try:
        guard()
        ingestor = Ingestor(store, Authority(sources))
        previous = store.one("SELECT state FROM rounds WHERE id=? AND source=?", ("item-" + identifier, "korea-portal"))
        if previous:
            # Resume only an interrupted running round, never retry a terminal incomplete observation.
            ingested = (ingestor.resume if previous["state"] == "running" else ingestor.result)("item-" + identifier, "korea-portal")
        else:
            ingested = ingestor.run(Run.model_validate({"schemaVersion": "zoop-ingestion-s2-1", "roundId": "item-" + identifier,
                "sourceId": "korea-portal", "scopeId": identifier, "window": None, "checkpointRevision": 0,
                "fixtureManifestHash": result["manifest"]["sha256"], "cleanerVersion": "exact-copy-1"}), Path(result["manifestPath"]))
        guard()
        refs = ingested["documentRefs"]
        if len(refs) != 1 or not refs[0]["documentVersion"] or refs[0]["failure"]:
            raise IngestionFailure("corpus_ingestion_not_exportable")
        selector = Export.model_validate({"schemaVersion": "zoop-ingestion-s2-1", "roundId": "item-" + identifier, "sourceId": "korea-portal",
                                         **{k: refs[0][k] for k in ("page", "ordinal", "documentId", "rawVersion", "documentVersion")}})
        guard()
        exported = ingestor.export(selector, require_store=True)
        guard()
    finally:
        store.close()
    guard()
    atomic(item_dir / "ingestion-result.json", ingested, immutable=True)
    guard()
    atomic(state.root / "exports" / (identifier + ".json"), exported, immutable=True, guard=guard)
    guard()
    record.update(phase="exported", outcome="exported", exportFile="exports/" + identifier + ".json", exportSha256=digest(exported),
                  documentId=refs[0]["documentId"], rawVersion=refs[0]["rawVersion"], documentVersion=refs[0]["documentVersion"],
                  fetchedAt=exported["observation"]["collection"]["fetchedAt"], nativeBodySha256=result["targets"][0]["bodySha256"],
                  nativeReceiptSha256=result["targets"][0]["receiptSha256"], grant=exported["grant"])
    state.save()


def package(config, data):
    records = dict(sorted(data["items"].items()))
    counts = {name: sum(r["outcome"] == name for r in records.values()) for name in ("exported", "refused", "failed", "unknown", "pending")}
    hit = (("document-cap" if counts["exported"] >= config.max_documents else None)
           or ("candidate-cap" if data["candidateCount"] >= config.max_candidates else None)
           or ("listing-page-cap" if data["listingPages"] >= config.max_listing_pages else None))
    channels = {}
    for name, info in data["channels"].items():
        selected = [r for r in records.values() if r["candidate"]["channel"] == name]
        days = [r["candidate"]["publicationDay"] for r in selected]
        channels[name] = {**info, "candidates": len(selected), "exported": sum(r["outcome"] == "exported" for r in selected),
                          "observedDayRange": {"from": min(days), "through": max(days)} if days else None}
    completed = all(c["done"] and c["reason"] == "listing-end" for c in data["channels"].values()) and not data["reason"] and not hit and not any(counts[k] for k in ("failed", "unknown", "pending"))
    return {"schemaVersion": "zoop-korea-package-1", "planId": config.plan_id, "state": "completed" if completed else "partial",
            "acquisitionMode": "retrospective-bulk", "network": "synthetic_loopback" if config.policy.synthetic_loopback else "external",
            "period": {"from": config.from_day, "through": config.through_day, "precision": "day"}, "counts": counts,
            "duplicates": data["duplicates"], "exclusions": data["exclusions"], "candidateCount": data["candidateCount"],
            "usage": {k: data[k] for k in ("requests", "bytes", "unknownRequests", "unknownByteUpperBound", "listingPages")},
            "reason": data["reason"] or hit, "channels": channels, "documents": [r for r in records.values() if r["outcome"] == "exported"],
            "dispositions": [{"newsId": i, "outcome": r["outcome"], "reason": r.get("reason")} for i, r in records.items() if r["outcome"] != "exported"],
            "limits": {"coverage": "bounded chronological listing subset, not full coverage; caps mean partial", "models": "no model sends; no semantic/gold claim",
                       "text": "native canonical mapping unchanged; rights/contact boilerplate may remain and must not be treated as evidence", "retry": "none; failed or unknown attempts need an explicit distinct plan"}}


def status(config):
    data = json.loads(read_file(Path(config.state_dir) / "STATE.json", MAX_STATE))
    plan = json.loads(read_file(Path(config.state_dir) / "PLAN.json", MAX_STATE))
    if plan["config"] != config.wire():
        raise IngestionFailure("corpus_configuration_conflict")
    return package(config, data)


def run(config):
    evidence = load_evidence(config.rights_evidence)
    excluded = exclusions(config)
    binding = {"config": config.wire(), "rightsSha256": byte_hash(evidence), "gateVersion": "korea-portal-static-3"}
    state = State(config, binding)
    try:
        data = state.data
        if data["pendingRequest"]:
            pending = data["pendingRequest"]
            data["unknownRequests"] += 1
            data["unknownByteUpperBound"] += pending["byteUpperBound"]
            data["blocked"] = sorted(set(data["blocked"]) | {pending["host"]})
            data["pendingRequest"] = None
        if data["pendingListing"]:
            name = data["pendingListing"]
            data["channels"][name].update(done=True, reason="listing-interrupted-unknown")
            data["pendingListing"] = None
        state.save()

        def guard():
            load_evidence(config.rights_evidence)
            load_evidence(config.exclusion_manifest)
            # A changed operator grant/config is refused before existing state is opened; expiry stays live.
            if config.grant.expires_at and datetime.fromisoformat(config.grant.expires_at) <= datetime.now(timezone.utc):
                raise IngestionFailure("source_unauthorized")

        fetcher = DurableFetcher(config, state, guard)
        for record in data["items"].values():
            if record["outcome"] != "pending" or record["phase"] == "planned":
                continue
            identifier = record["candidate"]["newsId"]
            native = state.root / "native" / "collections" / ("item-" + identifier) / "collection.json"
            if native.exists():
                try:
                    guard()
                    acquire_item(config, state, fetcher, record, guard, recovering=True)
                except IngestionFailure as exc:
                    record.update(outcome="unknown" if exc.code == "corpus_rights_receipt_mismatch" else "failed", reason=exc.code)
            else:
                record.update(outcome="unknown", reason="interrupted-attempt-no-automatic-refetch")
            state.save()
        # Round-robin pages and items keep channel caps independent of portal category volume.
        while not data["reason"]:
            progress = False
            for channel in config.channels:
                name, info = channel.name, data["channels"][channel.name]
                successes = sum(r["outcome"] == "exported" and r["candidate"]["channel"] == name for r in data["items"].values())
                if successes >= channel.max_documents:
                    info.update(done=True, reason="channel-document-cap")
                pending = [r for r in data["items"].values() if r["outcome"] == "pending" and r["candidate"]["channel"] == name]
                if not pending and not info["done"]:
                    if info["pages"] >= channel.max_pages:
                        info.update(done=True, reason="channel-page-cap")
                    elif data["listingPages"] >= config.max_listing_pages:
                        data["reason"] = "listing-page-cap"
                        break
                    elif data["candidateCount"] >= config.max_candidates:
                        data["reason"] = "candidate-cap"
                        break
                    else:
                        data["pendingListing"] = name
                        info["pages"] += 1
                        data["listingPages"] += 1
                        state.save()
                        try:
                            response = fetcher.fetch(listing_url(config, name, info["page"]))
                            candidates, more = parse_listing(response.body, config, name, info["page"], info.get("pageSize"))
                            signature = digest([c["newsId"] for c in candidates])
                            if candidates and signature in info["signatures"]:
                                raise IngestionFailure("portal_repeated_page")
                            if candidates and info["oldest"] and candidates[0]["publicationDay"] > info["oldest"]:
                                raise IngestionFailure("portal_page_not_chronological")
                            atomic(state.root / "items" / f"listing-{name}-{info['page']}.json", {"requestedUrl": response.requested_url, "fetchedAt": response.fetched_at,
                                   "bodySha256": byte_hash(response.body), "candidates": candidates, "more": more}, immutable=True)
                            if info["page"] == 1:
                                info["pageSize"] = len(candidates)
                            info["signatures"].append(signature)
                            info["oldest"] = candidates[-1]["publicationDay"] if candidates else info["oldest"]
                            info["page"] += 1
                            info.update(done=not more, reason=None if more else "listing-end")
                            for candidate in candidates:
                                if data["candidateCount"] >= config.max_candidates:
                                    data["reason"] = "candidate-cap"
                                    break
                                data["candidateCount"] += 1
                                identifier = candidate["newsId"]
                                if identifier in excluded:
                                    data["exclusions"] += 1
                                elif identifier in data["items"]:
                                    data["duplicates"] += 1
                                else:
                                    data["items"][identifier] = {"candidate": candidate, "outcome": "pending", "phase": "planned"}
                        except IngestionFailure as exc:
                            info.update(done=True, reason=exc.code)
                        data["pendingListing"] = None
                        state.save()
                        progress = True
                        pending = [r for r in data["items"].values() if r["outcome"] == "pending" and r["candidate"]["channel"] == name]
                for record in pending:
                    successes = sum(r["outcome"] == "exported" and r["candidate"]["channel"] == name for r in data["items"].values())
                    total = sum(r["outcome"] == "exported" for r in data["items"].values())
                    if total >= config.max_documents:
                        data["reason"] = "document-cap"
                        break
                    if successes >= channel.max_documents:
                        info.update(done=True, reason="channel-document-cap")
                        break
                    try:
                        guard()
                        acquire_item(config, state, fetcher, record, guard)
                    except IngestionFailure as exc:
                        record.update(outcome="refused" if exc.code.startswith("portal_") else "failed", reason=exc.code)
                    progress = True
                    state.save()
                if data["reason"]:
                    break
            if not progress:
                break
        state.save()
        result = package(config, data)
        atomic(state.root / "PACKAGE.json", result)
        return result
    finally:
        state.close()
