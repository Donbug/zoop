#!/usr/bin/env python3
"""Recover briefing items without changing extraction, grouping or recorded rounds.

The original bundle and provider recordings are immutable inputs. Selection is
reused, never rescored. Fact checks receive current text only; editorial novelty
receives prior published source quotes separately. A failed item cannot discard
unrelated supported items. This is an opt-in development replay, not publication
authorization or proof of historical collection.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import briefing_grouped_rounds as grouped
import briefing_item_recovery as recovery

base, sim = grouped.base, grouped.sim
POLICY = "item-recovery-v1"
SCHEMA = "zoop-briefing-item-recovery-v1"
ERRORS = (sim.ReplayError, recovery.ReplayError)


def clone(value):
    return base.strict_load(base.canonical(value))


def require(condition, code):
    grouped.require(condition, code)


class CacheOnlyRecoveryClient(recovery.RecoveryClient):
    """Revalidate completed responses without reserving or transmitting a call."""
    def call(self, stage, data, prompt_name, schema_name, max_output=8000, schema_override=None):
        key = self.request_digest(stage, data, prompt_name, schema_name, max_output, schema_override)
        require((self.calls / (key + ".complete.json")).exists(), "recovery_cache_only_miss")
        return super().call(stage, data, prompt_name, schema_name, max_output, schema_override)


def reply(calls, key):
    receipt = base.strict_load(base.regular(calls / (key + ".complete.json")))
    request = base.regular(calls / (key + ".request.json"))
    response = base.regular(calls / (key + ".response.json"))
    require(base.digest(request) == key and base.digest(response) == receipt["responseSha256"]
            and receipt["status"] == "completed" and receipt["usageKnown"], "recovery_completed_record_required")
    return base.output_of(base.strict_load(response)), receipt


def normalized(item):
    value = clone(item)
    value["rank"] = 1
    return value


def prompt_artifacts():
    return {p.name: base.digest(base.regular(p)) for p in sorted(recovery.PROMPTS.iterdir()) if p.is_file()}


def prepare_round(record, archive, calls, original_history):
    """Keep the final recorded importance decision; isolate invalid choices."""
    items = []
    if record["selectionStatus"] == "SELECTED":
        for selection in record["selected"]:
            issue = selection["issueId"]
            draft = next(d for d in record["result"]["items"] if d["issueId"] == issue)
            checks = [c for c in record["result"]["verification"]["checks"] if c["targetId"].startswith(issue + ":")]
            items.append({"issueId": issue, "originalRank": selection["rank"], "status": "FACT_PASS",
                "selection": normalized(selection), "sourceSelectionRequestDigest": record["groupedSelectionRequestDigest"],
                "draft": normalized(draft), "draftSourceRequestDigest": record["result"]["generationRequestDigest"],
                "draftOrigin": "base", "verificationOrigin": "base",
                "verificationRequestDigest": record["result"]["verificationRequestDigest"],
                "verification": {"status": "PASS", "checks": checks},
                "noveltyRequestDigest": None, "noveltyDecision": None, "errors": []})
        return items
    key = record.get("groupedSelectionRequestDigest")
    if not key or not (calls / (key + ".complete.json")).exists():
        return []
    selection_reply, _ = reply(calls, key)
    candidates = grouped.build_grouped_candidates(archive, record)
    if record.get("identity", {}).get("selectionEvidencePolicy") is not None:
        import briefing_semantic_support as semantic
        require(record["identity"]["selectionEvidencePolicy"] == semantic.POLICY, "recovery_semantic_policy_unknown")
        candidates = semantic.apply(candidates, semantic.load(archive, calls.parent))
    # Sorting and thresholds are identical to the original selector. This only
    # prevents an invalid company mapping on one choice from discarding others.
    choices = sorted(selection_reply["selected"], key=lambda c: (
        -selection_reply["assessments"][c["issueId"]]["importance"],
        -selection_reply["assessments"][c["issueId"]]["priority"], c["issueId"]))
    used_docs, used_ids = set(), set()
    for index, choice in enumerate(choices):
        entry = {"issueId": choice["issueId"], "originalRank": index + 1, "status": "NEEDS_DRAFT",
            "sourceSelectionRequestDigest": key, "selection": None, "draft": None,
            "draftSourceRequestDigest": None, "draftOrigin": None, "verificationOrigin": None,
            "verificationRequestDigest": None, "verification": None,
            "noveltyRequestDigest": None, "noveltyDecision": None, "errors": []}
        try:
            subset = clone(selection_reply); subset["selected"] = [choice]
            frozen = grouped.freeze_grouped_selection(subset, candidates, record["identitySha256"], original_history)[0]
            docs = {s["documentId"] for s in frozen["sources"]}
            require(choice["issueId"] not in used_ids and not docs & used_docs, "recovery_duplicate_selection")
            used_ids.add(choice["issueId"]); used_docs |= docs
            entry["selection"] = frozen
        except ERRORS as error:
            entry.update(status="INVALID_SELECTION", errors=[str(error)])
        items.append(entry)
    # Reuse the earliest independently well-formed item, not the last whole-
    # batch repair. Provider text/citations are never edited on this path.
    completed = []
    for receipt in record["receipts"]:
        if receipt["stage"].endswith("_generation") and receipt.get("status") == "completed":
            completed.append(receipt)
    completed.sort(key=lambda r: (r["finishedAt"], r["requestDigest"]))
    for entry in items:
        if entry["selection"] is None:
            continue
        for receipt in completed:
            raw_reply, _ = reply(calls, receipt["requestDigest"])
            drafts = raw_reply.get("items", {})
            drafts = list(drafts.values()) if type(drafts) is dict else drafts
            draft = next((d for d in drafts if d.get("issueId") == entry["issueId"]), None)
            if draft is None:
                continue
            try:
                checked = recovery.validate_item(normalized(draft), entry["selection"])
            except ERRORS:
                continue
            entry.update(status="NEEDS_VERIFICATION", draft=checked, draftOrigin="base",
                         draftSourceRequestDigest=receipt["requestDigest"])
            break
    return items


def context_for(layer, record):
    return {"date": record["date"], "edition": record["edition"], "window": record["window"],
        "recoveryRunId": layer["runId"], "policyVersion": POLICY,
        "contextSha256": record["identitySha256"], "sourceFileSha256": layer["sourceFileSha256"],
        "clockFileSha256": layer["clockFileSha256"], "groupArchiveSha256": layer["groupArchiveSha256"],
        "baseBundleSha256": layer["baseBundleSha256"], "historicalSimulation": True,
        "operationalCollectionGate": False}


def cached_stage(path, invoke):
    # Re-run host checks against the client's immutable response cache. A local
    # stage-summary file is never itself an authority for a PASS decision.
    result = invoke()
    if path.exists():
        require(base.strict_load(base.regular(path)) == result, "recovery_stage_summary_changed")
        return result
    base.write_once(path, base.canonical(result))
    return result


def stage_facts(client, output, layer, record, entries, max_repairs):
    """This phase has no prior-round prose and may run across rounds in parallel."""
    entries = clone(entries)
    if record["selectionStatus"] == "SELECTED" or not entries:
        return entries
    context = context_for(layer, record)
    directory = output / (record["date"] + "-" + record["edition"])
    base.private_dir(directory)
    for attempt in range(max_repairs + 1):
        missing = [e for e in entries if e["selection"] is not None and e["status"] in {"NEEDS_DRAFT", "WITHHELD"}]
        if missing:
            # The writer accepts machine codes only. Supplying a different key
            # would silently erase repair hints and reuse the first bad request.
            prior = {e["issueId"]: {"codes": e["errors"]} for e in missing}
            generated = cached_stage(directory / (f"generation-{attempt}.json"), lambda: recovery.generate_items(
                client, [e["selection"] for e in missing], context, prior_failures=prior))
            by_id = {d["issueId"]: d for d in generated["items"]}
            for entry in missing:
                issue = entry["issueId"]
                if issue in by_id:
                    entry.update(status="NEEDS_VERIFICATION", draft=by_id[issue], draftOrigin="recovery",
                        draftSourceRequestDigest=generated["requestDigest"], errors=[])
                else:
                    entry.update(status="WITHHELD", errors=[generated.get("failures", {}).get(issue, "generation_item_missing")])
        pending = [e for e in entries if e["status"] == "NEEDS_VERIFICATION"]
        if pending:
            verified = cached_stage(directory / (f"verification-{attempt}.json"), lambda: recovery.verify_items(
                client, [e["selection"] for e in pending], [e["draft"] for e in pending], context))
            for entry in pending:
                issue = entry["issueId"]
                checks = [c for c in verified["checks"] if c["targetId"].startswith(issue + ":")]
                passed = verified["perIssueStatuses"].get(issue) == "PASS"
                entry.update(status="FACT_PASS" if passed else "WITHHELD", verificationOrigin="recovery",
                    verificationRequestDigest=verified["requestDigest"],
                    verification={"status": "PASS" if passed else "WITHHELD", "checks": checks},
                    errors=[] if passed else [verified.get("failures", {}).get(issue, "semantic_item_withheld")])
        if all(e["status"] in {"FACT_PASS", "INVALID_SELECTION"} for e in entries):
            break
    base.write_once(directory / "fact-items.json", base.canonical(entries))
    return entries


def result_projection(entries, receipts):
    selected, drafts, checks = [], [], []
    keys = set()
    for entry in entries:
        if entry["status"] != "PASS":
            continue
        rank = len(selected) + 1
        choice, draft = clone(entry["selection"]), clone(entry["draft"])
        choice["rank"] = draft["rank"] = rank
        selected.append(choice); drafts.append(draft)
        for check in entry["verification"]["checks"]:
            value = clone(check)
            if "flags" in value:
                value.update(value.pop("flags"))
            checks.append(value)
        keys |= {entry["draftSourceRequestDigest"], entry["verificationRequestDigest"], entry.get("noveltyRequestDigest")}
    if not selected:
        return selected, None
    used = [r for r in receipts if r["requestDigest"] in keys]
    generated_at = max(r["finishedAt"] for r in used)
    return selected, {"generatedAt": generated_at, "items": drafts,
        "verification": {"status": "PASS", "checks": checks,
            "meaning": "Current-text fact checks and prior-source novelty are separate; failed items withheld independently."},
        "generationRequestDigest": None, "verificationRequestDigest": None,
        "itemProvenance": [{k: e.get(k) for k in ("issueId", "originalRank", "draftOrigin", "draftSourceRequestDigest",
             "verificationOrigin", "verificationRequestDigest", "noveltyRequestDigest")} for e in entries if e["status"] == "PASS"],
        "usage": used}


def _run(args, transport=None):
    source = Path(args.base_bundle); raw = base.regular(source); bundle = base.strict_load(raw)
    require(bundle["schemaVersion"] == "zoop-briefing-grouped-simulation-v1" and "briefingRecovery" not in bundle,
            "recovery_requires_original_grouped_bundle")
    archive_raw = base.regular(source.parent / "grouped-issues.json")
    require(base.digest(archive_raw) == bundle["groupArchiveSha256"], "recovery_archive_binding")
    archive = base.strict_load(archive_raw)
    prompts = prompt_artifacts()
    identity = {"baseBundleSha256": base.digest(raw), "policyVersion": POLICY, "promptArtifacts": prompts,
        "userInboxRef": args.user_inbox_ref, "maximumPaidCallsIncludingPrior": args.max_calls}
    layer = {"schemaVersion": SCHEMA, **identity, "runId": "briefing-recovery-" + base.digest(base.canonical(identity))[:20],
        "sourceFileSha256": bundle["sourceFileSha256"], "clockFileSha256": bundle["clockFileSha256"],
        "groupArchiveSha256": bundle["groupArchiveSha256"],
        "authorization": {"scope": sim.MODE, "sourceSha256": bundle["sourceFileSha256"],
            "productionAuthorized": False, "userInboxRef": args.user_inbox_ref},
        "previousOutputPolicy": "Original generated prose is not new fact evidence; effective history uses prior published exact quotes only."}
    review_path = getattr(args, "review_holds", None)
    review_raw = base.regular(Path(review_path)) if review_path else None
    review_holds = base.strict_load(review_raw).get("holds", []) if review_raw else []
    require(type(review_holds) is list and all(type(h) is dict and h.get("roundId") and h.get("issueId")
            and h.get("code") and h.get("reason") for h in review_holds), "recovery_review_hold_invalid")
    layer["editorialReview"] = {"sha256": base.digest(review_raw) if review_raw else None, "holds": clone(review_holds),
        "meaning": "Explicit conservative editorial holds may remove items; they cannot grant a PASS or change model findings."}
    prepared, history = [], []
    for record in bundle["rounds"]:
        entries = prepare_round(record, archive, source.parent / "calls", history)
        prepared.append(entries)
        if record["selectionStatus"] == "SELECTED":
            history.extend(record["selected"])
    output = Path(args.output); base.private_dir(output)
    recordings_from = getattr(args, "recordings_from", None)
    if recordings_from:
        extra = Path(recordings_from)
        calls = output / "calls"; base.private_dir(calls)
        for path in sorted(extra.glob("*.json")):
            base.write_once(calls / path.name, base.regular(path))
    pending_count = len({p.name for directory in (source.parent / "calls", output / "calls")
                         for p in directory.glob("*.pending.json")})
    existing_recovery = sum(base.strict_load(base.regular(p)).get("stage", "").startswith("briefing_item_recovery_")
                            for p in (output / "calls").glob("*.complete.json"))
    plan = {"identity": identity, "runId": layer["runId"], "priorReservations": pending_count,
        "editorialReviewSha256": layer["editorialReview"]["sha256"],
        "remainingReservations": args.max_calls - pending_count,
        "existingCompletedRecoveryCalls": existing_recovery,
        "maximumAdditionalCalls": (sum(bool(entries) and r["selectionStatus"] != "SELECTED"
            for r, entries in zip(bundle["rounds"], prepared)) * 2 * (args.max_repairs + 1)
            + max(0, sum(bool(entries) for entries in prepared) - 1)),
        "rounds": [{"roundId": r["roundId"], "date": r["date"], "edition": r["edition"],
                    "baseStatus": r["selectionStatus"], "items": entries} for r, entries in zip(bundle["rounds"], prepared)]}
    require(pending_count <= args.max_calls, "recovery_budget_already_exceeded")
    # A resume may reuse all or some completed recovery requests. Their exact
    # digests are checked by the client; the same 400-slot write-ahead limit
    # remains authoritative even if changed drafts invalidate a cached request.
    require(existing_recovery or plan["maximumAdditionalCalls"] <= plan["remainingReservations"],
            "recovery_plan_exceeds_remaining_budget")
    if (output / "plan.json").exists():
        prior_plan = base.strict_load(base.regular(output / "plan.json"))
        require(prior_plan["identity"] == plan["identity"]
                and prior_plan.get("editorialReviewSha256") == plan["editorialReviewSha256"],
                "recovery_resume_plan_changed")
        # Resume the fixed input choice, rather than opportunistically choosing
        # another old draft after a host validator becomes more permissive.
        require(len(prior_plan["rounds"]) == len(plan["rounds"]), "recovery_resume_round_count")
        for frozen, fresh in zip(prior_plan["rounds"], plan["rounds"]):
            require(frozen["roundId"] == fresh["roundId"] and len(frozen["items"]) == len(fresh["items"]), "recovery_resume_round_binding")
            for old, new in zip(frozen["items"], fresh["items"]):
                require(all(old.get(k) == new.get(k) for k in ("issueId", "originalRank", "selection", "sourceSelectionRequestDigest")),
                        "recovery_resume_selection_changed")
                if old.get("draft") is not None:
                    recovery.validate_item(old["draft"], old["selection"])
        prepared = [r["items"] for r in prior_plan["rounds"]]
    else:
        base.write_once(output / "plan.json", base.canonical(plan))
    if not args.execute_authorized:
        return {"status": "OFFLINE", "runId": layer["runId"], "priorReservations": pending_count,
            "remainingReservations": args.max_calls - pending_count,
            "reusableDraftItems": sum(e["draft"] is not None for entries in prepared for e in entries), "newPaidCalls": 0}
    cache_only = getattr(args, "cache_only", False)
    require(args.user_inbox_ref and (args.key_file or transport or cache_only), "recovery_execution_authorization_required")
    base.write_once(output / "base-bundle-v2.json", raw)
    base.write_once(output / "grouped-issues.json", archive_raw)
    if review_raw:
        base.write_once(output / "editorial-review-holds.json", review_raw)
    calls = output / "calls"; base.private_dir(calls)
    for path in sorted((source.parent / "calls").glob("*.json")):
        base.write_once(calls / path.name, base.regular(path))
    if cache_only:
        def no_transport(_):
            raise AssertionError("cache-only replay attempted network transport")
        client = CacheOnlyRecoveryClient(output, no_transport, args.max_calls)
    else:
        client = recovery.RecoveryClient(output, transport or base.authenticated_transport(Path(args.key_file), timeout=600), args.max_calls)
    # Independent current-text checking across held rounds. No agent approval
    # blocks this work and no history from another future round enters it.
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(stage_facts, client, output, layer, record, entries, args.max_repairs)
                   for record, entries in zip(bundle["rounds"], prepared)]
        facts = [future.result() for future in futures]
    effective_history, recovered_rounds = [], []
    for record, entries in zip(bundle["rounds"], facts):
        directory = output / (record["date"] + "-" + record["edition"]); base.private_dir(directory)
        factual = [e for e in entries if e["status"] == "FACT_PASS"]
        if factual:
            novelty = cached_stage(directory / "novelty.json", lambda: recovery.assess_novelty(
                client, [e["selection"] for e in factual], effective_history, context_for(layer, record)))
            decisions = {d["issueId"]: d for d in novelty["decisions"]}
            for entry in factual:
                decision = decisions.get(entry["issueId"])
                okay = novelty["perIssueStatuses"].get(entry["issueId"]) == "PASS" and decision is not None
                entry.update(noveltyRequestDigest=novelty["requestDigest"], noveltyDecision=decision,
                    status="PASS" if okay else "REPEAT" if decision and decision["decision"] == "REPEAT" else "WITHHELD")
                if not okay:
                    entry["errors"].append(novelty.get("failures", {}).get(entry["issueId"], "novelty_not_supported"))
        for hold in review_holds:
            if hold["roundId"] == record["roundId"]:
                entry = next((e for e in entries if e["issueId"] == hold["issueId"]), None)
                require(entry is not None, "recovery_review_hold_unknown_issue")
                entry.update(status="WITHHELD", editorialHold=clone(hold))
                entry["errors"].append(hold["code"])
        receipts = client.receipts()
        selected, result = result_projection(entries, receipts)
        row = {"roundId": record["roundId"], "date": record["date"], "edition": record["edition"],
            "baseRoundSha256": base.digest(base.canonical(record)),
            "status": "SELECTED" if selected else "HELD_VALIDATION" if entries else "HELD_SOURCE_COVERAGE",
            "partial": bool(selected) and any(e["status"] != "PASS" for e in entries),
            "issues": entries, "selected": selected, "result": result,
            "resultSha256": base.digest(base.canonical(result)) if result else None}
        base.write_once(directory / "recovered-round.json", base.canonical(row)); recovered_rounds.append(row)
        for choice in selected:
            effective_history.append({"roundId": record["roundId"], "date": record["date"], "edition": record["edition"],
                "issueId": choice["issueId"], "sources": clone(choice["sources"])})
        print(json.dumps({"round": record["date"] + "-" + record["edition"], "status": row["status"],
                          "items": len(selected), "partial": row["partial"]}), flush=True)
    originals = {p.name.removesuffix(".pending.json") for p in (source.parent / "calls").glob("*.pending.json")}
    layer.update(rounds=recovered_rounds, receipts=[r for r in client.receipts() if r["requestDigest"] not in originals])
    result_bundle = clone(bundle); result_bundle["briefingRecovery"] = layer
    base.write_once(output / "bundle-v2.json", base.canonical(result_bundle))
    proof = {"status": "COMPLETE", "runId": layer["runId"], "priorReservations": pending_count,
        "newPaidCalls": len(client.new_calls), "totalReservations": len(list(calls.glob("*.pending.json"))),
        "unknownReservations": [r["requestDigest"] for r in client.receipts() if not r["usageKnown"]],
        "baseBundleUnchanged": base.regular(output / "base-bundle-v2.json") == raw,
        "oldRecordingsByteIdentical": all(base.regular(calls / p.name) == base.regular(p) for p in (source.parent / "calls").glob("*.json")),
        "publishedRounds": sum(r["status"] == "SELECTED" for r in recovered_rounds),
        "publishedItems": sum(len(r["selected"]) for r in recovered_rounds),
        "partialRounds": sum(r["partial"] for r in recovered_rounds),
        "rounds": [{k:r[k] for k in ("roundId", "date", "edition", "status", "partial")} | {
            "issues": [{"issueId": e["issueId"], "status": e["status"], "title": (e["draft"] or e["selection"] or {}).get("title"),
                        "errors": e["errors"]} for e in r["issues"]]} for r in recovered_rounds]}
    completed = output / "completion-proof.json"
    if completed.exists():
        prior_proof = base.strict_load(base.regular(completed))
        require(all(prior_proof[k] == value for k, value in proof.items()
                    if k not in {"newPaidCalls", "priorReservations"}), "recovery_completed_result_changed")
        base.write_once(output / "reuse-proof.json", base.canonical(proof))
    else:
        base.write_once(completed, base.canonical(proof))
    return proof


def run(args, transport=None):
    output = Path(args.output).resolve()
    source = Path(args.base_bundle).resolve().parent
    require(output != source and source not in output.parents and output not in source.parents, "recovery_separate_output_required")
    base.private_dir(output)
    lock = output / ".recovery-execution.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise sim.ReplayError("recovery_execution_locked") from error
    os.close(descriptor)
    try:
        # Own the complete reservation count/copy/allocate lifecycle across processes.
        return _run(args, transport)
    finally:
        lock.unlink(missing_ok=True)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("base-bundle", "output", "user-inbox-ref"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--key-file"); p.add_argument("--execute-authorized", action="store_true")
    p.add_argument("--recordings-from", help="Reuse immutable recordings from an earlier recovery attempt, including its budget reservations.")
    p.add_argument("--review-holds", help="Recorded editorial holds only remove uncertain items; they never create facts or approvals.")
    p.add_argument("--cache-only", action="store_true", help="Require completed immutable responses for every stage; no key or transport and no new reservations.")
    p.add_argument("--max-calls", type=int, choices=range(1, 401), default=400)
    p.add_argument("--max-repairs", type=int, choices=range(2), default=1)
    p.add_argument("--workers", type=int, choices=range(1, 4), default=3)
    return p


if __name__ == "__main__":
    try:
        print(json.dumps(run(parser().parse_args()), ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"status": "FAILED", "code": str(error) if isinstance(error, ERRORS) else type(error).__name__}))
        raise
