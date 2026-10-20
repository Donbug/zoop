"""Harness for the read-only handoff door: a workspace with every server-owned input of the handoff group, a test-owned stand-in for `zoop-ai-handoff` and
producer-shaped export envelopes. The stand-in only records what the service passed it (argv, stdin, environment, working directory, timing) and answers what a
test scripted, so the service's argv, environment, interpretation, closed bundle model, pins and gating are proven without the pipeline. The real installed
`zoop-ai-handoff` over an actual two-job world is exercised by `pipeline_tests/test_handoff_real_cli.py` and `scripts/handoff_service_smoke.py`.

The bundles here come from `zoop_ai_service.handoff_doc.example_bundle()` (complete in the producer's shape, accepted by the producer's own validator in the
pipeline tests) and are then hand-mutated per test; every mutation re-seals the content digest so a test only trips the rule it targets.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

from support import Workspace, canonical, merged_grants
from zoop_ai_service.handoff_doc import CHECKED, HANDOFF, digest, example_bundle, pins

EXPORTS_SCHEMA = "zoop-ai-handoff-exports-1"
RUNTIME_SCHEMA = "zoop-ai-handoff-1"
USAGE = {"providerCalls": 0, "modelCalls": 0}
HANDOFF_VARS = ("ZOOP_AI_SERVICE_HANDOFF_COMMAND", "ZOOP_AI_HANDOFF_STATE_DIR", "ZOOP_AI_HANDOFF_RELATION_STATE_DIR", "ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR",
                "ZOOP_AI_HANDOFF_INGESTION_STATE_DIR", "ZOOP_AI_SERVICE_HANDOFF_SOURCES", "ZOOP_AI_SERVICE_HANDOFF_CANONICAL", "ZOOP_AI_SERVICE_HANDOFF_DECISIONS",
                "ZOOP_AI_SERVICE_HANDOFF_BINDINGS", "ZOOP_AI_SERVICE_HANDOFF_EXPORTS")
OTHER_HANDOFF = "handoff-synthetic-2"
PRINCIPAL = "handoffer"
# Strings of the bundle's own source-derived data (titles, labels, URLs): delivered on the bundle route, never in a status, a log or an error.
SOURCE_DATA = ("합성기업", "합성 공급 계약", "example.invalid", "synthetic-doc-1", "grant-1")

STUB = '''#!__PYTHON__
import json, os, signal, sys, time
ROOT = __ROOT__
raw = sys.stdin.read()
behavior = json.load(open(ROOT + "/behavior.json"))
call = {"argv": sys.argv[1:], "stdin": raw, "env": dict(os.environ), "cwd": os.getcwd(), "pid": os.getpid(), "t0": time.time()}
if behavior.get("rewrite"):
    open(behavior["rewrite"]["path"], "w").write(behavior["rewrite"]["content"])
mode = behavior.get("mode", "result")
if mode == "sleep":
    time.sleep(behavior["seconds"])
call["t1"] = time.time()
with open(ROOT + "/calls.jsonl", "a") as handle:
    handle.write(json.dumps(call) + "\\n")
if mode == "die":
    os.kill(os.getpid(), signal.SIGKILL)
if mode == "big":
    sys.stdout.buffer.write(b"x" * behavior["bytes"])
    sys.exit(0)
if mode == "raw":
    sys.stdout.buffer.write(behavior["raw"].encode("utf-8"))
    sys.exit(behavior["exit"])
text = json.dumps(behavior["output"], ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\\n"
sys.stdout.buffer.write(text.encode("utf-8"))
sys.exit(behavior.get("exit", 0))
'''


def manifest_of(bundle: dict[str, Any]) -> dict[str, Any]:
    """The frozen manifest the producer would have stored for this bundle: its source pins, declaration, policy version and operator-file hashes."""
    return {"schemaVersion": RUNTIME_SCHEMA, "handoffId": bundle["handoffId"], "sourceKind": bundle["provenance"]["declaredSourceKind"],
            "policyVersion": bundle["policy"]["version"], "files": copy.deepcopy(bundle["policy"]["files"]),
            "sources": [{"relation": copy.deepcopy(s["relation"]), "upstream": copy.deepcopy(s["upstream"]), "reviewDigest": s["reviewDigest"]} for s in bundle["sources"]]}


def seal(bundle: dict[str, Any]) -> dict[str, Any]:
    """Recompute the manifest and content digests after a mutation, the way the producer does, so only the targeted rule can refuse the bundle."""
    bundle["manifestDigest"] = digest(manifest_of(bundle))
    bundle["digests"]["content"] = digest({key: bundle[key] for key in ("companies", "issues", "relations", "evidence", "articles")})
    return bundle


def mutated(change) -> dict[str, Any]:
    bundle = copy.deepcopy(example_bundle())
    change(bundle)
    return seal(bundle)


def envelope(bundle: dict[str, Any] | None = None, handoff_id: str = HANDOFF, *, receipt: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    """A current export result exactly as the producer prints it, including everything the service must not relay (sources, files, counts, attempts...)."""
    bundle = bundle if bundle is not None else example_bundle()
    fixed = pins(bundle)
    stored = {"handoffId": bundle["handoffId"], "manifestDigest": fixed["manifestDigest"], "bundleSchema": bundle["schemaVersion"], "bundleDigest": fixed["bundleDigest"],
              "contentDigest": fixed["contentDigest"], "bundleBytes": fixed["bundleBytes"], "provenance": bundle["provenance"],
              "sources": [{"relation": s["relation"], "upstream": s["upstream"], "reviewDigest": s["reviewDigest"]} for s in bundle["sources"]],
              "files": bundle["policy"]["files"], "counts": bundle["counts"], "exclusionCodes": bundle["exclusions"]["counts"], "checks": bundle["checks"],
              "frozenAt": "2026-10-16T01:00:00.000000+00:00", **(receipt or {})}
    return {"schemaVersion": RUNTIME_SCHEMA, "handoffId": handoff_id, "state": "ready", "publication": "not-published", "next": "export", "failure": None,
            "receipt": stored, "attempts": [{"n": 1, "kind": "freeze", "outcome": "written", "code": None}], "usage": dict(USAGE),
            "delivery": {"status": "current", "checkedAt": CHECKED, "reviewDigestMatches": True,
                         "checks": ["operator_files_equal_manifest_pins", "s3_authority_and_s2_upstream_pin_current", "used_review_revisions_unchanged",
                                    "content_digest_rebuilt_equal"]},
            "manifest": manifest_of(bundle), "bundle": bundle, **overrides}


def withheld_output(handoff_id: str = HANDOFF, code: str = "source_unauthorized", state: str = "ready") -> dict[str, Any]:
    return {"schemaVersion": RUNTIME_SCHEMA, "handoffId": handoff_id, "state": state, "publication": "not-published",
            "delivery": {"status": "withheld", "code": code}, "usage": dict(USAGE)}


def error_output(code: str, detail: dict | None = None) -> dict[str, Any]:
    return {"schemaVersion": RUNTIME_SCHEMA, "error": {"code": code, **({"detail": detail} if detail else {})}}


def export_entry(principal: str = PRINCIPAL, handoff_id: str = HANDOFF, bundle: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    fixed = pins(bundle if bundle is not None else example_bundle())
    return {"principal": principal, "handoffId": handoff_id, "manifestDigest": fixed["manifestDigest"], "bundleDigest": fixed["bundleDigest"], **extra}


class HandoffWorkspace(Workspace):
    """One service's fresh state with every server-owned input of the handoff group over throwaway files and a scripted stand-in command."""

    def __init__(self, root: Path, *, with_relation: bool = False, command: Path | None = None, exports: list[dict] | None = None):
        super().__init__(root, replay=None, grants=merged_grants())
        self.with_relation = with_relation
        self.handoff_state, self.relation_state = root / "handoff", root / "relation"
        self.extraction_state, self.ingestion_state, self.app_state = root / "extraction", root / "ingestion", root / "app"
        for directory in (self.handoff_state, self.relation_state, self.extraction_state, self.ingestion_state, self.app_state):
            directory.mkdir()
        self.sources, self.canonical = root / "sources.json", root / "canonical.json"
        self.decisions, self.bindings, self.exports = root / "decisions.json", root / "bindings.json", root / "exports.json"
        self.producer, self.verifier, self.upstreams = root / "producer.json", root / "verifier.json", root / "upstreams.json"
        for path in (self.sources, self.canonical, self.decisions, self.bindings, self.producer, self.verifier):
            path.write_text("{}", encoding="utf-8")
        self.upstreams.write_text(canonical({"schemaVersion": "zoop-ai-relation-upstreams-1", "upstreams": []}), encoding="utf-8")
        self.write_exports(exports if exports is not None else [export_entry()])
        self.calls_path, self.behavior_path = root / "calls.jsonl", root / "behavior.json"
        self.command = command or self.write_stub()

    # ---- the scripted stand-in ----

    def write_stub(self) -> Path:
        script = self.root / "zoop-ai-handoff-stub.py"
        script.write_text(STUB.replace("__PYTHON__", sys.executable).replace("__ROOT__", repr(str(self.root))), encoding="utf-8")
        script.chmod(0o755)
        self.script({"mode": "result", "output": envelope()})
        return script

    def script(self, behavior: dict[str, Any]) -> None:
        self.behavior_path.write_text(json.dumps(behavior), encoding="utf-8")

    def calls(self) -> list[dict[str, Any]]:
        if not self.calls_path.exists():
            return []
        return [json.loads(line) for line in self.calls_path.read_text(encoding="utf-8").splitlines()]

    # ---- operator inputs ----

    def write_exports(self, entries: list[dict]) -> None:
        self.exports.write_text(canonical({"schemaVersion": EXPORTS_SCHEMA, "handoffs": entries}), encoding="utf-8")

    def env(self, **overrides: str | None) -> dict[str, str]:
        env = super().env()
        env.update({
            "ZOOP_STATE_DIR": str(self.app_state), "ZOOP_AI_SERVICE_HANDOFF_COMMAND": str(self.command), "ZOOP_AI_HANDOFF_STATE_DIR": str(self.handoff_state),
            "ZOOP_AI_HANDOFF_RELATION_STATE_DIR": str(self.relation_state), "ZOOP_AI_HANDOFF_EXTRACTION_STATE_DIR": str(self.extraction_state),
            "ZOOP_AI_HANDOFF_INGESTION_STATE_DIR": str(self.ingestion_state), "ZOOP_AI_SERVICE_HANDOFF_SOURCES": str(self.sources),
            "ZOOP_AI_SERVICE_HANDOFF_CANONICAL": str(self.canonical), "ZOOP_AI_SERVICE_HANDOFF_DECISIONS": str(self.decisions),
            "ZOOP_AI_SERVICE_HANDOFF_BINDINGS": str(self.bindings), "ZOOP_AI_SERVICE_HANDOFF_EXPORTS": str(self.exports)})
        if self.with_relation:   # an S3 group over the SAME roots: the handoff then shares its gate
            env.update({"ZOOP_AI_SERVICE_RELATION_COMMAND": sys.executable, "ZOOP_AI_RELATION_STATE_DIR": str(self.relation_state),
                        "ZOOP_AI_EXTRACTION_STATE_DIR": str(self.extraction_state), "ZOOP_AI_INGESTION_STATE_DIR": str(self.ingestion_state),
                        "ZOOP_AI_SERVICE_SOURCES": str(self.sources), "ZOOP_AI_SERVICE_RELATION_REPLAY": str(self.producer),
                        "ZOOP_AI_SERVICE_RELATION_VERIFIER_REPLAY": str(self.verifier), "ZOOP_AI_SERVICE_RELATION_UPSTREAMS": str(self.upstreams)})
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def private_strings(self) -> list[str]:
        return [*super().private_strings(), str(self.handoff_state), str(self.relation_state), str(self.extraction_state), str(self.ingestion_state),
                str(self.app_state), str(self.sources), str(self.canonical), str(self.decisions), str(self.bindings), str(self.exports), str(self.command)]


