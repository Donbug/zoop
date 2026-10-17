#!/usr/bin/env python3
"""Explicit bounded quality recheck of selected historical cases; does not replace published rounds."""

import argparse
import importlib.util
from pathlib import Path
import sys

_spec = importlib.util.spec_from_file_location("_round_remediation_sim", Path(__file__).with_name("briefing_round_simulation.py"))
sim = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sim)
base = sim.base
DEFAULT_CASES = ("2026-10-03-evening", "2026-10-05-morning", "2026-10-06-morning",
                 "2026-10-08-morning", "2026-10-08-evening")


def baseline_assessments(baseline, original, pool):
    """Reuse paid importance only after checking exact source/context and raw responses."""
    client = sim.SimulationClient(baseline, lambda _: (_ for _ in ()).throw(base.ReplayError("baseline_never_sends")))
    values, receipts = [], []
    for receipt in original["receipts"]:
        if receipt["stage"] != "round_simulation_importance":
            continue
        key = receipt["requestDigest"]
        verified, response = client.inspect_recorded(key)
        data = base.strict_load(base.strict_load(base.regular(client.calls / (key + ".request.json")))["input"])
        if data.get("contextSha256") != original["identitySha256"]:
            raise base.ReplayError("remediation_assessment_context_mismatch")
        sources = {row["documentId"]: row for row in pool}
        if any(d.get("documentId") not in sources or d.get("bodySha256") != sources[d["documentId"]]["bodySha256"]
               for d in data.get("documents", [])):
            raise base.ReplayError("remediation_assessment_source_digest_mismatch")
        values.extend(base.normalize_assessments(base.output_of(response)["assessments"]))
        receipts.append(verified)
    expected = {row["documentId"] for row in pool}
    if base.assessment_coverage(values, expected) is not None:
        raise base.ReplayError("remediation_baseline_assessment_coverage_mismatch")
    return values, receipts


