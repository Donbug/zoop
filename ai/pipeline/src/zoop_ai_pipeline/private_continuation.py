"""Proof-bound continuation of the frozen DAY Actor refusal, never generic retry."""
from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from .ingestion_contracts import IngestionFailure, digest
from .extraction_fallback import FETCH_ENDPOINT, _observation_from_wire, _reject_page
from .private_processing import Actor

ACTOR_SOURCE = "8315c85348a219b5b57f08f305b5281bb7fbe77a3a9d069c4080f16cebfc368a"
REASON = "fallback_admission_mismatch"
SCHEMA = "zoop-actor-unsent-continuation-1"


def pin(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve(strict=True) != path or not path.is_file():
        raise IngestionFailure("continuation_path_invalid")
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            value.update(chunk)
    return {"path": str(path), "sha256": value.hexdigest()}


def require_pin(reference):
    if pin(reference["path"]) != reference:
        raise IngestionFailure("continuation_pin_changed")
    return Path(reference["path"])


@contextmanager
def immutable_db(path):
    path = Path(path)
    for suffix in ("-wal", "-shm", "-journal"):
        if path.with_name(path.name + suffix).exists():
            raise IngestionFailure("continuation_unsettled_database")
    db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
    try:
        yield db
    finally:
        db.close()


def load(reference):
    return json.loads(require_pin(reference).read_bytes())


def _rows(db, table):
    for key, raw, sha in db.execute(f"SELECT key,value,sha256 FROM {table}"):
        row = json.loads(raw)
        if digest(row) != sha:
            raise IngestionFailure("continuation_queue_corrupt")
        yield key, row


def eligible_native(value, url):
    native = _observation_from_wire(value)
    if (native.wire() != value or native.requested_url != url or native.http_status not in {200, 403}
            or native.access != "public" or native.www_authenticate or native.known_unsent is not None
            or native.failure_code not in {"http_403", "no_usable_body", "article_scope_ambiguous_or_missing"}
            or native.final_url != url or native.redirects):
        raise IngestionFailure("continuation_native_ineligible")
    if native.body is not None:
        _reject_page(native.body.decode("utf-8"), is_html=True)
    if native.http_status == 200 and native.body is None:
        raise IngestionFailure("continuation_native_missing")
    return native


def _members(group, refusals=None):
    old_plan = load(group["plan"])
    config = old_plan["config"]
    snapshot = load(group["state"])
    data = snapshot["state"]
    require_pin(group["queue"])
    if (snapshot["sha256"] != digest(data) or data["planDigest"] != digest(old_plan)
            or data["pendingRequest"] is not None or data.get("pendingProviderRequest") is not None
            or data.get("providerUnknownRequests", 0) or data.get("providerBytes", 0)
            or data.get("providerUnknownByteUpperBound", 0)):
        raise IngestionFailure("continuation_unsettled_state")
    with immutable_db(group["queue"]["path"]) as db:
        if db.execute("SELECT digest FROM binding").fetchall() != [(digest(old_plan),)]:
            raise IngestionFailure("continuation_queue_corrupt")
        attempts = {}
        for _, row in _rows(db, "attempts"):
            if row["kind"] == "article":
                attempts.setdefault(row["key"], []).append(row)
        candidates = dict(_rows(db, "candidates"))
        tasks = dict(_rows(db, "tasks"))
    members = []
    for expected in group["members"]:
        try:
            key = expected["candidateId"]
            candidate = candidates[key]
            rows = attempts.get(key, [])
            if (len(rows) != 1 or candidate.get("status") != "refused" or candidate.get("code") != REASON
                    or rows[0].get("status") != "refused" or rows[0].get("code") != REASON
                    or any(rows[0].get(field) is not None for field in
                           ("providerAttemptId", "providerReceipt", "providerOutcome", "extractionArtifact"))):
                raise IngestionFailure("continuation_not_known_unsent")
            observation = rows[0].get("nativeObservation")
            if observation is None or digest(observation) != expected["nativeObservationDigest"]:
                raise IngestionFailure("continuation_native_mismatch")
            native = eligible_native(observation, candidate["url"])
            if "url" in expected and expected["url"] != candidate["url"]:
                raise IngestionFailure("continuation_candidate_mismatch")
            if key != "private-news-" + digest([config["planId"], candidate["url"]]):
                raise IngestionFailure("continuation_candidate_mismatch")
            for reference in candidate["refs"]:
                task = tasks.get(reference["listing"])
                if task is None or task["status"] != "done":
                    raise IngestionFailure("continuation_discovery_missing")
            members.append((candidate, native))
        except IngestionFailure as exc:
            if refusals is None:
                raise
            refusals.append({**expected, "reasonCode": exc.code})
    return config, tasks, members


def verify_bundle(reference):
    document = load(reference)
    if document["schemaVersion"] != SCHEMA or not document["approvalRef"]:
        raise IngestionFailure("continuation_proof_invalid")
    actor = load(document["actorProof"])
    source = document["historicalSource"]
    require_pin(source)
    if (source["sha256"] != ACTOR_SOURCE or actor["status"] != "completed"
            or actor["checks"]["red"]["sourceSha256"] != ACTOR_SOURCE
            or actor["checks"]["red"]["failed"] != 7 or actor["checks"]["green"]["passed"] != 14
            or actor["checks"]["green"]["failed"] != 0
            or actor["networkAttempts"] != 0 or actor["providerDispatches"] != 0):
        raise IngestionFailure("continuation_actor_proof_invalid")
    pending = load(document["pending"])["knownUnsentCandidates"]
    old_collection = load(document["collectionPlan"])
    if old_collection["sourcePins"].get(source["path"]) != ACTOR_SOURCE:
        raise IngestionFailure("continuation_source_unbound")
    budget = require_pin(document["budget"])
    with immutable_db(budget) as db:
        for group in document["groups"]:
            config = load(group["plan"])["config"]
            fallback = config["fallback"]
            control = load({"path": fallback["budgetConfigPath"], "sha256": fallback["budgetConfigSha256"]})
            proof = load({"path": fallback["setProofPath"], "sha256": fallback["setProofSha256"]})
            template = {key: value for key, value in config.items() if key != "fallback"}
            if (control["schemaVersion"] != "zoop-private-run-2"
                    or Actor.model_validate(control["processingActor"]).wire() != control["processingActor"]
                    or budget != Path(control["root"]) / "modelbudget/live-budget.sqlite3"
                    or old_collection["options"]["fundingConfig"]["sha256"] != fallback["budgetConfigSha256"]
                    or proof["schemaVersion"] != "zoop-acquisition-set-1"
                    or proof["setId"] != fallback["setId"] or proof["sourceId"] != fallback["sourceId"]
                    or proof["unitDigest"] != digest(template)
                    or proof["allowance"] != {"fetch": fallback["maxCalls"], "search": 0}):
                raise IngestionFailure("continuation_old_admission_invalid")
            if db.execute("SELECT unit_digest FROM admitted_sets WHERE set_id=?", (fallback["setId"],)).fetchall() != [(proof["unitDigest"],)]:
                raise IngestionFailure("continuation_old_admission_invalid")
            if db.execute("SELECT 1 FROM reservation_sets WHERE set_id=? LIMIT 1", (fallback["setId"],)).fetchone():
                raise IngestionFailure("continuation_provider_reservation_present")
            for member in group["members"]:
                request_digest = digest({"endpoint": FETCH_ENDPOINT, "body": {"url": member["url"]}})
                if db.execute("SELECT 1 FROM reservation_sets WHERE stage='fetch' AND request_digest=? LIMIT 1",
                              (request_digest,)).fetchone():
                    raise IngestionFailure("continuation_provider_reservation_present")
                matches = [row for row in pending if row["candidateId"] == member["candidateId"]
                           and row["stateDir"] == str(Path(group["plan"]["path"]).parent)]
                if (len(matches) != 1 or matches[0]["originalCode"] != REASON
                        or matches[0]["hasProviderReceipt"] or matches[0]["hasProviderAttemptId"]
                        or not matches[0]["hasNativeObservation"]
                        or matches[0]["nativeObservationDigest"] != member["nativeObservationDigest"]):
                    raise IngestionFailure("continuation_pending_mismatch")
    return document


def prepare_bundle(pending, actor_proof, historical_source, collection_plan, budget, approval_ref):
    rows = json.loads(Path(pending).read_bytes())["knownUnsentCandidates"]
    groups = {}
    for row in rows:
        root = Path(row["stateDir"])
        if str(root) not in groups:
            groups[str(root)] = {"plan": pin(root / "PLAN.json"), "state": pin(root / "STATE.json"),
                                 "queue": pin(root / "QUEUE.sqlite3"), "members": []}
        group = groups[str(root)]
        group["members"].append({"candidateId": row["candidateId"], "nativeObservationDigest": row["nativeObservationDigest"]})
    accepted, refused = [], []
    for group in groups.values():
        rejected = []
        old, _, members = _members(group, rejected)
        urls = {"private-news-" + digest([old["planId"], candidate["url"]]): candidate["url"] for candidate, _ in members}
        refused.extend(rejected)
        rejected_ids = {row["candidateId"] for row in rejected}
        group["members"] = [{**row, "url": urls[row["candidateId"]]} for row in group["members"] if row["candidateId"] not in rejected_ids]
        if group["members"]:
            accepted.append(group)
    return {"schemaVersion": SCHEMA, "approvalRef": approval_ref, "pending": pin(pending),
            "actorProof": pin(actor_proof), "historicalSource": pin(historical_source),
            "collectionPlan": pin(collection_plan), "budget": pin(budget), "groups": accepted,
            "refused": refused, "originalsModified": False}


def seed(state):
    from . import private_intake as intake
    replay = state.config.known_unsent
    document = verify_bundle({"path": replay.path, "sha256": replay.sha256})
    groups = [group for group in document["groups"] if load(group["plan"])["config"]["planId"] == replay.plan_id]
    if len(groups) != 1:
        raise IngestionFailure("continuation_plan_mismatch")
    group = groups[0]
    old, tasks, members = _members(group)
    if len(state.config.sources) != 1 or old["sources"][0]["name"] != state.config.sources[0].name:
        raise IngestionFailure("continuation_source_mismatch")
    for candidate, native in members:
        value = copy.deepcopy(candidate)
        value.update(status="pending", reusableNative={**intake._retain_observation(state, native), "reason": REASON})
        value.pop("code", None)
        identifier = "private-news-" + digest([state.config.plan_id, value["url"]])
        state.data["candidates"][identifier] = value
        for reference in value["refs"]:
            key = reference["listing"]
            task = copy.deepcopy(tasks[key])
            task.update(status="inherited", inheritedStatus="done", evidenceStateDir=str(Path(group["plan"]["path"]).parent))
            state.data["tasks"][key] = task


def collection_plans(reference, root, options):
    from . import news_archives as archives
    from .private_intake import Config
    document = verify_bundle(reference)
    plans = []
    for group in document["groups"]:
        old, _, _ = _members(group)
        config = copy.deepcopy(old)
        for key in ("fallback", "predecessor"):
            config.pop(key, None)
        identifier = "actor-" + digest([reference, old["planId"]])[:40]
        config.update(planId=identifier, stateDir=str(root / "state" / identifier), operatorApprovalRef=options["approvalRef"],
                      fromDay=options["fromDay"], throughDay=options["throughDay"],
                      knownUnsent={**reference, "planId": old["planId"]})
        source = config["sources"][0]["name"]
        selected = archives.source_descriptor(source)
        if selected is not None:
            config["sources"][0]["descriptor"] = selected.wire()
        config["policy"].update(maxRequests=options["setRequests"], maxTotalBytes=options["setBytes"],
                                maxTotalSeconds=options["setSeconds"])
        config = Config.model_validate(config).wire()
        plans.append({"id": identifier, "rowId": source, "sourceId": source, "kind": "private", "freshness": "unknown",
                      "hosts": config["exactArticleHosts"], "configTemplate": config,
                      "ceilings": {"requests": options["setRequests"],
                                   "bytes": options["setBytes"] + config["policy"]["maxResponseBytes"],
                                   "seconds": options["setSeconds"]}})
    return plans
