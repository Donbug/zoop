"""Run files: the record format a model/tool adapter must emit. Strictly validated before any scoring."""
from __future__ import annotations

from typing import Any

from .bench import Bench, triple_key
from .contracts import (
    FAMILIES, MERGE_PRED, OUTCOMES, PROVENANCE_KINDS, SCHEMA_RUN, SPLITS, STATUSES, TASK_KINDS, choice, day, flag,
    id_list, instant, integer, mapping, reject, sequence, text, unique,
)
from .timing import parse_trace

_ENTITY_FIELDS = ("subject", "predicate", "object")
CONFIG_SCALARS = (str, int, float, bool, type(None))


def _provenance(raw: Any) -> dict[str, Any]:
    prov = mapping(raw, "run.provenance", ("kind", "executionMode", "recorder", "recordedAt"), ("controlKind", "note"))
    kind = choice(prov["kind"], tuple(PROVENANCE_KINDS), "run.provenance.kind")
    mode = choice(prov["executionMode"], PROVENANCE_KINDS[kind], "run.provenance.executionMode")
    text(prov["recorder"], "run.provenance.recorder")
    if kind == "real_measured":
        instant(prov["recordedAt"], "run.provenance.recordedAt")
        if "controlKind" in prov:
            reject("provenance_invalid", "controlKind is only valid for authored_control runs")
    elif prov["recordedAt"] is not None:
        reject("provenance_invalid", "an authored control has no recording time: recordedAt must be null")
    elif "controlKind" not in prov:
        reject("provenance_invalid", "authored_control runs must state their controlKind")
    return {**prov, "executionMode": mode}


def _system(raw: Any, kind: str, tasks: list[str]) -> dict[str, Any]:
    sysd = mapping(raw, "run.system",
                   ("systemId", "family", "model", "config", "promptRevision", "toolRevision", "schemaRevision", "graphRevision"),
                   ("capabilities", "description"))
    text(sysd["systemId"], "run.system.systemId")
    family = choice(sysd["family"], FAMILIES, "run.system.family")
    model = sysd["model"]
    if model is not None:
        model = mapping(model, "run.system.model", ("provider", "name", "version"))
        for key in model:
            text(model[key], f"run.system.model.{key}")
    if family == "no_model_deterministic" and model is not None:
        reject("provenance_invalid", "a no_model_deterministic system cannot declare a model")
    if family == "agent_graphrag" and model is None:
        reject("provenance_invalid", "an agent_graphrag system must declare its model")
    config = sysd["config"]
    if not isinstance(config, dict):
        reject("malformed", "run.system.config: expected an object")
    for key, value in config.items():
        if not isinstance(value, CONFIG_SCALARS) or (isinstance(value, float) and value != value):
            reject("malformed", f"run.system.config.{key}: only scalar values are allowed")
    for key in ("promptRevision", "toolRevision", "graphRevision"):
        text(sysd[key], f"run.system.{key}", nullable=True)
    text(sysd["schemaRevision"], "run.system.schemaRevision")
    if kind == "real_measured":
        if sysd["toolRevision"] is None:
            reject("provenance_invalid", "real_measured runs must record toolRevision")
        if model is not None and sysd["promptRevision"] is None:
            reject("provenance_invalid", "a run with a model must record promptRevision")
    capabilities = None
    if "qa" in tasks:
        capabilities = mapping(sysd.get("capabilities"), "run.system.capabilities (required when qa is scored)", ("retrieval", "path", "citations"))
        for key in capabilities:
            flag(capabilities[key], f"run.system.capabilities.{key}")
    return {**sysd, "model": model, "capabilities": capabilities, "config": dict(config)}


def _edge(raw: Any, where: str, with_citations: bool) -> dict[str, Any]:
    optional = ("validFrom", "validTo", "status") + (("citations",) if with_citations else ())
    item = mapping(raw, where, _ENTITY_FIELDS, optional)
    out = {key: text(item[key], f"{where}.{key}") for key in _ENTITY_FIELDS}
    out["validFrom"] = day(item.get("validFrom"), f"{where}.validFrom")
    out["validTo"] = day(item.get("validTo"), f"{where}.validTo")
    out["status"] = choice(item.get("status", "asserted"), ("asserted", "disputed"), f"{where}.status")
    if with_citations:
        out["citations"] = id_list(item.get("citations", []), f"{where}.citations")
    return out


