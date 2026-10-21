"""Authored OpenAPI semantics and examples of the read-only handoff family. Every example is built through the real wire models, so an example that stops
validating fails at generation; the route and model schemas themselves come from the application (`app.openapi()`).

`example_bundle()` is a small but COMPLETE bundle in the producer's own shape: id formulas, referential closure, counts and digests are real, so the same
document is accepted by the producer's validator (`zoop_ai_pipeline.handoff_contracts.validate_bundle`, exercised by `pipeline_tests/test_handoff_real_cli.py`).
It is repository-authored synthetic text, never a copy of a real source.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .handoff_runtime import canonical
from .handoff_wire import Bundle, HandoffManifest, HdBundle, HdErrorEnvelope, HdStatus
from .wire import ErrorBody

STAMP = "2026-10-16T03:00:00Z"
CHECKED = "2026-10-16T03:00:00.123456+00:00"
HANDOFF = "handoff-synthetic-1"
PRODUCER_CHECKS = ["s3_authority_current", "s2_upstream_pinned", "review_state_pinned", "operator_files_pinned", "provenance_observed_equals_declared",
                   "evidence_exact_resolved_against_source_text", "app_binding_text_digest_equals_source_text", "bundle_schema_and_closure_validated",
                   "artifact_written_and_hashed"]
APP_IMPORT_PENDING = ["article_and_version_exist_in_app", "app_text_sha256_equals_binding", "app_text_span_hash_equals_evidence_quoteSha256",
                      "article_title_url_publishedAt_equal_bundle", "company_ids_exist_in_app_catalog_with_equal_label", "evidence_rows_registered_in_app",
                      "getEvidence_graph_evidence_path", "graph_version_row_and_activation", "asOf_policy"]


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def example_manifest() -> dict[str, Any]:
    """The frozen manifest of the example bundle: same source pins, declaration, policy version and file hashes; its digest is the bundle's `manifestDigest`."""
    pin = {"relation": {"jobId": "s3-synthetic-relation", "inputDigest": "1" * 64},
           "upstream": {"jobId": "s2-synthetic-extraction", "inputDigest": "2" * 64, "digest": "9" * 64}, "reviewDigest": "d" * 64}
    return HandoffManifest.model_validate({"schemaVersion": "zoop-ai-handoff-1", "handoffId": HANDOFF, "sourceKind": "synthetic",
                                           "policyVersion": "zoop-public-projection-policy-1", "sources": [pin],
                                           "files": {"canonical": "6" * 64, "decisions": "7" * 64, "bindings": "8" * 64}}).wire()


