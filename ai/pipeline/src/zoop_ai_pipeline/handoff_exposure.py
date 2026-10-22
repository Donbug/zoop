"""Pure closure of one validated handoff bundle under one change. No ledger, file, clock or model is touched here.

`Seeds` is the normalized S4 input (what the stored S2/S3 rows say depends on the change); `close(bundle, seeds)` returns the identity-only affected sets.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Seeds:
    """Everything the closure needs from the change, already restricted to the upstream and relation jobs of THIS bundle.

    documents:        (documentId, documentVersion) pairs of the bundle's upstream jobs whose frozen bindings the change reaches
    snapshot_events:  (upstream jobId, snapshot eventId) reached through a member document
    dispositions:     (upstream jobId, eventCandidateId) whose disposition was computed over a reached snapshot event
    relations:        (S3 jobId, relationCandidateId) of a retracted relation (never a source change)
    inputs:           (S3 jobId, relationCandidateId) of every bundle-used relation of an S3 job whose S2 upstream is reached: the producer saw every bound document
    bound:            whether some upstream of the bundle is reached (source change) or the relation is used by the bundle (retraction)
    """
    documents: frozenset = frozenset()
    snapshot_events: frozenset = frozenset()
    dispositions: frozenset = frozenset()
    relations: frozenset = frozenset()
    inputs: frozenset = frozenset()
    bound: bool = False


def used_relations(bundle: dict) -> set:
    """Every (S3 jobId, relationCandidateId) that an emitted edge rests on: INVOLVES/FOLLOWS `sourceRefs` of kind s3-relation and the structural basis."""
    found = set()
    for edge in bundle["relations"]:
        found.update((r["jobId"], r["id"]) for r in edge["sourceRefs"] if r["kind"] == "s3-relation")
        found.update((b["sourceRelation"]["jobId"], b["sourceRelation"]["relationCandidateId"]) for b in edge["basis"])
    return found


def close(bundle: dict, seeds: Seeds) -> dict:
    docs, relations = seeds.documents, seeds.relations
    articles = {(a["articleId"], a["articleVersion"]): a for a in bundle["articles"]}
    hit_articles = {key for key, a in articles.items() if (a["documentId"], a["documentVersion"]) in docs}
    hit_evidence = {e["id"] for e in bundle["evidence"] if (e["articleId"], e["articleVersion"]) in hit_articles}

    reasons: dict[str, set] = {}
    for issue in bundle["issues"]:
        found = set()
        for s in issue["sourceEvents"]:
            job = s["upstream"]["jobId"]
            if (s["documentId"], s["documentVersion"]) in docs or (s["kind"] == "snapshot-event" and (job, s["ref"]) in seeds.snapshot_events):
                found.add("source-document")
            if s["kind"] == "event-candidate" and (job, s["ref"]) in seeds.dispositions:
                found.add("disposition-input")
        if found:
            reasons[issue["id"]] = found
    first = set(reasons)

    involves: dict[str, list] = {}
    for edge in bundle["relations"]:
        if edge["type"] == "INVOLVES":
            involves.setdefault(edge["source"], []).append(edge)
    edge_reasons: dict[str, set] = {}
    for edges in involves.values():
        for edge in edges:
            found = set()
            if edge["source"] in first:
                found.add("issue")
            if hit_evidence.intersection(edge["evidenceIds"]):
                found.add("evidence")
            if any(r["kind"] == "s3-relation" and (r["jobId"], r["id"]) in relations for r in edge["sourceRefs"]):
                found.add("source-relation")
            if any(r["kind"] == "s3-relation" and (r["jobId"], r["id"]) in seeds.inputs for r in edge["sourceRefs"]):
                found.add("upstream-input")
            if found:
                edge_reasons[edge["id"]] = found

    # An issue every INVOLVES edge of which is gone is not published (the planner's own rule); only a loss not already caused by the issue itself is a new reason.
    for issue_id, edges in involves.items():
        if issue_id not in first and all(e["id"] in edge_reasons for e in edges):
            reasons.setdefault(issue_id, set()).add("involvement-lost")
    affected_issues = set(reasons)

    for edge in bundle["relations"]:
        found = set()
        if edge["type"] == "STRUCTURALLY_RELATED_TO":
            if edge["source"] in affected_issues:
                found.add("issue")
            if hit_evidence.intersection(edge["evidenceIds"]):
                found.add("evidence")
            for b in edge["basis"]:
                if hit_evidence.intersection(b["evidenceIds"]) or any((a["articleId"], a["articleVersion"]) in hit_articles for a in b["sourceArticles"]):
                    found.add("basis-evidence")
                if (b["sourceRelation"]["jobId"], b["sourceRelation"]["relationCandidateId"]) in relations:
                    found.add("source-relation")
                if (b["sourceRelation"]["jobId"], b["sourceRelation"]["relationCandidateId"]) in seeds.inputs:
                    found.add("upstream-input")
            hit = {e["target"] for e in involves.get(edge["source"], []) if e["id"] in edge_reasons}
            path = edge["structuralPath"]
            if path["status"] == "unavailable":
                if hit:
                    found.add("anchor-undetermined")
            elif path["companyIds"][0] in hit:
                found.add("anchor")
        elif edge["type"] == "FOLLOWS":
            if edge["source"] in affected_issues or edge["target"] in affected_issues:
                found.add("issue")
            if hit_evidence.intersection(edge["evidenceIds"]):
                found.add("evidence")
        if found:
            edge_reasons[edge["id"]] = found

    return {
        "articles": [{"articleId": a["articleId"], "articleVersion": a["articleVersion"], "documentId": a["documentId"], "documentVersion": a["documentVersion"]}
                     for _, a in sorted(articles.items()) if (a["articleId"], a["articleVersion"]) in hit_articles],
        "issues": [{"id": i, "reasons": sorted(r)} for i, r in sorted(reasons.items())],
        "relations": [{"id": e["id"], "type": e["type"], "reasons": sorted(edge_reasons[e["id"]])} for e in sorted(bundle["relations"], key=lambda e: e["id"])
                      if e["id"] in edge_reasons],
        "evidenceIds": sorted(hit_evidence),
    }


def unresolved(bundle: dict, index: dict) -> tuple[str, str] | None:
    """(S2 upstream jobId, reason) of the first pinned upstream of the bundle that the scanned extraction ledger does not resolve EXACTLY, else None.

    The pin is the S3 binding upstream the freeze checked: the S2 job must be in the scan with the same input digest, be `ready`, and its stored candidate
    projection must recompute to the pinned `digest` (the same job under another frozen grant revision does not)."""
    for source in sorted(bundle["sources"], key=lambda s: s["upstream"]["jobId"]):
        pin = source["upstream"]
        found = index.get(pin["jobId"])
        if found is None:
            return pin["jobId"], "upstream_not_in_scanned_ledger"
        if found["inputDigest"] != pin["inputDigest"]:
            return pin["jobId"], "upstream_input_mismatch"
        if not found["ready"] or found["digest"]() != pin["digest"]:
            return pin["jobId"], "upstream_binding_mismatch"
    return None


def source_seeds(bundle: dict, extracted: dict, index: dict) -> Seeds:
    """The normalized S4 input of one bundle for a source change, from the extraction report and join index of the scan (every upstream is resolved already)."""
    upstreams = {s["upstream"]["jobId"] for s in bundle["sources"]}
    affected = {u for u in upstreams if index[u]["affected"]}
    entries = [j for j in extracted["jobs"] if j["jobId"] in upstreams]
    # An S3 producer reads every document its S2 upstream bound, so every bundle-used relation of such a job is an input, cited or not.
    tainted = {s["relation"]["jobId"] for s in bundle["sources"] if s["upstream"]["jobId"] in affected}
    return Seeds(
        documents=frozenset(pair for u in upstreams for pair in index[u]["documents"]),
        snapshot_events=frozenset((j["jobId"], e["eventId"]) for j in entries for e in j["snapshotEvents"]),
        dispositions=frozenset((j["jobId"], c["eventCandidateId"]) for j in entries for c in j["eventCandidates"]
                               if any(r["code"] == "disposition_input" for r in c["reasons"])),
        inputs=frozenset(pair for pair in used_relations(bundle) if pair[0] in tainted),
        bound=bool(affected))


def relation_seeds(bundle: dict, job_id: str, relation_candidate_id: str) -> Seeds:
    """A relation retraction: the pair only. It withdraws no quote and no document, so no article or evidence is ever reached."""
    pair = (job_id, relation_candidate_id)
    return Seeds(relations=frozenset([pair]), bound=pair in used_relations(bundle))