def run(args, transport=None):
    baseline, output = Path(args.baseline).resolve(), Path(args.output).resolve()
    if output == baseline or baseline in output.parents:
        raise base.ReplayError("remediation_output_must_be_separate")
    rows, unknown, source = sim.load_inputs(Path(args.sources), Path(args.clocks),
        Path(args.clock_html_root) if args.clock_html_root else None)
    bundle_bytes = base.regular(baseline / "bundle-v2.json")
    bundle = base.strict_load(bundle_bytes)
    if bundle.get("schemaVersion") != "zoop-briefing-round-simulation-v2" or bundle.get("mode") != sim.MODE \
            or bundle.get("sourceFileSha256") != source["sourceFileSha256"] \
            or bundle.get("clockFileSha256") != source["clockFileSha256"]:
        raise base.ReplayError("remediation_source_or_clock_mismatch")
    names = args.round or list(DEFAULT_CASES)
    if not names or len(names) > 5 or len(names) != len(set(names)):
        raise base.ReplayError("remediation_case_bound_or_duplicate")
    by_name = {r["date"] + "-" + r["edition"]: (i, r) for i, r in enumerate(bundle["rounds"])}
    if not set(names).issubset(by_name):
        raise base.ReplayError("remediation_unknown_round")
    plan = {"schemaVersion": "zoop-briefing-quality-recheck-v1", "qualityPolicy": sim.QUALITY_V2,
            "baselineBundleSha256": base.digest(bundle_bytes), "sourceFileSha256": source["sourceFileSha256"],
            "clockFileSha256": source["clockFileSha256"], "userInboxRef": args.user_inbox_ref,
            "rounds": names, "maxCalls": args.max_calls, "notAReplacementPublicationBundle": True}
    if not args.execute_authorized_recheck:
        return {**plan, "status": "OFFLINE", "newPaidCalls": 0}
    if not args.user_inbox_ref or not (args.key_file or transport):
        raise base.ReplayError("remediation_authorization_and_key_required")
    base.private_dir(output)
    base.save_json(output / "plan.json", plan)
    original_prompts = sim.PROMPTS
    snapshot = output / "prompts"
    base.private_dir(snapshot)
    for prompt in sorted(original_prompts.iterdir()):
        if prompt.is_file():
            base.write_once(snapshot / prompt.name, base.regular(prompt))
    import os
    lock = output / ".remediation.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise base.ReplayError("active_or_interrupted_remediation_requires_inspection") from error
    os.close(fd)
    sim.PROMPTS = snapshot
    client = sim.SimulationClient(output, transport or base.authenticated_transport(Path(args.key_file)), args.max_calls)
    results = []
    try:
        for name in names:
            index, original = by_name[name]
            directory = output / name
            base.private_dir(directory)
            binding = base.strict_load(base.regular(baseline / name / "round.binding.json"))
            if binding != {"identitySha256": original["identitySha256"], "roundSha256": base.digest(base.regular(baseline / name / "round.json"))} \
                    or base.strict_load(base.regular(baseline / name / "round.json")) != original:
                raise base.ReplayError("remediation_original_round_binding_mismatch")
            pool, input_sources, clock_refs, _, _ = sim.pool_for_round(rows, original, len(unknown))
            if input_sources != original["inputSources"] or clock_refs != original["clockRefs"]:
                raise base.ReplayError("remediation_input_population_mismatch")
            assessments, reused = baseline_assessments(baseline, original, pool)
            candidates = sim.helper("briefing_quality").catalog_candidates(sim.shortlist_round(assessments, pool))
            history = sim.helper("briefing_quality").published_history(bundle["rounds"][:index], original["window"]["from"])
            previous, previous_result = sim.previous_context(bundle["rounds"][index - 1] if index else None)
            identity = {**original["identity"], "qualityPolicy": sim.QUALITY_V2,
                        "baselineBundleSha256": plan["baselineBundleSha256"], "originalRoundId": original["roundId"],
                        "authorization": {"scope": sim.MODE, "sourceSha256": source["sourceFileSha256"],
                                          "userInboxRef": args.user_inbox_ref, "productionAuthorized": False},
                        "noveltyHistorySha256": base.digest(base.canonical(history)),
                        "promptArtifacts": {p.name: base.digest(base.regular(p)) for p in sorted(sim.PROMPTS.iterdir()) if p.is_file()}}
            recovery = None
            for receipt in original["receipts"]:
                if receipt.get("httpStatus") in {500, 502, 503, 504}:
                    if recovery is not None or receipt["stage"] != "round_simulation_selection":
                        raise base.ReplayError("remediation_only_one_selection_http_recovery_supported")
                    recovery = sim.helper("briefing_http_recovery").inspect_transient_failure(
                        baseline / "calls", receipt["requestDigest"], args.user_inbox_ref)
                    identity["operatorRecovery"] = recovery
            identity_sha = base.digest(base.canonical(identity))
            base.save_json(directory / "identity.json", identity)
            final_path = directory / "recheck.json"
            if final_path.exists():
                final_binding = base.strict_load(base.regular(directory / "recheck.binding.json"))
                if final_binding != {"identitySha256": identity_sha, "recheckSha256": base.digest(base.regular(final_path))}:
                    raise base.ReplayError("remediation_cached_recheck_digest_mismatch")
                saved = base.strict_load(base.regular(final_path))
                if saved.get("identitySha256") != identity_sha or saved.get("resultSha256") != \
                        (base.digest(base.canonical(saved["result"])) if saved.get("result") else None):
                    raise base.ReplayError("remediation_cached_result_binding_mismatch")
                results.append(saved)
                continue
            context = {**sim.model_context(identity, identity_sha, previous_result), "qualityPolicy": sim.QUALITY_V2,
                       "noveltyHistory": history}
            if recovery:
                context["operatorRecovery"] = recovery
            candidates, audit = sim.helper("briefing_novelty").filter_candidates(client, candidates, history, context)
            context["noveltyAudit"] = audit
            base.save_json(directory / "novelty-audit.json", audit)
            selected, _, _ = sim.choose_round(client, candidates, pool, context, identity_sha) if candidates else ([], [], False)
            base.save_json(directory / "selected.json", selected)
            result = sim.generate_round(client, selected, original["edition"], context, 1) if selected else None
            value = {"date": original["date"], "edition": original["edition"], "identitySha256": identity_sha,
                     "originalRoundId": original["roundId"], "originalStatus": original["selectionStatus"],
                     "assessmentReuse": {"policy": "same_source_and_raw_response_verified", "receipts": reused},
                     "noveltyAudit": audit, "operatorRecovery": recovery, "selected": selected, "result": result,
                     "resultSha256": base.digest(base.canonical(result)) if result else None,
                     "status": "PASS" if result and result["verification"]["status"] == "PASS" else "HELD_VALIDATION",
                     "receipts": sim.context_receipts(client, identity_sha), "published": False}
            base.save_json(final_path, value)
            base.save_json(directory / "recheck.binding.json", {"identitySha256": identity_sha,
                          "recheckSha256": base.digest(base.regular(final_path))})
            results.append(value)
            print(base.canonical({"round": name, "status": value["status"], "selected": len(selected),
                                  "excludedRepeats": sum(d["decision"] == "REPEAT" for d in audit["decisions"])}).decode(), flush=True)
        final = {**plan, "results": results, "receipts": client.receipts()}
        base.save_json(output / "recheck-bundle.json", final)
        return {"status": "COMPLETE", "cases": len(results), "pass": sum(r["status"] == "PASS" for r in results),
                "newPaidCalls": len(client.new_calls), "published": False, "output": str(output / "recheck-bundle.json")}
    finally:
        receipts = base.canonical(client.receipts())
        base.write_once(output / ("accounting-" + base.digest(receipts) + ".json"), receipts)
        lock.unlink(missing_ok=True)
        sim.PROMPTS = original_prompts


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    for flag in ("baseline", "output", "sources", "clocks", "user-inbox-ref"):
        p.add_argument("--" + flag, required=True)
    p.add_argument("--clock-html-root")
    p.add_argument("--key-file")
    p.add_argument("--round", action="append")
    p.add_argument("--max-calls", type=base.bounded(1, 30), default=24)
    p.add_argument("--execute-authorized-recheck", action="store_true")
    return p


if __name__ == "__main__":
    try:
        print(base.canonical(run(parser().parse_args())).decode())
    except (base.ReplayError, ValueError) as error:
        print(base.canonical({"status": "STOPPED", "reason": str(error)}).decode(), file=sys.stderr)
        raise SystemExit(2)