def _unique_by(items: list[dict[str, Any]], key: str, where: str) -> None:
    unique([item[key] for item in items], where, "duplicate_item")


def _check_graph_scope(bench: Bench, case_id: str, output: dict[str, Any], where: str) -> None:
    """Merge decisions are closed over this task's candidate pairs; edges are one-to-one with canonical triples.
    (Same endpoints with another predicate, or a directed predicate in the other direction, stay distinct edges.)"""
    decisions = output["mergeDecisions"]
    if decisions is not None:
        asked = {pair["pairId"] for pair in bench.graph_tasks[case_id]["mergeCandidates"]}
        extra = sorted(set(decisions) - asked)
        if extra:
            reject("unmatched_item", f"{where}: mergeDecisions name pair(s) {extra} that are not candidates of task {case_id!r}")
    seen: set[tuple[str, str, str]] = set()
    for edge in output["edges"] or []:
        key = triple_key(bench.predicates, edge["subject"], edge["predicate"], edge["object"])
        if key in seen:
            reject("duplicate_item", f"{where}: edge {key} is emitted more than once (undirected predicates compare endpoints unordered)")
        seen.add(key)


def _graph_output(raw: Any, where: str) -> dict[str, Any]:
    out = mapping(raw, where, (), ("entityLinks", "events", "mergeDecisions", "edges"))
    norm: dict[str, Any] = {"entityLinks": None, "events": None, "mergeDecisions": None, "edges": None}
    if "entityLinks" in out:
        links = [mapping(i, f"{where}.entityLinks[]", ("mentionId", "entityId")) for i in sequence(out["entityLinks"], f"{where}.entityLinks")]
        for item in links:
            text(item["mentionId"], "mentionId")
            text(item["entityId"], "entityId", nullable=True)
        _unique_by(links, "mentionId", f"{where}.entityLinks")
        norm["entityLinks"] = {i["mentionId"]: i["entityId"] for i in links}
    if "events" in out:
        events = [mapping(i, f"{where}.events[]", ("eventMentionId", "eventType"), ("eventDate",)) for i in sequence(out["events"], f"{where}.events")]
        for item in events:
            text(item["eventMentionId"], "eventMentionId")
            text(item["eventType"], "eventType")
            day(item.get("eventDate"), "eventDate")
        _unique_by(events, "eventMentionId", f"{where}.events")
        norm["events"] = {i["eventMentionId"]: {"eventType": i["eventType"], "eventDate": i.get("eventDate")} for i in events}
    if "mergeDecisions" in out:
        merges = [mapping(i, f"{where}.mergeDecisions[]", ("pairId", "decision")) for i in sequence(out["mergeDecisions"], f"{where}.mergeDecisions")]
        for item in merges:
            text(item["pairId"], "pairId")
            choice(item["decision"], MERGE_PRED, "decision")
        _unique_by(merges, "pairId", f"{where}.mergeDecisions")
        norm["mergeDecisions"] = {i["pairId"]: i["decision"] for i in merges}
    if "edges" in out:
        edges = [_edge(i, f"{where}.edges[{n}]", True) for n, i in enumerate(sequence(out["edges"], f"{where}.edges"))]
        norm["edges"] = edges
    return norm


def _qa_output(raw: Any, where: str, capabilities: dict[str, bool]) -> dict[str, Any]:
    out = mapping(raw, where, ("outcome",), ("abstainReason", "answerEntities", "facts", "citations", "retrieved", "path", "answerText"))
    outcome = choice(out["outcome"], OUTCOMES, f"{where}.outcome")
    norm: dict[str, Any] = {
        "outcome": outcome, "abstainReason": text(out.get("abstainReason"), f"{where}.abstainReason", nullable=True),
        "answerEntities": id_list(out.get("answerEntities", []), f"{where}.answerEntities"),
        "facts": [_edge(i, f"{where}.facts[]", False) for i in sequence(out.get("facts", []), f"{where}.facts")],
        "citations": None, "retrieved": None, "path": None,
        "answerText": text(out.get("answerText"), f"{where}.answerText", nullable=True),
    }
    if outcome != "answered" and (norm["answerEntities"] or norm["facts"]):
        reject("record_inconsistent", f"{where}: {outcome} must not carry answerEntities or facts")
    if outcome != "abstained" and norm["abstainReason"] is not None:
        reject("record_inconsistent", f"{where}: abstainReason is only valid with outcome abstained")
    for key, capability in (("citations", "citations"), ("retrieved", "retrieval")):
        if key in out:
            if not capabilities[capability]:
                reject("capability_contradiction", f"{where}: emits {key} but system.capabilities.{capability} is false")
            norm[key] = id_list(out[key], f"{where}.{key}")
    if "path" in out:
        if not capabilities["path"]:
            reject("capability_contradiction", f"{where}: emits path but system.capabilities.path is false")
        norm["path"] = [_edge(i, f"{where}.path[]", False) for i in sequence(out["path"], f"{where}.path")]
        if any(step["validFrom"] or step["validTo"] or step["status"] != "asserted" for step in norm["path"]):
            reject("malformed", f"{where}.path: steps are bare triples (no validity or status)")
    return norm


