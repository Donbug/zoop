"""Corpus (system-visible), tasks (system-visible) and gold (withheld) loading and integrity checks."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import (
    EDGE_STATUSES, MERGE_GOLD, MERGE_KINDS, OUTCOMES, QUESTION_KINDS, SCHEMA_CORPUS, SCHEMA_GOLD, SCHEMA_TASKS,
    SPLITS, choice, day, flag, free_mapping, id_list, integer, mapping, read_json, reject, sequence, text, unique,
)

DEFAULT_CORPUS = Path(__file__).resolve().parent.parent / "corpus" / "zoop-bench-v1"
FILES = ("corpus.json", "tasks.json", "gold.json")


def triple_key(predicates: dict[str, bool], subject: str, predicate: str, obj: str) -> tuple[str, str, str]:
    """Identity of an edge: direction matters for directed predicates, endpoints are sorted for undirected ones.
    Predicates outside the registry are treated as directed (a system's invented predicate never matches gold)."""
    if predicates.get(predicate, True):
        return (subject, predicate, obj)
    first, second = sorted((subject, obj))
    return (first, predicate, second)


@dataclass(frozen=True)
class Bench:
    directory: Path
    corpus_id: str
    corpus_revision: str
    gold_revision: str
    inputs_sha256: str  # corpus.json + tasks.json: exactly what a system may see
    gold_sha256: str
    gold_provenance: dict[str, Any]
    entities: dict[str, str]
    passages: dict[str, str]  # passageId -> docId
    doc_split: dict[str, str]
    predicates: dict[str, bool]  # name -> directed
    graph_tasks: dict[str, dict[str, Any]]
    questions: dict[str, dict[str, Any]]
    gold_graph: dict[str, dict[str, Any]]
    gold_questions: dict[str, dict[str, Any]]
    edges: dict[str, dict[str, Any]]
    edge_by_triple: dict[tuple[str, str, str], str]

    def cases(self, task: str, split: str) -> list[str]:
        source = self.graph_tasks if task == "graph" else self.questions
        return [key for key, item in source.items() if item["split"] == split]


def walk_steps(bench: Bench, anchor: str, steps: list[dict[str, Any]]):
    """Resolve path steps (edges in assertion direction) against the gold graph and walk them from `anchor`.
    A step may be traversed against its assertion direction (upstream questions); it may never be reversed
    as an *edge* (a directed edge asserted backwards is not in the graph).
    Returns (valid, resolved gold edge ids, end entity | None, failure reason | None)."""
    if not steps:
        return False, [], None, "empty"
    resolved: list[str] = []
    reason = None
    for step in steps:
        key = triple_key(bench.predicates, step["subject"], step["predicate"], step["object"])
        edge_id = bench.edge_by_triple.get(key)
        if edge_id is not None:
            resolved.append(edge_id)
        elif reason is None:
            backwards = (step["object"], step["predicate"], step["subject"]) in bench.edge_by_triple
            reason = "reversed_edge" if bench.predicates.get(step["predicate"], True) and backwards else "edge_not_in_graph"
    if reason:
        return False, resolved, None, reason
    current = anchor
    for step in steps:
        if step["subject"] == current:
            current = step["object"]
        elif step["object"] == current:
            current = step["subject"]
        else:
            return False, resolved, None, "disconnected"
    return True, resolved, current, None


def _split(value: Any, where: str) -> str:
    return choice(value, SPLITS, where)


def load_bench(directory: Path | str | None = None) -> Bench:
    base = Path(directory) if directory else DEFAULT_CORPUS
    raws = {name: read_json(base / name) for name in FILES}
    digests = {name: hashlib.sha256((base / name).read_bytes()).hexdigest() for name in FILES}
    inputs_sha = hashlib.sha256(
        (digests["corpus.json"] + digests["tasks.json"]).encode("ascii")).hexdigest()

    corpus = mapping(raws["corpus.json"], "corpus.json", ("schema", "corpusId", "corpusRevision", "provenance", "entities", "documents"))
    if corpus["schema"] != SCHEMA_CORPUS:
        reject("schema_mismatch", f"corpus.json: schema must be {SCHEMA_CORPUS}")
    corpus_id = text(corpus["corpusId"], "corpus.corpusId")
    corpus_revision = text(corpus["corpusRevision"], "corpus.corpusRevision")
    mapping(corpus["provenance"], "corpus.provenance", ("authored", "synthetic", "note"))

    entities: dict[str, str] = {}
    ent_items = sequence(corpus["entities"], "corpus.entities", 1)
    for index, item in enumerate(ent_items):
        item = mapping(item, f"corpus.entities[{index}]", ("entityId", "name", "type"))
        entities[text(item["entityId"], "entityId")] = text(item["name"], "entity.name")
        text(item["type"], "entity.type")
    unique([item["entityId"] for item in ent_items], "corpus.entities")

    passages: dict[str, str] = {}
    docs: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(sequence(corpus["documents"], "corpus.documents", 1)):
        where = f"corpus.documents[{index}]"
        item = mapping(item, where, ("docId", "publishedAt", "source", "originFamily", "passages"))
        doc_id = text(item["docId"], f"{where}.docId")
        if doc_id in docs:
            reject("malformed", f"{where}: duplicate docId {doc_id!r}")
        day(item["publishedAt"], f"{where}.publishedAt", nullable=False)
        text(item["source"], f"{where}.source")
        text(item["originFamily"], f"{where}.originFamily")
        docs[doc_id] = item
        for pindex, passage in enumerate(sequence(item["passages"], f"{where}.passages", 1)):
            passage = mapping(passage, f"{where}.passages[{pindex}]", ("passageId", "text"))
            pid = text(passage["passageId"], "passageId")
            text(passage["text"], f"passage {pid}")
            if pid in passages:
                reject("malformed", f"duplicate passageId {pid!r}")
            passages[pid] = doc_id

    tasks = mapping(raws["tasks.json"], "tasks.json", ("schema", "corpusId", "corpusRevision", "predicates", "graphTasks", "questions"))
    gold = mapping(raws["gold.json"], "gold.json", ("schema", "corpusId", "corpusRevision", "goldRevision", "provenance", "graph", "questions"))
    if tasks["schema"] != SCHEMA_TASKS or gold["schema"] != SCHEMA_GOLD:
        reject("schema_mismatch", "tasks.json/gold.json schema mismatch")
    for name, item in (("tasks.json", tasks), ("gold.json", gold)):
        if item["corpusId"] != corpus_id or item["corpusRevision"] != corpus_revision:
            reject("revision_mismatch", f"{name}: corpusId/corpusRevision differ from corpus.json")
    gold_revision = text(gold["goldRevision"], "gold.goldRevision")
    gprov = mapping(gold["provenance"], "gold.provenance", ("authoredBy", "synthetic", "adjudicated", "annotators", "note"))
    text(gprov["authoredBy"], "gold.provenance.authoredBy")
    flag(gprov["synthetic"], "gold.provenance.synthetic")
    flag(gprov["adjudicated"], "gold.provenance.adjudicated")
    integer(gprov["annotators"], "gold.provenance.annotators")

    predicates: dict[str, bool] = {}
    for name, spec in free_mapping(tasks["predicates"], "tasks.predicates").items():
        predicates[name] = flag(mapping(spec, f"tasks.predicates.{name}", ("directed",))["directed"], f"tasks.predicates.{name}.directed")
    if not predicates:
        reject("malformed", "tasks.predicates: empty registry")

    graph_tasks: dict[str, dict[str, Any]] = {}
    mention_ids: dict[str, str] = {}
    mention_kind: dict[str, str] = {}
    pair_ids: set[str] = set()
    doc_owner: dict[str, str] = {}
    doc_split: dict[str, str] = {}
    for index, item in enumerate(sequence(tasks["graphTasks"], "tasks.graphTasks", 1)):
        where = f"tasks.graphTasks[{index}]"
        item = mapping(item, where, ("taskId", "split", "docIds", "entityMentions", "eventMentions", "mergeCandidates"))
        tid = text(item["taskId"], f"{where}.taskId")
        if tid in graph_tasks:
            reject("malformed", f"{where}: duplicate taskId {tid!r}")
        split = _split(item["split"], f"{where}.split")
        for doc_id in id_list(item["docIds"], f"{where}.docIds", 1):
            if doc_id not in docs:
                reject("dangling_reference", f"{where}: unknown docId {doc_id!r}")
            if doc_id in doc_owner:
                reject("split_leakage", f"{where}: document {doc_id!r} already belongs to task {doc_owner[doc_id]!r}")
            doc_owner[doc_id] = tid
            doc_split[doc_id] = split
        local_docs = set(item["docIds"])
        local: dict[str, set[str]] = {"entity": set(), "event": set()}
        for kind, field, idkey in (("entity", "entityMentions", "mentionId"), ("event", "eventMentions", "eventMentionId")):
            for mindex, mention in enumerate(sequence(item[field], f"{where}.{field}")):
                mention = mapping(mention, f"{where}.{field}[{mindex}]", (idkey, "passageId", "surface"))
                mid = text(mention[idkey], f"{field}.{idkey}")
                if mid in mention_ids:
                    reject("malformed", f"{where}: mention id {mid!r} is not unique across tasks")
                if passages.get(text(mention["passageId"], "passageId")) not in local_docs:
                    reject("dangling_reference", f"{where}: {mid!r} cites a passage outside the task's documents")
                text(mention["surface"], "surface")
                mention_ids[mid] = tid
                mention_kind[mid] = kind
                local[kind].add(mid)
        for pindex, pair in enumerate(sequence(item["mergeCandidates"], f"{where}.mergeCandidates")):
            pair = mapping(pair, f"{where}.mergeCandidates[{pindex}]", ("pairId", "kind", "a", "b"))
            pid = text(pair["pairId"], "pairId")
            if pid in pair_ids:
                reject("malformed", f"duplicate pairId {pid!r}")
            pair_ids.add(pid)
            kind = choice(pair["kind"], MERGE_KINDS, f"pair {pid}.kind")
            if pair["a"] == pair["b"] or pair["a"] not in local[kind] or pair["b"] not in local[kind]:
                reject("dangling_reference", f"{where}: pair {pid!r} needs two distinct {kind} mentions of the same task")
        graph_tasks[tid] = {**item, "split": split}
    for doc_id in docs:
        if doc_id not in doc_owner:
            reject("malformed", f"document {doc_id!r} belongs to no graph task (orphan)")

    families: dict[str, str] = {}
    for doc_id, item in docs.items():
        family_split = families.setdefault(item["originFamily"], doc_split[doc_id])
        if family_split != doc_split[doc_id]:
            reject("split_leakage", f"originFamily {item['originFamily']!r} spans dev and test")

    questions: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(sequence(tasks["questions"], "tasks.questions", 1)):
        where = f"tasks.questions[{index}]"
        item = mapping(item, where, ("questionId", "split", "text", "asOf", "anchorEntity"))
        qid = text(item["questionId"], f"{where}.questionId")
        if qid in questions:
            reject("malformed", f"{where}: duplicate questionId {qid!r}")
        text(item["text"], f"{where}.text")
        day(item["asOf"], f"{where}.asOf")
        if item["anchorEntity"] not in entities:
            reject("dangling_reference", f"{where}: unknown anchorEntity")
        questions[qid] = {**item, "split": _split(item["split"], f"{where}.split")}

    # ---- gold ----
    gold_graph: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    edge_split: dict[str, str] = {}
    edge_by_triple: dict[tuple[str, str, str], str] = {}
    split_entities: dict[str, set[str]] = {"dev": set(), "test": set()}
    for index, item in enumerate(sequence(gold["graph"], "gold.graph", 1)):
        where = f"gold.graph[{index}]"
        item = mapping(item, where, ("taskId", "entityLinks", "events", "merges", "edges"))
        tid = item["taskId"]
        task = graph_tasks.get(tid)
        if task is None or tid in gold_graph:
            reject("dangling_reference", f"{where}: unknown or repeated taskId {tid!r}")
        local_docs = set(task["docIds"])
        links = free_mapping(item["entityLinks"], f"{where}.entityLinks")
        if set(links) != {m["mentionId"] for m in task["entityMentions"]}:
            reject("gold_incomplete", f"{where}: entityLinks must label exactly the task's entity mentions")
        for mid, entity in links.items():
            if entity is not None and entity not in entities:
                reject("dangling_reference", f"{where}: {mid} links to unknown entity {entity!r}")
        events = free_mapping(item["events"], f"{where}.events")
        if set(events) != {m["eventMentionId"] for m in task["eventMentions"]}:
            reject("gold_incomplete", f"{where}: events must label exactly the task's event mentions")
        for eid, event in events.items():
            event = mapping(event, f"{where}.events.{eid}", ("eventType", "eventDate"))
            text(event["eventType"], f"{eid}.eventType")
            day(event["eventDate"], f"{eid}.eventDate")
        merges = free_mapping(item["merges"], f"{where}.merges")
        if set(merges) != {p["pairId"] for p in task["mergeCandidates"]}:
            reject("gold_incomplete", f"{where}: merges must label exactly the task's merge candidates")
        for pid, decision in merges.items():
            choice(decision, MERGE_GOLD, f"{where}.merges.{pid}")
        for eindex, edge in enumerate(sequence(item["edges"], f"{where}.edges")):
            edge = mapping(edge, f"{where}.edges[{eindex}]", ("edgeId", "subject", "predicate", "object", "validFrom", "validTo", "status", "evidence"))
            edge_id = text(edge["edgeId"], "edgeId")
            if edge_id in edges:
                reject("malformed", f"duplicate edgeId {edge_id!r}")
            for end in ("subject", "object"):
                if edge[end] not in entities:
                    reject("dangling_reference", f"edge {edge_id}: unknown {end}")
            if edge["predicate"] not in predicates or edge["subject"] == edge["object"]:
                reject("dangling_reference", f"edge {edge_id}: unregistered predicate or self-loop")
            start, end_ = day(edge["validFrom"], f"{edge_id}.validFrom"), day(edge["validTo"], f"{edge_id}.validTo")
            if start and end_ and start > end_:
                reject("malformed", f"edge {edge_id}: validFrom after validTo")
            choice(edge["status"], EDGE_STATUSES, f"{edge_id}.status")
            for pid in id_list(edge["evidence"], f"{edge_id}.evidence", 1):
                if passages.get(pid) not in local_docs:
                    reject("dangling_reference", f"edge {edge_id}: evidence {pid!r} is outside the task's documents")
            key = triple_key(predicates, edge["subject"], edge["predicate"], edge["object"])
            if key in edge_by_triple:
                reject("malformed", f"edge {edge_id}: triple already defined by {edge_by_triple[key]}")
            edge_by_triple[key] = edge_id
            edges[edge_id] = edge
            edge_split[edge_id] = task["split"]
            split_entities[task["split"]].update((edge["subject"], edge["object"]))
        gold_graph[tid] = item
    if set(gold_graph) != set(graph_tasks):
        reject("gold_incomplete", "gold.graph must cover every graph task")
    if split_entities["dev"] & split_entities["test"]:
        reject("split_leakage", f"entities used by edges of both splits: {sorted(split_entities['dev'] & split_entities['test'])}")

    bench = Bench(
        directory=base, corpus_id=corpus_id, corpus_revision=corpus_revision, gold_revision=gold_revision,
        inputs_sha256=inputs_sha, gold_sha256=digests["gold.json"], gold_provenance=dict(gprov),
        entities=entities, passages=passages, doc_split=doc_split, predicates=predicates,
        graph_tasks=graph_tasks, questions=questions, gold_graph=gold_graph, gold_questions={}, edges=edges,
        edge_by_triple=edge_by_triple)

    gold_questions: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(sequence(gold["questions"], "gold.questions", 1)):
        where = f"gold.questions[{index}]"
        item = mapping(item, where, ("questionId", "kind", "hop", "outcome", "answerEntities", "facts", "paths", "supportPassages", "abstainReason"))
        qid = item["questionId"]
        question = questions.get(qid)
        if question is None or qid in gold_questions:
            reject("dangling_reference", f"{where}: unknown or repeated questionId {qid!r}")
        split = question["split"]
        choice(item["kind"], QUESTION_KINDS, f"{qid}.kind")
        outcome = choice(item["outcome"], OUTCOMES, f"{qid}.outcome")
        hop = item["hop"]
        if hop is not None:
            integer(hop, f"{qid}.hop", 1)
        answers = id_list(item["answerEntities"], f"{qid}.answerEntities")
        if any(entity not in entities for entity in answers):
            reject("dangling_reference", f"{qid}: unknown answer entity")
        support = id_list(item["supportPassages"], f"{qid}.supportPassages")
        for pid in support:
            if pid not in passages:
                reject("dangling_reference", f"{qid}: unknown support passage {pid!r}")
            if doc_split[passages[pid]] != split:
                reject("split_leakage", f"{qid}: support passage {pid!r} belongs to the other split")
        reason = text(item["abstainReason"], f"{qid}.abstainReason", nullable=True)
        facts = sequence(item["facts"], f"{qid}.facts")
        paths = sequence(item["paths"], f"{qid}.paths")
        if outcome == "answered":
            if reason is not None or not answers or not paths or hop is None:
                reject("gold_inconsistent", f"{qid}: answered needs entities, path(s), hop and no abstainReason")
        else:
            if answers or facts or paths:
                reject("gold_inconsistent", f"{qid}: {outcome} must not carry answers, facts or paths")
            if (outcome == "abstained") != (reason is not None):
                reject("gold_inconsistent", f"{qid}: abstainReason is required exactly for abstained")
            if outcome == "conflict" and (len({passages[p] for p in support}) < 2):
                reject("gold_inconsistent", f"{qid}: conflict needs support from at least two documents")
        for findex, fact in enumerate(facts):
            fact = mapping(fact, f"{qid}.facts[{findex}]", ("subject", "predicate", "object", "validFrom", "validTo", "status"))
            edge_id = edge_by_triple.get(triple_key(predicates, fact["subject"], fact["predicate"], fact["object"]))
            gold_edge = edges.get(edge_id) if edge_id else None
            if gold_edge is None or any(fact[k] != gold_edge[k] for k in ("validFrom", "validTo", "status")):
                reject("gold_inconsistent", f"{qid}: fact {findex} does not equal a gold edge")
        normalized_paths: list[list[str]] = []
        for pindex, path in enumerate(paths):
            ids = id_list(path, f"{qid}.paths[{pindex}]", 1)
            if any(edge_id not in edges for edge_id in ids):
                reject("dangling_reference", f"{qid}: path {pindex} names an unknown edge")
            if hop != len(ids):
                reject("gold_inconsistent", f"{qid}: path {pindex} length differs from hop")
            steps = [{k: edges[i][k] for k in ("subject", "predicate", "object")} for i in ids]
            valid, _, end, failure = walk_steps(bench, question["anchorEntity"], steps)
            if not valid or end not in answers:
                reject("gold_inconsistent", f"{qid}: path {pindex} does not walk from the anchor to an answer ({failure})")
            for edge_id in ids:
                if edge_split[edge_id] != split or not set(edges[edge_id]["evidence"]) & set(support):
                    reject("gold_inconsistent", f"{qid}: path edge {edge_id} is in the other split or has no support passage")
            normalized_paths.append(ids)
        if outcome == "answered" and any(entity not in split_entities[split] for entity in answers):
            reject("split_leakage", f"{qid}: answer entity belongs to the other split")
        gold_questions[qid] = {**item, "paths": normalized_paths, "split": split}
    if set(gold_questions) != set(questions):
        reject("gold_incomplete", "gold.questions must cover every question")

    return Bench(**{**bench.__dict__, "gold_questions": gold_questions})