def example_bundle() -> dict[str, Any]:
    """One company, one issue with its one original mention, one INVOLVES relation, one evidence span, one article, one S3 job over one S2 upstream."""
    doc_version, raw_version, article_id = "a" * 64, "b" * 64, "doc-" + "c" * 64
    start, end = 12, 48
    evidence_id = "ev-" + digest({"kind": "graph-body-span", "articleId": article_id, "articleVersion": doc_version, "start": start, "end": end})
    job = {"jobId": "s3-synthetic-relation", "inputDigest": "1" * 64}
    upstream = {"jobId": "s2-synthetic-extraction", "inputDigest": "2" * 64}
    event = {"upstream": upstream, "kind": "event-candidate", "ref": "evc-" + "3" * 64, "mentionId": "m-synthetic-1", "documentId": "synthetic-doc-1",
             "documentVersion": doc_version,
             "observation": {"roundId": "round-1", "sourceId": "source-1", "page": 1, "ordinal": 0, "documentId": "synthetic-doc-1", "rawVersion": raw_version,
                             "documentVersion": doc_version}}
    relation_candidate = "rc-" + "4" * 64
    mention = {"documentId": "synthetic-doc-1", "documentVersion": doc_version, "mentionId": "m-synthetic-1", "articleId": article_id, "articleVersion": doc_version,
               "verification": "none", "title": "합성 공급 계약", "action": "공급 계약 발표", "target": None, "eventTime": "2026-09-30", "timePrecision": "day",
               "period": None, "assertionStatus": "announced", "background": False,
               "participants": [{"sourceCompanyId": "synthetic-company-1", "companyId": "KRX:005930", "name": "합성기업", "role": "공급자"},
                                {"sourceCompanyId": None, "companyId": None, "name": "합성 협력사", "role": "수요자"}],
               "evidenceIds": [evidence_id]}
    # one mention that states every value of the issue: nothing selected, every list is that one identity
    mention_ref = {"documentId": mention["documentId"], "documentVersion": mention["documentVersion"], "mentionId": mention["mentionId"]}
    provenance = {"selection": "unanimous", "verification": "none", "withheld": [],
                  "sameValueMentions": {field: [dict(mention_ref)] for field in ("title", "action", "target", "eventTime", "period", "assertionStatus")}}
    # one operator ALLOW on the mention's own eventTime (synthetic); a HOLD/REJECT on a selected value would instead null the issue field and list it in `withheld`
    verdict = {**mention_ref, "field": "eventTime", "value": "2026-09-30", "decision": "ALLOW", "reasonCode": "stated", "evidenceIds": [evidence_id],
               "verification": "operator-field-verdict", "reviewer": "reviewer-1", "decisionRef": "field-2026-10-21:1", "decisionVersion": "v1"}
    bundle: dict[str, Any] = {
        "schemaVersion": "zoop-graph-handoff-bundle-4", "handoffId": HANDOFF, "manifestDigest": digest(example_manifest()),
        "provenance": {"declaredSourceKind": "synthetic", "observedSourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"},
        "policy": {"version": "zoop-public-projection-policy-1", "files": {"canonical": "6" * 64, "decisions": "7" * 64, "bindings": "8" * 64},
                   "evidenceIdKind": "graph-body-span", "offsetUnit": "unicode_code_point", "geography": "operator-field-verdict",
                   "structural": "manual-operator-review", "sequence": "s2-comparison-with-operator-decision", "sourceSupport": "origin-or-exact-text-union"},
        "sources": [{"relation": job, "upstream": {**upstream, "digest": "9" * 64}, "reviewDigest": "d" * 64,
                     "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"},
                     "policies": {"producer": "zoop-relation-producer-1", "verifier": "zoop-relation-verifier-1", "impactProducer": "zoop-impact-producer-1",
                                  "impactVerifier": "zoop-impact-verifier-1", "policy": "zoop-relation-policy-1", "revalidationPolicy": "zoop-revalidation-1",
                                  "impactPolicy": "zoop-impact-policy-1"},
                     "reviewUsed": [{"relationCandidateId": relation_candidate, "revision": 1,
                                     "approvalBasis": {"kind": "automatic-verifier", "revision": 1, "reviewer": None, "decidedAt": "2026-10-13T00:00:01+00:00"}}],
                     "audit": {"s3Relations": 1, "eligibility": {"eligible": 1, "hold": 0, "reject": 0, "pending": 0}, "reviewPending": 0,
                               "impactCandidates": 0, "eligibleNotPublicByType": {"SUPPLIES": 0}}}],
        "companies": [{"id": "KRX:005930", "canonicalId": "co:synth-1", "label": "합성기업", "decisionRef": "canon-2026-10-16:company"}],
        "issues": [{"id": "issue:synthetic-supply", "canonicalId": "issue:supply", "title": "합성 공급 계약", "action": "공급 계약 발표", "target": None,
                    "eventTime": "2026-09-30", "timePrecision": "day", "period": None, "assertionStatus": "announced",
                    "geography": {"value": "domestic", "decisionRef": "geo-2026-10-16:1", "decisionVersion": "v1", "policyVersion": "zoop-public-projection-policy-1",
                                  "countries": ["KR"], "verification": "operator-field-verdict", "evidenceIds": [evidence_id], "basis": [{**event, "countries": ["KR"]}]},
                    "evidenceIds": [evidence_id], "sourceEvents": [event], "mentions": [mention], "decisionRef": "issue-2026-10-16:1", "representative": None,
                    "fieldProvenance": provenance, "fieldVerdicts": [verdict],
                    # one cited article version with no declared origin: its lineage is unknown, so the independent source count is null (never a guess)
                    "sourceSupport": {"articleCount": 1, "knownLineageCount": 0, "unknownLineageArticles": [article_id], "independentSourceCount": None,
                                      "duplicateGroups": []}}],
        "relations": [{"id": "edge-" + digest({"type": "INVOLVES", "source": "issue:synthetic-supply", "target": "KRX:005930"}), "type": "INVOLVES",
                       "source": "issue:synthetic-supply", "target": "KRX:005930", "role": None, "assertionStatus": None, "evidenceIds": [evidence_id], "basis": [],
                       "provenance": {"origin": "s3-relation", "s3SemanticValidation": "independent-verifier-supported-all-claims"}, "decisionRef": None,
                       "sourceRefs": [{"kind": "s3-relation", "jobId": job["jobId"], "id": relation_candidate}]}],
        "evidence": [{"id": evidence_id, "kind": "graph-body-span", "articleId": article_id, "articleVersion": doc_version, "start": start, "end": end,
                      "offsetUnit": "unicode_code_point", "quoteSha256": "e" * 64, "rawLocatorIds": ["loc-1"],
                      "source": {"documentId": "synthetic-doc-1", "documentVersion": doc_version, "rawVersion": raw_version, "textArtifactId": "text-artifact-1",
                                 "sourceEvidenceId": "ev-" + "f" * 32, "inputKind": "body"}}],
        "articles": [{"articleId": article_id, "articleVersion": doc_version, "documentId": "synthetic-doc-1", "documentVersion": doc_version,
                      "rawVersion": raw_version, "textSha256": "5" * 64, "origin": None, "title": "합성 공급 계약 체결", "url": "https://example.invalid/news/1",
                      "publishedAt": "2026-09-30T01:00:00+00:00",
                      "publicationPrecision": "datetime",
                      "observations": [{"roundId": "round-1", "sourceId": "source-1", "page": 1, "ordinal": 0, "observedAt": "2026-09-30T02:00:00+00:00",
                                        "grant": {"grantId": "grant-1", "revision": "1"}}]}],
        "exclusions": {"counts": {}, "items": []},
        "counts": {"companies": 1, "issues": 1, "relations": {"INVOLVES": 1, "STRUCTURALLY_RELATED_TO": 0, "FOLLOWS": 0}, "evidence": 1, "articles": 1,
                   "exclusions": 0},
        "checks": {"producerConfirmed": list(PRODUCER_CHECKS), "appImportPending": list(APP_IMPORT_PENDING)},
        "readiness": {"app": "import-pending", "evidenceRegistration": "not-registered", "publicActivation": "none", "graphDb": "none"},
        "digests": {"content": ""}}
    bundle["digests"]["content"] = digest({key: bundle[key] for key in ("companies", "issues", "relations", "evidence", "articles")})
    return Bundle.model_validate(bundle).wire()