def parse_run(raw: Any, bench: Bench) -> dict[str, Any]:
    top = mapping(raw, "run", ("schema", "runId", "provenance", "corpus", "system", "records"), ("label", "timingContext"))
    if top["schema"] != SCHEMA_RUN:
        reject("schema_mismatch", f"run: schema must be {SCHEMA_RUN}")
    run_id = text(top["runId"], "run.runId")
    prov = _provenance(top["provenance"])
    corpus = mapping(top["corpus"], "run.corpus", ("corpusId", "corpusRevision", "goldRevision", "split", "tasks"), ("inputsSha256",))
    split = choice(corpus["split"], SPLITS, "run.corpus.split")
    tasks = id_list(corpus["tasks"], "run.corpus.tasks", 1)
    for task in tasks:
        choice(task, TASK_KINDS, "run.corpus.tasks[]")
    expected = {"corpusId": bench.corpus_id, "corpusRevision": bench.corpus_revision, "goldRevision": bench.gold_revision}
    if corpus.get("inputsSha256") is not None:
        expected["inputsSha256"] = bench.inputs_sha256
    for key, value in expected.items():
        if corpus.get(key) != value:
            reject("corpus_mismatch", f"run.corpus.{key} is {corpus.get(key)!r} but the loaded corpus has {value!r}")
    system = _system(top["system"], prov["kind"], tasks)
    context = None
    if "timingContext" in top:
        context = mapping(top["timingContext"], "run.timingContext", ("concurrency", "warmup"), ("environment",))
        integer(context["concurrency"], "run.timingContext.concurrency", 1)
        choice(context["warmup"], ("cold", "warm", "unknown"), "run.timingContext.warmup")
        text(context.get("environment"), "run.timingContext.environment", nullable=True)

    records: dict[tuple[str, str], dict[str, Any]] = {}
    for index, item in enumerate(sequence(top["records"], "run.records")):
        where = f"run.records[{index}]"
        item = mapping(item, where, ("task", "caseId", "status"), ("output", "detail", "trace"))
        task = choice(item["task"], TASK_KINDS, f"{where}.task")
        case_id = text(item["caseId"], f"{where}.caseId")
        key = (task, case_id)
        if key in records:
            reject("duplicate_record", f"{where}: duplicate record for {task} case {case_id!r}")
        if task not in tasks:
            reject("unmatched_case", f"{where}: task {task!r} is not declared in run.corpus.tasks")
        if case_id not in set(bench.cases(task, split)):
            reject("unmatched_case", f"{where}: {task} case {case_id!r} is not in the {split} split of this corpus")
        status = choice(item["status"], STATUSES, f"{where}.status")
        if status == "ok":
            if "output" not in item or "detail" in item:
                reject("record_inconsistent", f"{where}: status ok requires output and forbids detail")
            output = (_graph_output(item["output"], f"{where}.output") if task == "graph"
                      else _qa_output(item["output"], f"{where}.output", system["capabilities"]))
            if task == "graph":
                _check_graph_scope(bench, case_id, output, where)
        else:
            if "output" in item or "detail" not in item:
                reject("record_inconsistent", f"{where}: status {status} requires detail and forbids output")
            text(item["detail"], f"{where}.detail")
            output = None
        records[key] = {"status": status, "output": output,
                        "trace": parse_trace(item["trace"], f"{where}.trace") if "trace" in item else None}
    return {"runId": run_id, "label": top.get("label"), "provenance": prov,
            "corpus": {**corpus, "tasks": tasks}, "system": system, "timingContext": context, "records": records}
