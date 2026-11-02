"""Explicit read-only collection history for a fresh run, including unknown exclusions."""
from __future__ import annotations

from collections import Counter
import copy
import fcntl
import os
from pathlib import Path

import overnight_collect as base
from zoop_ai_pipeline.ingestion_contracts import digest


def include(roots, output, retained, exclusion):
    selected, seen_states = [], set()
    for position, value in enumerate(roots):
        root = Path(value)
        if (not root.is_absolute() or root.resolve(strict=True) != root or root == output
                or root.is_relative_to(output) or output.is_relative_to(root)):
            raise ValueError("explicit_distinct_prior_collection_required")
        lock = os.open(root / ".controller.lock", os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            pins = {name: base.ref(root / name) for name in ("PLAN.json", "LEDGER.json", "INDEX.json")}
            manifest, ledger, index = (base.load(root / name) for name in ("PLAN.json", "LEDGER.json", "INDEX.json"))
            if (ledger.get("endedAt") is None or any(row.get("status") in {"running", "reserved"} for row in ledger["plans"].values())
                    or ledger["planSha256"] != pins["PLAN.json"]["sha256"] or index["runId"] != manifest["runId"]):
                raise ValueError("prior_collection_not_drained_or_bound")
            destination = output / "evidence" / "prior-collections" / str(position)
            snapshots = {}
            for name, reference in pins.items():
                target = destination / name
                base.atomic(target, Path(reference["path"]).read_text(), immutable=True, text=True)
                if base.sha(target) != reference["sha256"]:
                    raise ValueError("prior_metadata_snapshot_changed")
                snapshots[name] = base.ref(target)
            state_refs = []
            for plan in base.all_plans(manifest, ledger):
                state = Path(plan["configTemplate"]["stateDir"])
                if state in seen_states:
                    continue
                seen_states.add(state)
                state_path = state / "STATE.json"
                if not state_path.exists():
                    if ledger["plans"].get(plan["id"], {}).get("status") == "unknown":
                        exclusion["blockedHosts"].update(plan["hosts"])
                    continue
                references = {name: base.ref(state / name) for name in ("PLAN.json", "STATE.json")}
                if (state / "QUEUE.sqlite3").exists():
                    references["QUEUE.sqlite3"] = base.ref(state / "QUEUE.sqlite3")
                base.absorb_state(state_path, exclusion, keep_unattempted=True, immutable=True)
                state_snapshots = {}
                for name in ("PLAN.json", "STATE.json"):
                    target = destination / "states" / plan["id"] / name
                    base.atomic(target, (state / name).read_text(), immutable=True, text=True)
                    if base.sha(target) != references[name]["sha256"]:
                        raise ValueError("prior_state_snapshot_changed")
                    state_snapshots[name] = base.ref(target)
                if plan["kind"] == "private":
                    snapshot = base.load(state_path)
                    data = snapshot["state"]
                    candidates = list(base.state_rows(data, state, "candidates", immutable=True))
                    old_plan_id = base.load(state / "PLAN.json")["config"]["planId"]
                    urls = {"private-news-" + digest([old_plan_id, row["url"]]): row["url"] for row in candidates}
                    protected = exclusion.setdefault("noReplayUrls", set())
                    for row in candidates:
                        own_actor_refusal = row["status"] == "refused" and row.get("code") == "fallback_admission_mismatch"
                        if row["status"] != "pending" and not own_actor_refusal:
                            protected.add(base.url_key(row["url"]))
                    for attempt in base.state_rows(data, state, "attempts", immutable=True):
                        own_url = urls.get(attempt.get("key"))
                        native = attempt.get("nativeObservation") or {}
                        response = attempt.get("response") or {}
                        metadata = attempt.get("articleMetadata") or {}
                        identities = [response.get("requestUrl"), response.get("finalUrl"),
                                      native.get("requestedUrl"), native.get("finalUrl"), metadata.get("canonicalUrl")]
                        identities.extend(native.get("redirects") or [])
                        identities.extend(response.get("redirects") or [])
                        if attempt.get("kind") == "article" and (attempt.get("status") != "deferred" or any(identities)):
                            identities.append(own_url)
                        own_actor_refusal = (
                            attempt.get("kind") == "article" and attempt.get("status") == "refused"
                            and attempt.get("code") == "fallback_admission_mismatch"
                            and native.get("requestedUrl") == own_url and native.get("httpStatus") in {200, 403}
                            and not any(attempt.get(field) is not None for field in
                                        ("providerReceipt", "providerAttemptId", "providerOutcome", "extractionArtifact")))
                        # Eligibility is separately proved by the Actor bundle. This exemption
                        # never covers another request's redirect or canonical occurrence.
                        for value in identities:
                            if value and not (own_actor_refusal and value == own_url):
                                protected.add(base.url_key(value))
                    for record_path in state.glob("private-news-*.json"):
                        if record_path.name.endswith(".extraction.json"):
                            continue
                        record = base.load(record_path)
                        for field in ("requestUrl", "finalUrl", "canonicalUrl"):
                            if record.get(field):
                                protected.add(base.url_key(record[field]))
                        protected.update(base.url_key(value) for value in record.get("redirects", []))
                state_refs.append({"planId": plan["id"], "stateDir": str(state), "files": references, "snapshots": state_snapshots})
            current = root / "evidence/CURRENT_EXCLUSIONS.json"
            if current.exists():
                prior = base.exclusion_sets(base.load(current))
                for key in ("urls", "newsIds", "blockedHosts"):
                    exclusion[key].update(prior[key])
                if prior.get("noReplayUrls"):
                    exclusion.setdefault("noReplayUrls", set()).update(prior["noReplayUrls"])
                for host, delay in prior["hostDelays"].items():
                    exclusion["hostDelays"][host] = max(exclusion["hostDelays"].get(host, 0), delay)
                pins["CURRENT_EXCLUSIONS.json"] = base.ref(current)
            retained["privateItems"].extend(index["privateItems"])
            retained["nativeItems"].extend(index["nativeItems"])
            retained["reusedCorpus"].append({"kind": "explicit-prior-collection", "inventory": pins["INDEX.json"],
                                            "freshness": "reused", "newCollection": False})
            for reference in pins.values():
                if base.ref(reference["path"]) != reference:
                    raise ValueError("prior_collection_changed")
            selected.append({"root": str(root), "originals": pins, "snapshots": snapshots, "states": state_refs,
                             "unknownPlans": [key for key, row in ledger["plans"].items() if row.get("status") == "unknown"]})
        finally:
            os.close(lock)
    retained["privateItems"] = base.unique_items(retained["privateItems"], "recordPath")
    retained["nativeItems"] = base.unique_items(retained["nativeItems"], "exportPath")
    receipt = {"schemaVersion": "zoop-prior-collections-1", "selected": selected, "originalsModified": False,
               "excludedUrls": len(exclusion["urls"]), "unknownReplay": False}
    target = output / "evidence/PRIOR_COLLECTIONS.json"
    base.atomic(target, receipt, immutable=True)
    return base.ref(target)


def merge_private(items):
    """Exact retained record identity only; never merge URLs or cross-source events."""
    selected = {}
    for item in items:
        key = item["privateId"]
        prior = selected.get(key)
        if prior is not None and any(prior[field] != item[field] for field in ("sourceId", "planId", "recordSha256")):
            raise ValueError("retained_record_identity_conflict")
        if prior is None:
            selected[key] = item
    return list(selected.values())


def replay_package(path, output, exclusion):
    from zoop_ai_pipeline import private_intake as intake
    from zoop_ai_pipeline.extraction_fallback import verify_extracted_page
    from zoop_ai_pipeline.private_continuation import immutable_db, require_pin, _rows
    from zoop_ai_pipeline.private_retained import describe_record

    path = Path(path)
    package = path.parent
    if (not path.is_absolute() or path.resolve(strict=True) != path or path.name != "INDEX.json"
            or package == output or package.is_relative_to(output) or output.is_relative_to(package)):
        raise ValueError("explicit_distinct_replay_package_required")
    index_pin = base.ref(path)
    index = intake._json(path.read_bytes())
    fields = {"schemaVersion", "mode", "originalPins", "evidencePins", "approvalRef", "considered",
              "available", "retained", "unrecovered", "outcomes", "privateItems", "externalCalls", "originalsModified"}
    if (set(index) != fields or index["schemaVersion"] != "zoop-retained-markdown-replay-1"
            or index["mode"] != "offline-retained-replay" or type(index["externalCalls"]) is not int
            or index["externalCalls"] != 0 or index["originalsModified"] is not False
            or not isinstance(index["approvalRef"], str) or not index["approvalRef"].strip()
            or any(type(index[key]) is not int or index[key] < 0 for key in ("available", "considered", "retained"))
            or not 0 <= index["retained"] <= index["considered"] <= index["available"]
            or not all(isinstance(index[key], list) for key in ("outcomes", "privateItems", "evidencePins"))
            or not isinstance(index["unrecovered"], dict)
            or any(not isinstance(key, str) or not key or type(value) is not int or value <= 0
                   for key, value in index["unrecovered"].items())
            or set(index["originalPins"]) != {"PLAN.json", "STATE.json", "QUEUE.sqlite3"}):
        raise ValueError("retained_replay_schema_invalid")
    pins = [index_pin, *index["originalPins"].values(), *index["evidencePins"]]
    for reference in pins:
        require_pin(reference)
    original = Path(index["originalPins"]["PLAN.json"]["path"]).parent
    if any(Path(reference["path"]) != original / name for name, reference in index["originalPins"].items()):
        raise ValueError("retained_replay_origin_mismatch")
    binding = base.load(original / "PLAN.json")
    snapshot = base.load(original / "STATE.json")
    if snapshot["sha256"] != digest(snapshot["state"]) or snapshot["state"]["planDigest"] != digest(binding):
        raise ValueError("retained_replay_state_mismatch")
    with immutable_db(original / "QUEUE.sqlite3") as db:
        if db.execute("SELECT digest FROM binding").fetchall() != [(digest(binding),)]:
            raise ValueError("retained_replay_queue_mismatch")
        attempts = [row for _, row in _rows(db, "attempts")
                    if row.get("code") == "article_date_unknown" and row.get("status") == "refused"
                    and row.get("providerOutcome") == "success" and row.get("extractionArtifact")]
        candidates = dict(_rows(db, "candidates"))
    state = package / "state"
    expected_config = copy.deepcopy(binding["config"])
    for key in ("fallback", "predecessor", "knownUnsent"):
        expected_config.pop(key, None)
    expected_config.update(planId="markdown-" + digest(index["originalPins"])[:40], stateDir=str(state),
                           operatorApprovalRef=index["approvalRef"])
    expected_config = intake.Config.model_validate(expected_config).wire()
    package_plan = base.load(state / "PLAN.json")
    if package_plan["config"] != expected_config:
        raise ValueError("retained_replay_source_plan_mismatch")
    items = base.private_items(state)
    if (items != index["privateItems"] or len(items) != index["retained"]
            or len(attempts) != index["available"] or len(index["outcomes"]) != index["considered"]):
        raise ValueError("retained_replay_membership_mismatch")
    records = {}
    allowed_files = {state / "PLAN.json"}
    for item in items:
        description = describe_record(item, output / "replay-verification-inputs")
        record = description["record"]
        if (record["schemaVersion"] != "zoop-private-news-record-3" or record["representation"] != "markdown"
                or not expected_config["fromDay"] <= record["publicationDay"] <= expected_config["throughDay"]):
            raise ValueError("retained_replay_record_version_or_window_invalid")
        records[record["privateId"]] = record
        allowed_files.update(description["pins"])
    if set(state.iterdir()) != allowed_files or set(package.iterdir()) != {path, state}:
        raise ValueError("immutable_replay_package_required")
    pins.extend(base.ref(value) for value in sorted(allowed_files))
    expected_evidence, recovered, unrecovered = [], set(), Counter()
    for outcome, attempt in zip(index["outcomes"], attempts):
        identifier = attempt["key"]
        candidate = candidates[identifier]
        if outcome["oldPrivateId"] != identifier or attempt["extractionArtifact"]["file"] != identifier + ".extraction.json":
            raise ValueError("retained_replay_outcome_mismatch")
        reference = {"path": str(original / attempt["extractionArtifact"]["file"]),
                     "sha256": attempt["extractionArtifact"]["sha256"]}
        envelope = intake._json(require_pin(reference).read_bytes())
        verify_extracted_page(envelope, allowed_hosts=tuple(expected_config["exactArticleHosts"]))
        if (envelope["requestedUrl"] != candidate["url"] or envelope["backend"] != "deepseek-fetch"
                or envelope["providerReceipt"]["attemptId"] != attempt["providerAttemptId"]):
            raise ValueError("retained_replay_provider_mismatch")
        if outcome["status"] == "retained":
            if set(outcome) != {"oldPrivateId", "privateId", "status", "publication", "evidenceMethod"}:
                raise ValueError("retained_replay_outcome_invalid")
            record = records[outcome["privateId"]]
            if (outcome["privateId"] in recovered or record["requestUrl"] != candidate["url"]
                    or record["source"] != candidate["refs"][0]["source"] or record["discoveryRefs"] != candidate["refs"]
                    or record["extractionArtifact"]["sha256"] != reference["sha256"]
                    or record["publication"] != outcome["publication"]
                    or record["publicationEvidence"]["method"] != outcome["evidenceMethod"]):
                raise ValueError("retained_replay_record_mismatch")
            recovered.add(outcome["privateId"])
            causal = envelope["nativeObservation"]["knownUnsent"]
            if causal is not None:
                expected_evidence.append({"path": str(original / causal["receiptRef"]), "sha256": causal["receiptSha256"]})
        elif outcome["status"] == "unrecovered":
            if set(outcome) != {"oldPrivateId", "status", "reasonCode"} or not isinstance(outcome["reasonCode"], str) or not outcome["reasonCode"]:
                raise ValueError("retained_replay_outcome_invalid")
            unrecovered[outcome["reasonCode"]] += 1
        else:
            raise ValueError("retained_replay_outcome_invalid")
        expected_evidence.append(reference)
        native = envelope["nativeObservation"]
        for url in (candidate["url"], envelope["finalUrl"], native["requestedUrl"], native["finalUrl"], *native["redirects"]):
            if url:
                exclusion["urls"].add(base.url_key(url))
                exclusion["noReplayUrls"].add(base.url_key(url))
    if (set(records) != recovered or dict(unrecovered) != index["unrecovered"]
            or expected_evidence != index["evidencePins"]):
        raise ValueError("retained_replay_evidence_mismatch")
    for reference in pins:
        require_pin(reference)
    return index, pins


def include_replays(paths, output, retained, exclusion):
    selected, pins = [], {}
    exclusion.setdefault("noReplayUrls", set())
    for path in dict.fromkeys(paths):
        index, references = replay_package(path, output, exclusion)
        for reference in references:
            prior = pins.setdefault(reference["path"], reference)
            if prior != reference:
                raise ValueError("retained_replay_pin_conflict")
        retained["privateItems"].extend(index["privateItems"])
        summary = {"kind": "retained-markdown-replay", "inventory": references[0],
                   "freshness": "reused", "newCollection": False, "externalCalls": 0,
                   **{key: index[key] for key in ("available", "considered", "retained", "unrecovered")}}
        selected.append(summary)
        retained["reusedCorpus"].append(summary)
    retained["privateItems"] = merge_private(retained["privateItems"])
    receipt = {"schemaVersion": "zoop-retained-replay-inputs-1", "selected": selected,
               "pins": list(pins.values()), "modelSend": False, "publicUse": False, "unknownReplay": False}
    target = output / "evidence/REPLAY_PACKAGES.json"
    base.atomic(target, receipt, immutable=True)
    return base.ref(target)


def verify_replay_pins(reference):
    from zoop_ai_pipeline.private_continuation import require_pin
    receipt = base.load(require_pin(reference))
    for pin in receipt["pins"]:
        require_pin(pin)
    for selected in receipt["selected"]:
        root = Path(selected["inventory"]["path"]).parent
        state = root / "state"
        expected = {Path(pin["path"]) for pin in receipt["pins"] if Path(pin["path"]).parent == state}
        if set(root.iterdir()) != {root / "INDEX.json", state} or set(state.iterdir()) != expected:
            raise ValueError("immutable_replay_package_required")
