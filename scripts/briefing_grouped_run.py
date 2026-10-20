#!/usr/bin/env python3
"""Select and generate per-round briefings from a private immutable issue archive."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import briefing_grouped_rounds as grouped

sim, base = grouped.sim, grouped.base


def prompt_artifacts():
    names = ["importance.md", "importance.schema.json", "selection.md", "selection.schema.json",
             "generation-morning.md", "generation-evening.md", "generation.schema.json", "verification.md", "verification.schema.json"]
    result = {n:base.digest(base.regular(sim.PROMPTS/n)) for n in names}
    result.update({"grouped-"+n:base.digest(base.regular(grouped.PROMPTS/n)) for n in
                   ["selection.md","selection.schema.json","generation-morning.md","generation-evening.md","verification.md"]})
    return result


def run(args, transport=None):
    archive_path, source_path, clock_path = Path(args.archive), Path(args.sources), Path(args.clocks)
    raw = base.regular(archive_path); archive = base.strict_load(raw); archive_sha = base.digest(raw)
    rows, unknown, source = sim.load_inputs(source_path, clock_path)
    if archive["sourceFileSha256"] != source["sourceFileSha256"] or archive["clockFileSha256"] != source["clockFileSha256"]:
        raise sim.ReplayError("grouped_run_source_binding_mismatch")
    prompts = prompt_artifacts()
    authorization = {"scope": sim.MODE, "sourceSha256": source["sourceFileSha256"], "userInboxRef": args.user_inbox_ref,
                     "productionAuthorized": False, "groupArchiveSha256": archive_sha}
    run_identity = {"source":source,"archiveSha256":archive_sha,"promptArtifacts":prompts,"authorization":authorization}
    run_id = "grouped-round-simulation-"+base.digest(base.canonical(run_identity))[:20]
    prepared = []
    for spec in sim.windows():
        pool, inputs, clocks, duplicates, coverage = sim.pool_for_round(rows,spec,len(unknown))
        candidates = grouped.build_grouped_candidates(archive,spec)
        prepared.append((spec,inputs,clocks,duplicates,coverage,candidates))
    plan = {"runId":run_id,"groupArchiveSha256":archive_sha,"maximumPaidCalls":args.max_calls,
            "rounds":[{**spec,"candidateIssues":len(candidates)} for spec,_,_,_,_,candidates in prepared]}
    if not args.execute_authorized:
        return {**plan,"status":"OFFLINE","newPaidCalls":0}
    if not args.user_inbox_ref or not (args.key_file or transport):
        raise sim.ReplayError("grouped_generation_authorization_required")
    output=Path(args.output);base.private_dir(output)
    base.save_json(output/"plan.json",plan)
    base.write_once(output/"grouped-issues.json",raw)
    # Copy original provider recordings, never fabricated/relabelled replay receipts.
    calls=output/"calls";base.private_dir(calls)
    for path in sorted((archive_path.parent/"calls").glob("*.json")):
        base.write_once(calls/path.name,base.regular(path))
    client=grouped.GroupedSimulationClient(output,transport or base.authenticated_transport(Path(args.key_file)),args.max_calls)
    rounds=[];published_history=[]
    for spec,inputs,clocks,duplicates,coverage,candidates in prepared:
        previous, previous_result=sim.previous_context(rounds[-1] if rounds else None)
        identity={"mode":sim.MODE,"runId":run_id,"sourceFileSha256":source["sourceFileSha256"],
                  "clockFileSha256":source["clockFileSha256"],**spec,"contextVersion":"round-simulation-v1",
                  "candidateInputSha256":base.digest(base.canonical(inputs)),"promptArtifacts":prompts,
                  "previous":previous,"operationalCollectionGate":False,"authorization":authorization,
                  "groupArchiveSha256":archive_sha,
                  "baseline":{"from":sim.BASELINE,"meaning":"simulation_baseline_not_service_first_round"}}
        identity_sha=base.digest(base.canonical(identity));round_id="sim-"+spec["date"]+"-"+spec["edition"]+"-"+identity_sha[:12]
        directory=output/(spec["date"]+"-"+spec["edition"]);base.private_dir(directory)
        path=directory/"round.json"
        if path.exists():
            record=base.strict_load(base.regular(path))
            if record["identity"]!=identity or (record["result"] and base.digest(base.canonical(record["result"]))!=record["resultSha256"]):
                raise sim.ReplayError("grouped_round_reuse_conflict")
            rounds.append(record)
            if record["selectionStatus"]=="SELECTED":published_history.extend(record["selected"])
            continue
        context=sim.model_context(identity,identity_sha,previous_result)
        context["priorSelectedIssues"]=[{"issueId":item["issueId"],"title":item["title"],"sources":item["sources"]}
                                        for item in published_history]
        record={"roundId":round_id,**spec,"identity":identity,"identitySha256":identity_sha,
                "inputSources":inputs,"clockRefs":clocks,"sourceCoverage":coverage,"discardedDuplicateBodies":duplicates,
                "previous":previous,"selected":[],"result":None,"resultSha256":None,"receipts":[],
                "groupedSelectionRequestDigest":None}
        if not candidates:
            record["selectionStatus"]="HELD_SOURCE_COVERAGE"
        else:
            data=grouped.grouped_selection_data(candidates,context,published_history)
            selection_digest=client.request_digest(grouped.SELECTION_STAGE,data,"selection.md","selection.schema.json",max_output=12000,
                                                   schema_override=grouped.selection_schema(candidates))
            record["groupedSelectionRequestDigest"]=selection_digest
            try:
                selected=grouped.choose_grouped_round(client,candidates,context,identity_sha,published_history)
                base.save_json(directory/"selected.json",selected)
                if not selected:
                    record["selectionStatus"]="HELD_SOURCE_COVERAGE"
                else:
                    # Generation receives stable issue/role/evidence records; no raw-news re-extraction.
                    result=sim.generate_round(client,selected,spec["edition"],context,args.max_repairs)
                    base.save_json(directory/"generation-result.json",result)
                    if result["verification"]["status"]=="PASS":
                        record.update(selectionStatus="SELECTED",selected=selected,result=result)
                    else:
                        record["selectionStatus"]="HELD_VALIDATION"
            except sim.ReplayError as error:
                # Preserve the exact unsuccessful paid response and continue only after known completed calls.
                if client.stopped.is_set():raise
                record["selectionStatus"]="HELD_VALIDATION";record["groupedValidationFailure"]=str(error)
        record["receipts"]=sim.context_receipts(client,identity_sha)
        if record["result"]:
            final={record["result"]["generationRequestDigest"],record["result"]["verificationRequestDigest"]}
            record["result"]["usage"]=[r for r in record["receipts"] if r["requestDigest"] in final]
            record["resultSha256"]=base.digest(base.canonical(record["result"]))
            published_history.extend(record["selected"])
        base.save_json(path,record);rounds.append(record)
        print(json.dumps({"round":spec["date"]+"-"+spec["edition"],"status":record["selectionStatus"],"issues":len(record["selected"])}),flush=True)
    receipts=client.receipts()
    # Files for grouping calls share storage, but their ownership is explicit and distinct.
    group_keys={r["requestDigest"] for r in archive["receipts"]}
    round_receipts=[r for r in receipts if r["requestDigest"] not in group_keys]
    bundle={"schemaVersion":"zoop-briefing-grouped-simulation-v1","mode":sim.MODE,"runId":run_id,
            "sourceFileSha256":source["sourceFileSha256"],"clockFileSha256":source["clockFileSha256"],
            "authorization":authorization,"retrospectiveBodies":True,"operationalCollectionGate":False,"graphVersion":None,
            "groupArchiveSha256":archive_sha,"groupingReceipts":archive["receipts"],"rounds":rounds,"receipts":round_receipts,
            "marketSummary":{"status":"unavailable","reason":"Grouped-issue replay; new market summary not generated."},
            "marketVariables":{"status":"unavailable","reason":"Market snapshots are separate from issue regrouping."},
            "sinceMorning":{"status":"unavailable","reason":"No operational forecast evaluation for late-body replay."}}
    base.save_json(output/"bundle-v2.json",bundle)
    return {**plan,"status":"COMPLETE","newPaidCalls":len(client.new_calls),
            "selectedRounds":sum(r["selectionStatus"]=="SELECTED" for r in rounds),
            "selectedIssues":sum(len(r["selected"]) for r in rounds)}


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ["archive","sources","clocks","output","user-inbox-ref"]:p.add_argument("--"+name,required=True)
    p.add_argument("--key-file");p.add_argument("--execute-authorized",action="store_true")
    p.add_argument("--max-calls",type=int,choices=range(1,513),default=400)
    p.add_argument("--max-repairs",type=int,choices=range(2),default=1)
    return p


if __name__=="__main__":
    try:print(json.dumps(run(parser().parse_args()),ensure_ascii=False))
    except Exception as error:
        print(json.dumps({"status":"FAILED","code":str(error) if isinstance(error,sim.ReplayError) else type(error).__name__}))
        raise SystemExit(1)