def pins(bundle: dict[str, Any]) -> dict[str, Any]:
    raw = canonical(bundle).encode("utf-8")
    return {"manifestDigest": bundle["manifestDigest"], "bundleDigest": hashlib.sha256(raw).hexdigest(), "contentDigest": bundle["digests"]["content"],
            "bundleBytes": len(raw)}


def verification(bundle: dict[str, Any]) -> dict[str, Any]:
    return {**pins(bundle), "counts": bundle["counts"], "sources": len(bundle["sources"]), "provenance": bundle["provenance"]}


DESCRIPTION = """\
**Graph handoff bundles (`/internal/v1/graph-handoffs`, schema `zoop-ai-internal-handoff-1`, scope `handoff.read`).** A fourth, separate, strictly read-only
family over the installed `zoop-ai-handoff export` command: the verified status of one AI handoff and, only while it verifies now, the whole versioned bundle
(`zoop-graph-handoff-bundle-4`) the application imports. It is **not** the `graph.read` family above and shares none of its variables, scope or allowlist. It
writes nothing (no handoff, no ledger, no cache, no source write, no model or network call), cannot freeze, recover, activate or publish, runs no caller-supplied
path, command or query and has no list route. It is off unless its all-or-nothing server configuration group is set (otherwise both routes answer 409
`execution_unavailable` after authentication). `publication` is always `not-published` and `appImport` always `pending`: this service delivers the AI-side
artifact; the application's article/text/evidence/catalog verification, snapshot registration and activation are the backend's and are not claimed here.

**Which handoffs a caller may read.** A handoff id is only a label, so the operator lists per principal the exact `{handoffId, manifestDigest, bundleDigest}`
(both SHA-256 pins are required) in a server-owned allowlist that is re-read on every request and again before anything of the answer is used. A handoff that is
not listed for the caller answers 403 `handoff_not_allowed` before any child process is touched, with one answer for "unknown", "exists but not yours" and
"listed for another principal". A listed handoff that the ledger does not have answers 404 `handoff_not_found` (an operator configuration gap).

**Delivery.** Content leaves only while the handoff verifies *now*: the producer re-checks on every export the S3 authority and S2 upstream pins, grants and
rights, the used review revisions, the three operator files against the manifest pins and the rebuilt content digest; the service then hashes the canonical
bytes of the bundle it received, requires the result to equal the producer's receipt **and** the operator's pins, parses it through a closed model (unknown
fields are refused at every level) and requires the model to dump back to exactly those canonical bytes. Otherwise the answer is **200 with
`delivery.state=withheld`**, a reason code (`source_unauthorized`, `upstream_changed`, `source_pin_missing`, `review_revision_changed`,
`canonical_mapping_changed`, `decisions_changed`, `bindings_changed`, `handoff_content_changed`, `handoff_not_ready`, `handoff_pin_mismatch`,
`handoff_contract_changed` ...) and nothing else: no `verification` (so no count, source id or digest) and no `bundle`. `handoff_contract_changed` means the
handoff was frozen under an earlier bundle schema (`zoop-graph-handoff-bundle-1`, `-2` or `-3`): it is never reinterpreted or relayed, and the operator freezes a new handoff id.
A withheld answer is not an error and not an empty bundle; do not import it and do not treat it as "no data". The checks are separate reads at separate instants,
so a revocation that lands between them and the response is not covered and nothing recalls content a caller already received.

**Original mentions.** Every `issues[].mentions[]` item is one S2 mention exactly as extracted (`documentId`, `documentVersion` and the S2 local `mentionId`
identify it; a local id is unique only within one document version), with the app article it belongs to and the evidence ids of its own citations. Its
`verification` is always `none`: title, action, target, time, period, assertion status, background flag and participants are candidate or snapshot values of S2,
never verified, decided or approved fields, and they are not derived from the merged issue. A participant carries the S2 `sourceCompanyId`, the S2 `name` and the
S2 `role` text as is (not a confirmed role, not an `INVOLVES` relation); `companyId` is the public company only where every carrying upstream mapped the source id
to the same company of this bundle, otherwise null.

**Field provenance.** Every issue carries a closed `fieldProvenance` that records how the producer chose the issue's six headline values (`title`, `action`,
`target`, `eventTime`, `period`, `assertionStatus`): `selection` is `unanimous` (no operator representative; every mention states all six values) or
`operator-representative` (the operator's single representative decision; it is one choice for all six fields, never a per-field decision). `sameValueMentions`
lists per field, in the order of `mentions[]`, the identities (`documentId`, `documentVersion`, `mentionId`) of exactly those mentions whose own value equals the
issue's value (null equals null; no trimming or time normalisation) where "the issue's value" is the SELECTED value, never a redacted null. `verification` is always
`none`: this is the actual selection, never a fact verification, support or approval. `withheld` lists (`eventTime`, `period` order) the fields whose headline the
producer nulled because of an operator HOLD or REJECT on the selected basis. The producer proves list exactness and closure; this service checks only the shapes.

**Field verdicts.** `issues[].fieldVerdicts` holds the operator's own per-field decisions on one original mention's `eventTime` or `period` (`field`, the exact
reviewed `value`, `decision` ALLOW|HOLD|REJECT, a closed `reasonCode`, `evidenceIds` of the mention's own document, `reviewer`, `decisionRef`, `decisionVersion`,
`verification` always `operator-field-verdict`). They are never AI output, carry no free-text note, and exist only where an operator reviewed; an empty list means
"no field verdict exists", not "verified". This service neither derives nor judges them and checks only the shapes (decision/reason/evidence-count combinations:
ALLOW+stated needs spans, HOLD+unstated none, HOLD+ambiguous spans, REJECT+contradicted spans). Original `mentions[]` values are never changed.

**The bundle bytes.** `bundle` is the producer's artifact, relayed with exactly its keys and values. `verification.bundleDigest` is the SHA-256 of its canonical
UTF-8 bytes, where canonical means JSON with keys sorted by code point, separators `,` and `:` without whitespace and non-ASCII characters not escaped (Python
`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`). All numbers are non-negative integers and all keys ASCII, so any JSON parser followed by that
serialisation reproduces the same bytes and the same digest, whatever the language; do not normalise, drop or add a field before hashing. Every key the service
adds (`appImport`, `observedAt`, `verification`, `delivery`) is a sibling of `bundle`, never inside it. Strings that came from sources (titles, URLs, labels,
observation and grant metadata, `sourceKind`) are data the producer recorded, never an authority: nothing in them proves or extends a right, and the pins and the
current `delivery.state` are the only delivery gates.

**The manifest bytes.** `manifest` is the operator's frozen manifest exactly as the producer's ledger stored it at freeze time (never rebuilt from today's files or
configuration): schema, handoff id, source-kind declaration, policy version, the S3/S2 source pins with their review digests and the three operator-file SHA-256
hashes. It holds no path and no secret. Its canonical bytes (same canonicalisation as the bundle) hash to `verification.manifestDigest`, which equals
`bundle.manifestDigest`. The service refuses (500 `runtime_binding_mismatch`) a manifest whose digest, handoff id, declaration, policy version, file hashes or
source pins disagree with the bundle or the producer's receipt, and (500 `runtime_contract_mismatch`) a missing manifest or any unknown field at any level. A
backend therefore recomputes both digests from ONE authenticated response. `manifest` is a sibling of `bundle`; status and withheld answers never carry it.

**Status.** `GET /{handoffId}` runs the same full export gate chain and returns identity, `state`, `delivery`, `appImport` and, only when current,
`verification` (manifest, bundle and content digests, bundle size, the bundle's own counts, number of source jobs, provenance declaration). It carries no
node, source id, text or title.

**Bundle.** `GET /{handoffId}/bundle` returns the same fields plus `manifest` and `bundle`. The response is bounded by the producer's 6 MiB bundle limit; the
service reads at most 16 MiB from its child, so an oversized answer is a 503 (`runtime_unavailable`), never a truncated bundle.

**Busy and unavailable.** An operator writer holding a ledger (`handoff_busy`, `relation_busy`, `extraction_busy`, `ingestion_busy`) is 503 `runtime_busy`;
unusable server configuration or operator state (damaged or altered artifact, operator file, ownership, ledger recovery needed) is 503
`service_configuration_invalid`; too many concurrent reads (at most 2 children) is 503 `service_busy`; a missed 45 s deadline or an unreadable answer is 503
`runtime_unavailable`. All carry `Retry-After`; there is exactly one child per request and no automatic retry. A child answer that is not the contract this service
knows is 500 `runtime_contract_mismatch` or `runtime_binding_mismatch` (not retryable). A 503 or 500 is never an empty bundle.
"""


