"""Validate proposed handoff partitions against an independently pinned source population."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Literal

from pydantic import Field

from . import handoff
from .extraction_contracts import Submit
from .graph_projection import load_registry, review_state
from .graph_projection_contracts import Withheld, entry_key
from .handoff_contexts import Contexts, _object
from .handoff_contracts import MAX_SOURCES, Manifest, SourcePin
from .ingestion_contracts import IngestionFailure, Wire, byte_hash, canonical, digest, read_file
from .operating import MAX_MANIFEST_BYTES, manifest as operating_manifest

SCHEMA = "zoop-partition-check-1"
RESULT = "zoop-partition-check-result-1"


class PinnedFile(Wire):
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class Partition(Wire):
    manifest: PinnedFile
    canonical: PinnedFile
    decisions: PinnedFile
    bindings: PinnedFile


class Request(Wire):
    schema_version: Literal["zoop-partition-check-1"]
    scope: str = Field(min_length=1, max_length=2000)
    source_kind: Literal["actual", "synthetic"]
    universe: PinnedFile
    canonical: PinnedFile
    contexts: PinnedFile
    partitions: list[Partition] = Field(min_length=1)
    operating_manifests: list[PinnedFile] = Field(default_factory=list)


class Population(Wire):
    sources: list[SourcePin] = Field(min_length=1)


def check(raw: bytes) -> dict:
    """Read through native owners; report blocked reads separately from complete invalid partitions."""
    result = {"schemaVersion": RESULT, "status": "blocked", "inputs": [], "findings": [], "components": [],
              "issues": [], "usage": dict(handoff.USAGE), "memberInventoryComplete": False}
    findings = result["findings"]

    def finding(code, effect="partition-invalid", **detail):
        findings.append({"code": code, "effect": effect, **detail})

    def pinned(ref, role):
        raw = read_file(Path(ref.path), MAX_MANIFEST_BYTES)
        if byte_hash(raw) != ref.sha256:
            raise handoff.ExtractionFailure("input_pin_mismatch", {"file": role})
        result["inputs"].append({"file": role, "sha256": ref.sha256})
        return json.loads(raw, object_pairs_hook=_object)
    analysis_findings_start = None

    try:
        request = Request.model_validate(json.loads(raw, object_pairs_hook=_object))
        result["scope"] = request.scope
        pins = Population.model_validate(pinned(request.universe, "universe")).sources
        counts = Counter(pin.relation.job_id for pin in pins)
        for job, count in sorted(counts.items()):
            if count != 1:
                finding("original_job_duplicate", jobId=job, count=count)
        if any(count != 1 for count in counts.values()):
            raise handoff.ExtractionFailure("original_universe_ambiguous")
        expected = {pin.relation.job_id: pin for pin in pins}
        # The population comes from the original collection/accepted selection, never the proposed partitions.
        collection_jobs, collection_requests = [], {}
        for index, ref in enumerate(request.operating_manifests):
            for unit in operating_manifest(pinned(ref, f"operatingManifests/{index}")):
                job = unit["relationJobId"]
                collection_jobs.append(job)
                collection_requests[job] = Submit.model_validate(unit["extraction"]).wire()
                if job not in expected or expected[job].upstream.job_id != unit["extraction"]["jobId"]:
                    finding("original_collection_job_mismatch", jobId=job, setId=unit["setId"])
        if request.operating_manifests:
            if set(collection_jobs) != set(expected) or len(collection_jobs) != len(set(collection_jobs)):
                finding("original_collection_universe_mismatch")
        pinned(request.canonical, "canonical")
        registry = load_registry(Path(request.canonical.path))
        if byte_hash(registry.raw) != request.canonical.sha256:
            raise handoff.ExtractionFailure("canonical_mapping_changed")
        pinned(request.contexts, "contexts")
        contexts = Contexts.read(Path(request.contexts.path), request.contexts.sha256, Path(request.canonical.path))
        partitions, occurrences = [], defaultdict(list)
        for index, spec in enumerate(request.partitions):
            wire = pinned(spec.manifest, f"partitions/{index}/manifest")
            # Keep population diagnostics even when the production manifest rejects duplicate or excessive sources.
            for source in wire["sources"]:
                pin = SourcePin.model_validate(source)
                job = pin.relation.job_id
                occurrences[job].append(index)
                if job not in expected:
                    finding("unexpected_job", jobId=job, partition=index)
                elif pin != expected[job]:
                    finding("job_pin_mismatch", jobId=job, partition=index)
            try:
                manifest = Manifest.model_validate(wire)
            except ValueError:
                finding("manifest_invalid", "whole-freeze-error", partition=index)
                continue
            if manifest.source_kind != request.source_kind:
                finding("manifest_source_kind_mismatch", "whole-freeze-error", partition=index)
            for name in ("canonical", "decisions", "bindings"):
                ref = getattr(spec, name)
                pinned(ref, f"partitions/{index}/{name}")
                if ref.sha256 != getattr(manifest.files, name):
                    raise handoff.ExtractionFailure("operator_file_pin_mismatch", {"file": name})
            paths = handoff.HandoffPaths(None, None, None, None, *(Path(getattr(spec, name).path) for name in ("canonical", "decisions", "bindings")))
            operator = handoff.load_operator(paths)
            if operator.hashes() != manifest.files.wire():
                raise handoff.ExtractionFailure("operator_file_changed")
            if operator.decisions.policy_version != manifest.policy_version:
                raise handoff.ExtractionFailure("operator_policy_mismatch")
            partitions.append((index, manifest, operator))
        for job in sorted(expected):
            if not occurrences[job]:
                finding("missing_job", jobId=job)
        for job, indexes in sorted(occurrences.items()):
            if len(indexes) > 1:
                finding("duplicate_job", jobId=job, partitions=indexes)
        loaded, member_rows = {}, {}
        with contexts.open(pins) as readers:
            for pin in sorted(pins, key=lambda item: item.relation.job_id):
                job = pin.relation.job_id
                try:
                    item = handoff.load_source(readers, contexts, request, pin, strict=False)
                    if digest(review_state(item.s3)) != pin.review_digest:
                        raise handoff.ExtractionFailure("review_revision_changed")
                    if job in collection_requests and item.submit.wire() != collection_requests[job]:
                        finding("original_collection_request_mismatch", jobId=job)
                    member_rows[job] = handoff.members_of(item)
                    loaded[job] = item
                except (handoff.ExtractionFailure, Withheld, IngestionFailure) as exc:
                    finding(exc.code, "source-blocked", jobId=job)
            result["counts"] = {"originalS3Jobs": len(pins), "readS3Jobs": len(loaded), "partitions": len(request.partitions),
                                "actualMembers": sum(map(len, member_rows.values()))}
            if len(loaded) != len(pins):
                return result
            analysis_findings_start = len(findings)
            issue_jobs, groups = defaultdict(set), defaultdict(dict)
            unmapped = []
            for job, members in member_rows.items():
                for member in members:
                    key = entry_key(*member.loaded.upstream_key, "event", member.ref)
                    entry = registry.entries.get(key)
                    if entry is None:
                        unmapped.append({"jobId": job, "sourceEvent": member.source_event()})
                        continue
                    issue_jobs[entry.canonical_id].add(job)
                    groups[entry.canonical_id][canonical(member.source_event())] = member
            result["unmappedMembers"] = unmapped
            result["counts"].update(mappedCanonicalIssues=len(groups), unmappedMembers=len(unmapped))
            result["memberInventory"] = [{"jobId": job, "sourcePin": expected[job].wire(),
                                          "members": [member.source_event() for member in members]}
                                         for job, members in sorted(member_rows.items())]
            parent = {job: job for job in expected}

            def root(job):
                while parent[job] != job:
                    parent[job] = parent[parent[job]]
                    job = parent[job]
                return job

            for issue, jobs in sorted(issue_jobs.items()):
                jobs = sorted(jobs)
                for job in jobs[1:]:
                    parent[root(job)] = root(jobs[0])
                indexes = sorted({index for job in jobs for index in occurrences[job]})
                members = list(groups[issue].values())
                result["issues"].append({"canonicalId": issue, "jobs": jobs, "partitions": indexes,
                                         "uniqueSourceEvents": len(members), "uniqueMentions": len({(m.doc, m.mention_id) for m in members})})
                if len(indexes) > 1:
                    finding("cross_manifest_issue", canonicalId=issue, jobs=jobs, partitions=indexes)
            components = defaultdict(list)
            for job in sorted(expected):
                components[root(job)].append(job)
            for jobs in sorted(components.values()):
                issues = sorted(issue for issue, carrying in issue_jobs.items() if carrying.intersection(jobs))
                members = {canonical(m.source_event()): m for issue in issues for m in groups[issue].values()}
                component = {"jobs": jobs, "uniqueS3Jobs": len(jobs), "canonicalIssues": issues,
                             "uniqueSourceEvents": len(members), "uniqueMentions": len({(m.doc, m.mention_id) for m in members.values()})}
                result["components"].append(component)
                if len(jobs) > MAX_SOURCES:
                    finding("component_exceeds_manifest_limit", limit=MAX_SOURCES, **component)
            for index, manifest, operator in partitions:
                local_jobs = {pin.relation.job_id for pin in manifest.sources} & expected.keys()
                local_groups = defaultdict(dict)
                for job in sorted(local_jobs):
                    for member in member_rows[job]:
                        key = entry_key(*member.loaded.upstream_key, "event", member.ref)
                        local = operator.registry.entries.get(key)
                        global_entry = registry.entries.get(key)
                        if (local.canonical_id if local else None) != (global_entry.canonical_id if global_entry else None):
                            finding("canonical_membership_mismatch", partition=index, jobId=job, ref=member.ref)
                        if local:
                            local_groups[local.canonical_id][canonical(member.source_event())] = member
                for decision in operator.decisions.issues:
                    members = list(local_groups[decision.canonical_id].values())
                    detail = {"partition": index, "canonicalId": decision.canonical_id}
                    if not members:
                        finding("issue_source_missing", "issue-exclusion", **detail)
                        continue
                    try:
                        handoff.Planner.fields(decision, members)
                    except handoff.Skip as exc:
                        finding(exc.code, "issue-exclusion", **detail)
                    identities = {(m.doc[0], m.doc[1], m.mention_id) for m in members}
                    documents = {m.doc for m in members}
                    for verdict in decision.field_verdicts:
                        if (verdict.document_id, verdict.document_version, verdict.mention_id) not in identities:
                            finding("field_verdict_unbound", "issue-exclusion", **detail, mentionId=verdict.mention_id)
                        for span in verdict.evidence:
                            if (span.document_id, span.document_version) != (verdict.document_id, verdict.document_version):
                                finding("field_verdict_evidence_unbound", "issue-exclusion", **detail)
                    for span in decision.geography.evidence:
                        if (span.document_id, span.document_version) not in documents:
                            finding("geography_evidence_unbound", "issue-exclusion", **detail)
                for decision in operator.decisions.structural:
                    for basis in decision.basis:
                        if basis.job_id not in local_jobs or basis.relation_candidate_id not in loaded[basis.job_id].relations:
                            finding("structural_source_outside_partition", "item-exclusion", partition=index, canonicalId=decision.issue, jobId=basis.job_id)
                upstreams = {loaded[job].upstream_key for job in local_jobs}
                refs = {(m.loaded.upstream_key, m.ref) for job in local_jobs for m in member_rows[job]}
                for decision in operator.decisions.follows:
                    source = decision.source
                    up = (source.upstream.job_id, source.upstream.input_digest)
                    if up not in upstreams or (up, source.event_candidate_id) not in refs or (up, source.target_event_id) not in refs:
                        finding("follows_source_outside_partition", "item-exclusion", partition=index)
            # Match the handoff delivery boundary: every constituent must still be readable under the retained S3 locks.
            for pin in sorted(pins, key=lambda item: item.relation.job_id):
                item = handoff.load_source(readers, contexts, request, pin, strict=False)
                if digest(review_state(item.s3)) != pin.review_digest:
                    raise handoff.ExtractionFailure("review_revision_changed")
        result["memberInventoryComplete"] = True
        result["status"] = "invalid" if findings else "valid"
    except (handoff.ExtractionFailure, Withheld, IngestionFailure) as exc:
        code, detail = exc.code, getattr(exc, "detail", None)
    except (OSError, ValueError, KeyError, TypeError):
        code, detail = "input_or_configuration_invalid", None
    else:
        return result
    if analysis_findings_start is not None:
        del findings[analysis_findings_start:]
    for name in ("counts", "memberInventory", "unmappedMembers", "issues", "components"):
        result.pop(name, None)
    result["memberInventoryComplete"] = False
    finding(code, "source-blocked", **({"detail": detail} if detail else {}))
    return result