HANDOFFS = "/internal/v1/graph-handoffs"


def status_url(handoff: str = HANDOFF) -> str:
    return f"{HANDOFFS}/{handoff}"


def bundle_url(handoff: str = HANDOFF) -> str:
    return f"{HANDOFFS}/{handoff}/bundle"


def full_bundle() -> dict[str, Any]:
    """The example bundle enriched with every variant the closed model has to accept: a structural and a FOLLOWS relation, a representative source event, a second
    source and every exclusion detail shape. It is STRUCTURALLY complete but not semantically closed (the producer's validator would refuse it): the service
    never judges semantics, so this is what the model-level tests mutate."""
    bundle = copy.deepcopy(example_bundle())
    job, evidence_id = bundle["sources"][0]["relation"], bundle["evidence"][0]["id"]
    article = bundle["articles"][0]
    event = bundle["issues"][0]["sourceEvents"][0]
    bundle["issues"][0]["representative"] = copy.deepcopy(event)
    # a second original mention that reuses the S2 local id of the first one in ANOTHER document (a local id is unique only within one document version), with
    # values of its own: nothing of it is derived from the merged issue
    first = bundle["issues"][0]["mentions"][0]
    bundle["issues"][0]["mentions"].append({**copy.deepcopy(first), "documentId": "synthetic-doc-2", "documentVersion": "9" * 64, "articleId": "doc-" + "8" * 64,
                                            "articleVersion": "9" * 64, "title": "합성 공급 계약 후속", "target": "합성 대상", "eventTime": None, "timePrecision": "unknown",
                                            "period": "2026Q4", "assertionStatus": "planned", "background": True, "participants": []})
    bundle["sources"].append({**copy.deepcopy(bundle["sources"][0]), "relation": {"jobId": "s3-synthetic-relation-2", "inputDigest": "7" * 64}})
    relation_candidate = "rc-" + "4" * 64
    bundle["relations"].append({
        "id": "edge-" + "a" * 64, "type": "STRUCTURALLY_RELATED_TO", "source": "issue:synthetic-supply", "target": "KRX:005930", "role": None, "assertionStatus": None,
        "evidenceIds": [evidence_id],
        "basis": [{"sourceRelation": {"jobId": job["jobId"], "relationCandidateId": relation_candidate}, "relationKey": "b" * 64, "relationType": "SUPPLIES",
                   "validFrom": None, "validUntil": "2026-12-31", "countries": ["KR"], "verifiedAt": "2026-10-01T00:00:00+00:00",
                   "sourceArticles": [{"articleId": article["articleId"], "articleVersion": article["articleVersion"]}], "evidenceIds": [evidence_id]}],
        "provenance": {"origin": "manual-operator-review", "s3SemanticValidation": "none", "status": "operator-asserted", "reviewer": "reviewer-a",
                       "decisionRef": "structural-1", "decisionVersion": "v1", "bindingDigest": "c" * 64,
                       "basisEligibility": "s3-independent-verifier-supported-all-claims"},
        "decisionRef": "structural-1", "sourceRefs": [{"kind": "s3-relation", "jobId": job["jobId"], "id": relation_candidate}]})
    bundle["relations"].append({
        "id": "edge-" + "d" * 64, "type": "FOLLOWS", "source": "issue:synthetic-supply", "target": "issue:synthetic-earlier", "role": None, "assertionStatus": None,
        "evidenceIds": [evidence_id], "basis": [],
        "provenance": {"origin": "s2-comparison-with-operator-decision", "s3SemanticValidation": "none", "s2Relation": "FOLLOWS",
                       "evidenceGate": "exact-source-citation-in-incoming-article", "groupDigest": "e" * 64, "decisionRef": "follows-1", "decisionVersion": "v1"},
        "decisionRef": "follows-1", "sourceRefs": [{"kind": "s2-comparison", "jobId": event["upstream"]["jobId"], "id": "evc-" + "3" * 64 + ">event-1"}]})
    bundle["exclusions"] = {"counts": {"geography_unproven": 1, "issue_metadata_conflict": 1, "applicability_binding_mismatch": 1},
                            "items": [{"kind": "issue", "id": "issue:x", "jobId": None, "code": "geography_unproven"},
                                      {"kind": "issue", "id": "issue:y", "jobId": job["jobId"], "code": "issue_metadata_conflict",
                                       "detail": {"fields": ["title", "eventTime"]}},
                                      {"kind": "structural", "id": "issue:z", "jobId": None, "code": "applicability_binding_mismatch",
                                       "detail": {"expectedBindingDigest": "f" * 64}}]}
    return seal(bundle)