def error(code: str, *, retryable: bool = False, runtime_code: str | None = None, field: str | None = None) -> dict[str, Any]:
    return HdErrorEnvelope(error=ErrorBody(code=code, retryable=retryable, request_id="req-0001", runtime_code=runtime_code, field=field)).wire()


CURRENT = {"state": "current", "reason": None, "checkedAt": CHECKED}


def status(**overrides: Any) -> dict[str, Any]:
    base = {"handoffId": HANDOFF, "state": "ready", "delivery": CURRENT, "verification": verification(example_bundle()), "observedAt": STAMP, **overrides}
    return HdStatus.model_validate(base).wire()


def bundle_result(**overrides: Any) -> dict[str, Any]:
    bundle = example_bundle()
    manifest = example_manifest()
    base = {"handoffId": HANDOFF, "state": "ready", "delivery": CURRENT, "verification": verification(bundle), "manifest": manifest, "bundle": bundle,
            "observedAt": STAMP, **overrides}
    return HdBundle.model_validate(base).wire()


def examples() -> dict[str, Any]:
    withheld = {"state": "withheld", "reason": "source_unauthorized"}
    return {
        "status": {"current": {"summary": "The handoff verifies now and matches the operator's pins", "value": status()},
                   "withheld": {"summary": "A current authority gate refused delivery: identity, state and a reason code only",
                                "value": status(delivery=withheld, verification=None)},
                   "pinMismatch": {"summary": "The ledger holds another bundle than the one the operator reviewed (pins differ)",
                                   "value": status(delivery={"state": "withheld", "reason": "handoff_pin_mismatch"}, verification=None)},
                   "notReady": {"summary": "The handoff is reserved (an interrupted freeze) and not exportable until the operator recovers it",
                                "value": status(state="reserved", delivery={"state": "withheld", "reason": "handoff_not_ready"}, verification=None)},
                   "legacyContract": {"summary": "The handoff was frozen under the earlier bundle schema: withheld, never reinterpreted (freeze a new handoff id)",
                                      "value": status(delivery={"state": "withheld", "reason": "handoff_contract_changed"}, verification=None)}},
        "bundle": {"current": {"summary": "The whole bundle, only while every delivery gate holds at this moment", "value": bundle_result()},
                   "withheld": {"summary": "Source rights were revoked: no manifest, no bundle, no counts",
                                "value": bundle_result(delivery=withheld, verification=None, manifest=None, bundle=None)}},
        "errors": {
            "401": {"summary": "Missing, malformed or unknown bearer token", "value": error("authentication_required")},
            "403.scope": {"summary": "The principal lacks handoff.read", "value": error("scope_denied")},
            "403.handoff": {"summary": "Not listed for this principal (unknown, unlisted and another principal's answer alike)", "value": error("handoff_not_allowed")},
            "404": {"summary": "Listed by the operator but absent from the handoff ledger", "value": error("handoff_not_found", runtime_code="handoff_not_found")},
            "409": {"summary": "The handoff configuration group is not enabled", "value": error("execution_unavailable")},
            "422": {"summary": "Path or query validation", "value": error("invalid_request", field="handoffId")},
            "500": {"summary": "The producer's answer is not the contract this service knows (for example an unknown nested field)", "value": error("runtime_contract_mismatch")},
            "503.busy": {"summary": "A writer holds a ledger: retry later", "value": error("runtime_busy", retryable=True, runtime_code="handoff_busy")},
            "503.unavailable": {"summary": "The child missed its deadline or answered unreadably", "value": error("runtime_unavailable", retryable=True)},
            "503.config": {"summary": "The stored artifact or an operator file needs an operator", "value": error("service_configuration_invalid", retryable=True,
                                                                                                                  runtime_code="handoff_artifact_invalid")},
        },
    }


def _attach(operation: dict[str, Any], code: str, mapping: dict[str, Any]) -> None:
    operation["responses"][code]["content"]["application/json"]["examples"] = mapping


def document(spec: dict[str, Any]) -> None:
    sample = examples()
    errors = sample["errors"]
    status_op = spec["paths"]["/internal/v1/graph-handoffs/{handoffId}"]["get"]
    bundle_op = spec["paths"]["/internal/v1/graph-handoffs/{handoffId}/bundle"]["get"]
    for operation in (status_op, bundle_op):
        _attach(operation, "401", {"example": errors["401"]})
        _attach(operation, "403", {"scopeDenied": errors["403.scope"], "handoffNotAllowed": errors["403.handoff"]})
        _attach(operation, "404", {"example": errors["404"]})
        _attach(operation, "409", {"example": errors["409"]})
        _attach(operation, "422", {"example": errors["422"]})
        _attach(operation, "500", {"example": errors["500"]})
        _attach(operation, "503", {"runtimeBusy": errors["503.busy"], "runtimeUnavailable": errors["503.unavailable"], "serviceConfigurationInvalid": errors["503.config"]})
    status_op["responses"]["200"]["description"] = ("Verified status read from the producer during this request: identity, state, delivery and, only when current, "
                                                    "digests and the bundle's own counts. Never a bundle, a source id or a title.")
    _attach(status_op, "200", sample["status"])
    bundle_op["responses"]["200"]["description"] = ("The frozen manifest and the whole bundle, only while every delivery gate holds at this moment; otherwise `delivery.state` "
                                                    "is `withheld` and `verification`, `manifest` and `bundle` are null. `manifest` hashes (canonical bytes) to `verification.manifestDigest` "
                                                    "and `bundle` to `verification.bundleDigest`.")
    _attach(bundle_op, "200", sample["bundle"])
