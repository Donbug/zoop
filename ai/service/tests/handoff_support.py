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
from zoop_ai_service.handoff_doc import CHECKED, HANDOFF, digest, example_bundle, pins, summary_of
from zoop_ai_service.handoff_wire import result_digest, result_version, summary_basis

EXPORTS_SCHEMA = "zoop-ai-handoff-exports-1"
RUNTIME_SCHEMA = "zoop-ai-handoff-1"
USAGE = {"providerCalls": 0, "modelCalls": 0}
# The keys that carry a summary. Privacy checks look at STRUCTURE (a forbidden key at any depth), never at a word an allowed handoff id such as `handoff-summary-1` contains.
SUMMARY_KEYS = frozenset({"summary", "claims", "resultVersion", "generatedAt", "issueSummary", "producer", "verifier"})


def json_keys(value: Any) -> set[str]:
    """Every object key at every depth of a JSON value."""
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in json_keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in json_keys(item)}
    return set()

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
    keys = ("companies", "pathCompanies", "issues", "relations", "impacts", "evidence", "articles")
    bundle["digests"]["content"] = digest({key: bundle[key] for key in keys if key in bundle})   # a dropped list is hashed as absent: only the closed model can refuse it
    return bundle


def structural(bundle: dict[str, Any], hops: int = 1, middle: str = "private") -> dict[str, Any]:
    """Add one STRUCTURALLY_RELATED_TO relation from the example issue's participant P to a non-participant company C, in place.
    `hops` is the number of bases (1 or 2); `middle` is `private` (mapped, only in pathCompanies), `main` (mapped and a public company) or `unmapped` (2 hops only)."""
    evidence_id = bundle["evidence"][0]["id"]
    p, c, m = "KRX:005930", "KRX:000660", "KRX:000270"
    bundle["companies"].append({"id": c, "canonicalId": "co:synth-2", "label": "합성고객", "decisionRef": "canon-2026-10-16:company"})
    middle_company = {"id": m, "canonicalId": "co:synth-3", "label": "합성중간", "decisionRef": "canon-2026-10-16:company"}
    if hops == 2 and middle == "main":
        bundle["companies"].append(middle_company)
    elif hops == 2 and middle == "private":
        bundle["pathCompanies"].append(middle_company)
    bundle["companies"].sort(key=lambda company: company["id"])
    chain = [p, c] if hops == 1 else [p, m, c]
    links = [{"supplierCompanyId": chain[i], "customerCompanyId": chain[i + 1]} for i in range(hops)]
    path = {"status": "unavailable", "reason": "intermediate_company_unmapped"} if middle == "unmapped" else {"status": "complete", "companyIds": chain, "links": links}
    basis = [{"sourceRelation": {"jobId": "s3-synthetic-relation", "relationCandidateId": "rc-" + str(4 + i) * 64}, "relationKey": str(i + 1) * 64, "relationType": "SUPPLIES",
             "businessScope": "합성 사업 범위" if i == 0 else None, "productScope": "합성 제품 범위" if i == 0 else None, "validFrom": None, "validUntil": None, "countries": [],
             "verifiedAt": "2026-10-13T00:00:01+00:00", "sourceArticles": [], "evidenceIds": [evidence_id]} for i in range(hops)]
    bundle["relations"].append({"id": "edge-" + digest({"type": "STRUCTURALLY_RELATED_TO", "source": "issue:synthetic-supply", "target": c, "hops": hops, "middle": middle}),
                                "type": "STRUCTURALLY_RELATED_TO", "source": "issue:synthetic-supply", "target": c, "role": None, "assertionStatus": None, "evidenceIds": [],
                                "basis": basis, "structuralPath": path,
                                "provenance": {"origin": "manual-operator-review", "s3SemanticValidation": "none", "status": "operator-asserted", "reviewer": "reviewer-1",
                                               "decisionRef": "structural-1", "decisionVersion": "v1", "bindingDigest": "a" * 64,
                                               "basisEligibility": "s3-independent-verifier-supported-all-claims"},
                                "decisionRef": None, "sourceRefs": []})
    counts = bundle["counts"]
    counts["companies"], counts["pathCompanies"] = len(bundle["companies"]), len(bundle["pathCompanies"])
    counts["relations"]["STRUCTURALLY_RELATED_TO"] += 1
    return bundle


def mutated(change) -> dict[str, Any]:
    bundle = copy.deepcopy(example_bundle())
    change(bundle)
    return seal(bundle)


def resummarize(bundle: dict[str, Any], outcome: str | None = None, *, index: int = 0) -> dict[str, Any]:
    """Re-pin the summary of issue `index` to the basis the issue has NOW, the way the producer would have written it (default: the same outcome as before), and re-seal the
    outer digests. A test that changes what a summary rests on and still wants an accepted bundle calls this; a test that wants the stale summary refused does not."""
    current = bundle["issues"][index]["summary"]
    bundle["issues"][index]["summary"] = summary_of(bundle, outcome or (current["code"] if current["status"] == "unavailable" else "available"), index=index)
    return seal(bundle)


def with_quotes(bundle: dict[str, Any], extra: int) -> dict[str, Any]:
    """Add `extra` more evidence spans of the issue's one article, cited by its one mention (so `extra` more input quotes of the issue's summary), in place. The summary is
    NOT re-pinned: it now rests on a stale basis until `resummarize`."""
    base, issue = bundle["evidence"][0], bundle["issues"][0]
    for n in range(extra):
        start = 100 + 40 * n
        ident = "ev-" + digest({"kind": "graph-body-span", "articleId": base["articleId"], "articleVersion": base["articleVersion"], "start": start, "end": start + 30})
        bundle["evidence"].append({**copy.deepcopy(base), "id": ident, "start": start, "end": start + 30, "quoteSha256": digest({"quote": n}), "rawLocatorIds": [f"loc-extra-{n}"],
                                   "source": {**base["source"], "sourceEvidenceId": "ev-" + digest({"source": n})[:32]}})
        issue["mentions"][0]["evidenceIds"].append(ident)
        issue["evidenceIds"].append(ident)
    issue["mentions"][0]["evidenceIds"].sort()
    issue["evidenceIds"].sort()
    bundle["counts"]["evidence"] = len(bundle["evidence"])
    return bundle


def live_bundle() -> dict[str, Any]:
    """The example bundle as a LIVE export: bundle and source provenance say live/provider and the summary carries provider and independent-verifier identities."""
    bundle = copy.deepcopy(example_bundle())
    bundle["provenance"].update(executionMode="live", recordingKind="provider")
    bundle["sources"][0]["provenance"].update(executionMode="live", recordingKind="provider")
    return resummarize(bundle)


HIDDEN_EVIDENCE = "ev-" + "9" * 64      # an evidence id no bundle of these tests holds


def issue_summary(bundle: dict[str, Any], index: int = 0) -> dict[str, Any]:
    return bundle["issues"][index]["summary"]


def basis_of(bundle: dict[str, Any], index: int = 0) -> dict[str, Any]:
    """The input basis of issue `index` as the pure rules derive it from the bundle's own evidence rows and articles."""
    return summary_basis(bundle["issues"][index], {e["id"]: e for e in bundle["evidence"]}, {(a["articleId"], a["articleVersion"]): a for a in bundle["articles"]})


def assemble(bundle: dict[str, Any], texts: list[str], cited: list[list[str]] | None = None) -> dict[str, Any]:
    """An `available` summary over the bundle's basis with these claim texts (each cites the first input quote unless `cited` names the ids of every claim) and EVERY identity
    recomputed (result version, result digest), so only a rule about the content itself can refuse it."""
    base = summary_of(bundle, "available")
    quotes = [q["evidenceId"] for q in basis_of(bundle)["quotes"]]
    claims = [{"claimId": f"c{n}", "text": text, "evidenceIds": sorted(set(cited[n - 1] if cited else [quotes[0]]))} for n, text in enumerate(texts, 1)]
    body = {key: value for key, value in base.items() if key != "source"}
    body.update(text="\n".join(texts), claims=claims, evidenceIds=sorted({i for c in claims for i in c["evidenceIds"]}),
                resultVersion=result_version(base["source"]["basisDigest"], claims))
    source = base["source"]
    return {**body, "source": {**source, "resultDigest": result_digest(source["jobId"], source["inputDigest"], source["basisDigest"], body)}}


def reseal(bundle: dict[str, Any], index: int = 0) -> dict[str, Any]:
    """Recompute the result version and the result digest of the bundle's AVAILABLE summary after a test edited its content, so only the targeted rule can refuse it."""
    value = issue_summary(bundle, index)
    value["resultVersion"] = result_version(value["source"]["basisDigest"], value["claims"])
    body = {key: item for key, item in value.items() if key != "source"}
    value["source"]["resultDigest"] = result_digest(value["source"]["jobId"], value["source"]["inputDigest"], value["source"]["basisDigest"], body)
    return bundle


def with_side_evidence(bundle: dict[str, Any], where: str) -> str:
    """One more evidence row of the issue that its mention does NOT cite: only its geography (or its first verdict) does. It is an evidence id of the issue, but not an input
    quote of its summary."""
    base, issue = bundle["evidence"][0], bundle["issues"][0]
    ident = "ev-" + digest({"kind": "graph-body-span", "articleId": base["articleId"], "articleVersion": base["articleVersion"], "start": 200, "end": 230})
    bundle["evidence"].append({**copy.deepcopy(base), "id": ident, "start": 200, "end": 230, "quoteSha256": digest({"quote": where}), "rawLocatorIds": ["loc-side"],
                               "source": {**base["source"], "sourceEvidenceId": "ev-" + digest({"source": where})[:32]}})
    issue["evidenceIds"] = sorted([*issue["evidenceIds"], ident])
    target = issue["geography"] if where == "geography" else issue["fieldVerdicts"][0]
    target["evidenceIds"] = sorted([*target["evidenceIds"], ident])
    bundle["counts"]["evidence"] = len(bundle["evidence"])
    return ident


def summary_edit(path: str, value: Any):
    """A change function that sets `path` (dotted, list indexes numeric) inside the example issue's summary."""
    keys = path.split(".")

    def change(bundle: dict[str, Any]) -> None:
        node: Any = issue_summary(bundle)
        for key in keys[:-1]:
            node = node[int(key)] if isinstance(node, list) else node[key]
        node[int(keys[-1]) if isinstance(node, list) else keys[-1]] = value
    return change


def edit_claim_text(bundle: dict[str, Any], index: int, text: str) -> None:
    """Rewrite claim `index` and the summary `text` consistently WITHOUT recomputing the result version or the result digest."""
    issue_summary(bundle)["claims"][index]["text"] = text
    issue_summary(bundle)["text"] = "\n".join(c["text"] for c in issue_summary(bundle)["claims"])


HANGUL = "가"
# The `generatedAt` grammar shared with the producer and the app (`api/src/test/resources/graph-handoff/summary-time-vectors.json`): YYYY-MM-DDTHH:MM:SS[.f{1,9}](Z|+HH:MM|-HH:MM),
# ASCII, uppercase T and Z, years 1..9999, a real calendar day, offset at most 18:00. The lists are authored here (they never come from the code under test); the shared file
# is read by `test_handoff_summary_unit.py` as well.
SUMMARY_TIME_ACCEPTED = ["2026-10-16T02:30:00Z", "2026-10-16T02:30:00+00:00", "2026-10-16T02:30:00-00:00", "2026-10-16T11:30:00+09:00", "2026-10-16T02:30:00.1Z",
                         "2026-10-16T02:30:00.123456789-05:30", "2026-10-16T02:30:00.100Z", "0001-01-01T00:00:00Z", "9999-12-31T23:59:59+18:00",
                         "2024-02-29T23:59:59-18:00", "2000-02-29T00:00:00Z"]
SUMMARY_TIME_REFUSED = ["2026-10-16T02:30:00", "2026-10-16", "20261016T023000Z", "2026-10-16t02:30:00Z", "2026-10-16T02:30:00z", "2026-10-16 02:30:00Z", "2026-10-16T02:30Z",
                        "2026-10-16T02:30:00+0900", "2026-10-16T02:30:00+09", "2026-10-16T02:30:00+18:01", "2026-10-16T02:30:00-19:00", "2026-10-16T02:30:00+09:60",
                        "0000-01-01T00:00:00Z", "2026-02-29T00:00:00Z", "1900-02-29T00:00:00Z", "2026-13-01T00:00:00Z", "2026-04-31T00:00:00Z", "2026-10-16T24:00:00Z",
                        "2026-10-16T23:60:00Z", "2026-10-16T23:59:60Z", "2026-10-16T02:30:00.Z", "2026-10-16T02:30:00.1234567890Z", "2026-10-16T02:30:00,5Z",
                        "2026-W42-5T02:30:00Z", "2026-289T02:30:00Z", "２０２６-10-16T02:30:00Z", "2026-10-16T02:30:00Z ", " 2026-10-16T02:30:00Z", "2026-10-16T02:30:00Z\n",
                        "2026-10-16T02:30:00 Z"]
# One illegal edit of the example's AVAILABLE summary per rule. Each leaves the other identities as they were, so an edit that also moves a digest is refused twice; the
# rules that could hide behind another are isolated by the tests that recompute identities (`assemble`, `reseal`).
SUMMARY_TAMPER = {
    "text-edited": summary_edit("text", "다른 본문이다."),
    "text-appended": lambda b: issue_summary(b).update(text=issue_summary(b)["text"] + "\n"),
    "claim-text-edited-with-text": lambda b: edit_claim_text(b, 0, "합성기업이 계약을 취소했다."),      # consistent text, but resultVersion and the result digest were not recomputed
    "claim-id-gap": summary_edit("claims.1.claimId", "c3"),
    "claim-id-upper": summary_edit("claims.0.claimId", "C1"),
    "claim-id-zero": summary_edit("claims.0.claimId", "c0"),
    "claim-without-hangul": lambda b: edit_claim_text(b, 0, "Synthetic supply contract announced"),
    "claim-with-newline": lambda b: edit_claim_text(b, 0, "첫 줄이다.\n둘째 줄이다."),
    "claim-with-carriage-return": lambda b: edit_claim_text(b, 0, "첫 줄이다.\r둘째 줄이다."),
    "claim-too-long": lambda b: edit_claim_text(b, 0, HANGUL * 281),
    "claim-empty": lambda b: edit_claim_text(b, 0, ""),
    "claims-empty": lambda b: issue_summary(b).update(claims=[], text=""),
    "claims-six": lambda b: issue_summary(b).update(claims=[{**c, "claimId": f"c{n}"} for n, c in enumerate(issue_summary(b)["claims"] * 2, 1)]),
    "claim-evidence-hidden": summary_edit("claims.0.evidenceIds", [HIDDEN_EVIDENCE]),
    "claim-evidence-duplicate": lambda b: issue_summary(b)["claims"][0].update(evidenceIds=[issue_summary(b)["claims"][0]["evidenceIds"][0]] * 2),
    "claim-evidence-empty": summary_edit("claims.0.evidenceIds", []),
    "claim-evidence-over-five": lambda b: issue_summary(b)["claims"][0].update(evidenceIds=sorted("ev-" + str(n) * 64 for n in range(1, 7))),
    "claim-evidence-not-an-id": summary_edit("claims.0.evidenceIds", ["x"]),
    "union-empty": summary_edit("evidenceIds", []),
    "union-extra-hidden": lambda b: issue_summary(b).update(evidenceIds=sorted([*issue_summary(b)["evidenceIds"], HIDDEN_EVIDENCE])),
    "generated-naive": summary_edit("generatedAt", "2026-10-16T02:30:00"),
    "generated-date": summary_edit("generatedAt", "2026-10-16"),
    "generated-not-a-time": summary_edit("generatedAt", "yesterday"),
    "generated-not-a-string": summary_edit("generatedAt", 1760581800),
    "generated-basic-iso": summary_edit("generatedAt", "20261016T023000+0000"),
    "generated-lowercase": summary_edit("generatedAt", "2026-10-16t02:30:00z"),
    "generated-space": summary_edit("generatedAt", "2026-10-16 02:30:00+00:00"),
    "generated-no-seconds": summary_edit("generatedAt", "2026-10-16T02:30+00:00"),
    "generated-offset-over": summary_edit("generatedAt", "2026-10-16T02:30:00+18:01"),
    "generated-year-zero": summary_edit("generatedAt", "0000-01-01T00:00:00Z"),
    "language-en": summary_edit("language", "en"),
    "language-null": summary_edit("language", None),
    "version-zero": summary_edit("resultVersion", "isr-" + "0" * 64),
    "version-prefix": lambda b: issue_summary(b).update(resultVersion="res-" + issue_summary(b)["resultVersion"][4:]),
    "version-short": summary_edit("resultVersion", "isr-abc"),
    "basis-digest-other": summary_edit("source.basisDigest", "0" * 64),
    "result-digest-other": summary_edit("source.resultDigest", "0" * 64),
    "job-id-edited": summary_edit("source.jobId", "isum-forged-1"),
    "input-digest-edited": summary_edit("source.inputDigest", "1" * 64),
    "source-null": summary_edit("source", None),
    "source-extra-key": summary_edit("source.extra", 1),
    "producer-provider-in-replay": summary_edit("producer.kind", "provider"),
    "producer-unknown-kind": summary_edit("producer.kind", "model"),
    "verifier-independent-in-replay": summary_edit("verifier.kind", "independent-verifier"),
    "producer-model-in-replay": summary_edit("producer.model", "model-x"),
    "producer-effort-in-replay": summary_edit("producer.reasoningEffort", "high"),
    "verifier-model-in-replay": summary_edit("verifier.model", "model-x"),
    "producer-extra-key": summary_edit("producer.extra", 1),
    "verifier-key-missing": lambda b: issue_summary(b)["verifier"].pop("adapterIdentity"),
    "producer-prompt-empty": summary_edit("producer.promptVersion", ""),
    "producer-schema-digest-short": summary_edit("producer.schemaDigest", "abc"),
    "verifier-request-digest-short": summary_edit("verifier.requestDigest", "abc"),
    "available-with-code": summary_edit("code", "verifier-hold"),
    "status-other": summary_edit("status", "ready"),
    "text-key-missing": lambda b: issue_summary(b).pop("text"),
}
# Changes to what the summary RESTS ON (its basis): every one leaves a stale summary behind, and `resummarize` re-derives it.
SUMMARY_BASIS_CHANGES = {
    "issue-title": lambda b: (b["issues"][0].update(title="합성 공급 계약 (정정)"), b["issues"][0]["mentions"][0].update(title="합성 공급 계약 (정정)")),   # headline = selected mention
    "issue-id": lambda b: b["issues"][0].update(id="issue:synthetic-other"),
    "quote-hash": lambda b: b["evidence"][0].update(quoteSha256="f" * 64),
    "quote-start": lambda b: b["evidence"][0].update(start=13),
    "quote-end": lambda b: b["evidence"][0].update(end=49),
    "article-text-hash": lambda b: b["articles"][0].update(textSha256="6" * 64),
    "article-document-id": lambda b: b["articles"][0].update(documentId="synthetic-doc-9"),
    "article-document-version": lambda b: b["articles"][0].update(documentVersion="d" * 64),
    "mention-background": lambda b: b["issues"][0]["mentions"][0].update(background=True),
    "one-more-quote": lambda b: with_quotes(b, 1),
}
# Changes to everything ELSE of the bundle: the summary stays exactly valid.
SUMMARY_NOT_BASIS = {
    "article-title-and-url": lambda b: b["articles"][0].update(title="다른 기사 제목", url="https://example.invalid/news/2"),
    "article-published-at": lambda b: b["articles"][0].update(publishedAt="2026-09-29T01:00:00+00:00"),
    "mention-values": lambda b: b["issues"][0]["mentions"][0].update(title="다른 멘션 제목", action="다른 행위", participants=[]),
    "company-label": lambda b: b["companies"][0].update(label="다른 라벨"),
    "geography-countries": lambda b: (b["issues"][0]["geography"].update(countries=["KR", "US"], value="international"),
                                      [row.update(countries=["KR", "US"]) for row in b["issues"][0]["geography"]["basis"]]),
    "verdict-removed": lambda b: b["issues"][0].update(fieldVerdicts=[]),
    "impact-proposal": lambda b: b["impacts"][0]["proposal"].update(reason="다른 제안"),
}


# The edits below are legal for the PRODUCER's own validator apart from the summary rule they target (an edit of the issue id, an evidence offset or an article's document id
# would also break referential closure the service never checks), so they are the ones the differential corpus may use.
DIFFERENTIAL_BASIS_CHANGES = ("issue-title", "quote-hash", "article-text-hash", "mention-background", "one-more-quote")


def summary_corpus() -> dict[str, dict[str, Any]]:
    """name -> a bundle (every outer digest re-sealed), covering every summary rule with legal and illegal values: each outcome, live provenance, a multi-quote summary, the
    quote cap at 60/61, a held issue with every other outcome, every content tamper, a stale and a re-pinned summary per basis change, side evidence and cross-mode swaps.
    The service's closed model and the producer's `validate_bundle` must agree on EVERY entry (`pipeline_tests/test_handoff_real_cli.py`)."""
    corpus: dict[str, dict[str, Any]] = {}
    for outcome in ("available", "not-requested", "temporal-review-pending", "verifier-hold", "producer-invalid", "verifier-reject"):
        corpus[f"outcome:{outcome}"] = example_bundle(outcome)
    live = live_bundle()
    corpus["live"] = live
    corpus["multi-quote"] = resummarize(with_quotes(copy.deepcopy(example_bundle()), 4))
    for name, change in SUMMARY_TAMPER.items():
        tampered = copy.deepcopy(example_bundle())
        change(tampered)
        corpus[f"tamper:{name}"] = seal(tampered)
    for name in DIFFERENTIAL_BASIS_CHANGES:
        for outcome in ("available", "verifier-hold"):
            changed = copy.deepcopy(example_bundle(outcome))
            SUMMARY_BASIS_CHANGES[name](changed)
            corpus[f"stale:{name}:{outcome}"] = seal(copy.deepcopy(changed))
            corpus[f"repinned:{name}:{outcome}"] = resummarize(changed)
    held = example_bundle("temporal-review-pending")
    for outcome in ("available", "not-requested", "input-too-large", "verifier-hold", "producer-invalid", "verifier-reject"):
        other = copy.deepcopy(held)
        other["issues"][0]["summary"] = summary_of(other, outcome)
        corpus[f"held:{outcome}"] = seal(other)
    for quotes in (59, 60, 61):
        grown = with_quotes(copy.deepcopy(example_bundle()), quotes - 1)
        for outcome in ("available", "not-requested", "verifier-hold", "input-too-large", "temporal-review-pending"):
            other = copy.deepcopy(grown)
            other["issues"][0]["summary"] = summary_of(other, outcome)
            corpus[f"quotes:{quotes}:{outcome}"] = seal(other)
    for where in ("geography", "verdict"):
        side = copy.deepcopy(example_bundle())
        ident = with_side_evidence(side, where)
        corpus[f"side:{where}:unused"] = seal(copy.deepcopy(side))
        side["issues"][0]["summary"] = assemble(side, ["합성기업이 공급 계약을 발표했다."], [[ident]])
        corpus[f"side:{where}:cited"] = seal(side)
    replay_in_live = copy.deepcopy(live)
    replay_in_live["issues"][0]["summary"] = copy.deepcopy(example_bundle()["issues"][0]["summary"])
    corpus["swap:replay-summary-in-live-bundle"] = seal(replay_in_live)
    live_in_replay = copy.deepcopy(example_bundle())
    live_in_replay["issues"][0]["summary"] = copy.deepcopy(live["issues"][0]["summary"])
    corpus["swap:live-summary-in-replay-bundle"] = seal(live_in_replay)
    for index, change in enumerate((lambda s: s["producer"].update(model=None), lambda s: s["producer"].update(reasoningEffort=None), lambda s: s["verifier"].update(model=None),
                                    lambda s: s["producer"].update(kind="authored-replay"), lambda s: s["verifier"].update(kind="authored-replay"))):
        broken = copy.deepcopy(live)
        change(broken["issues"][0]["summary"])
        corpus[f"live-identity:{index}"] = seal(reseal(broken))
    for index, value in enumerate(SUMMARY_TIME_ACCEPTED):               # the strict `generatedAt` grammar, identities recomputed: only the time can decide
        timed = copy.deepcopy(example_bundle())
        issue_summary(timed)["generatedAt"] = value
        corpus[f"time:accept:{index}"] = seal(reseal(timed))
    for index, value in enumerate(SUMMARY_TIME_REFUSED):
        timed = copy.deepcopy(example_bundle())
        issue_summary(timed)["generatedAt"] = value
        corpus[f"time:refuse:{index}"] = seal(reseal(timed))
    return corpus


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
    judges no semantics but the impact rows and the issue summary, so this is what the model-level tests mutate. Its issue carries a HOLD verdict (on the second,
    non-selected mention), so its summary is exactly `temporal-review-pending`."""
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
    # the representative is the first mention's source event and the second mention differs in every headline value but the action: the selection rule is the
    # operator's representative, and only the action list names both mentions (exact equality, null equals null)
    refs = [{key: mention[key] for key in ("documentId", "documentVersion", "mentionId")} for mention in bundle["issues"][0]["mentions"]]
    bundle["issues"][0]["fieldProvenance"] = {
        "selection": "operator-representative", "verification": "none", "withheld": [],
        "sameValueMentions": {"title": [refs[0]], "action": list(refs), "target": [refs[0]], "eventTime": [refs[0]], "period": [refs[0]], "assertionStatus": [refs[0]]}}
    # one more operator verdict, on the NON-selected mention's period (HOLD/ambiguous keeps spans); it changes no headline value
    bundle["issues"][0]["fieldVerdicts"].append({
        **refs[1], "field": "period", "value": "2026Q4", "decision": "HOLD", "reasonCode": "ambiguous", "evidenceIds": [evidence_id],
        "verification": "operator-field-verdict", "reviewer": "reviewer-2", "decisionRef": "field-2026-10-21:2", "decisionVersion": "v1"})
    bundle["sources"].append({**copy.deepcopy(bundle["sources"][0]), "relation": {"jobId": "s3-synthetic-relation-2", "inputDigest": "7" * 64}})
    structural(bundle, hops=2, middle="private")     # a complete two-link path over a private (non-public) mapped middle company
    relation = bundle["relations"][-1]
    relation["basis"][0].update(validUntil="2026-12-31", countries=["KR"], verifiedAt="2026-10-01T00:00:00+00:00",
                                sourceArticles=[{"articleId": article["articleId"], "articleVersion": article["articleVersion"]}])
    relation.update(decisionRef="structural-1", sourceRefs=[{"kind": "s3-relation", "jobId": job["jobId"], "id": "rc-" + "4" * 64}])
    bundle["relations"].append({
        "id": "edge-" + "d" * 64, "type": "FOLLOWS", "source": "issue:synthetic-supply", "target": "issue:synthetic-earlier", "role": None, "assertionStatus": None,
        "evidenceIds": [evidence_id], "basis": [], "structuralPath": None,
        "provenance": {"origin": "s2-comparison-with-operator-decision", "s3SemanticValidation": "none", "s2Relation": "FOLLOWS",
                       "evidenceGate": "exact-source-citation-in-incoming-article", "groupDigest": "e" * 64, "decisionRef": "follows-1", "decisionVersion": "v1"},
        "decisionRef": "follows-1", "sourceRefs": [{"kind": "s2-comparison", "jobId": event["upstream"]["jobId"], "id": "evc-" + "3" * 64 + ">event-1"}]})
    bundle["exclusions"] = {"counts": {"geography_unproven": 1, "issue_metadata_conflict": 1, "applicability_binding_mismatch": 1},
                            "items": [{"kind": "issue", "id": "issue:x", "jobId": None, "code": "geography_unproven"},
                                      {"kind": "issue", "id": "issue:y", "jobId": job["jobId"], "code": "issue_metadata_conflict",
                                       "detail": {"fields": ["title", "eventTime"]}},
                                      {"kind": "structural", "id": "issue:z", "jobId": None, "code": "applicability_binding_mismatch",
                                       "detail": {"expectedBindingDigest": "f" * 64}}]}
    bundle["counts"]["relations"] = {name: sum(r["type"] == name for r in bundle["relations"]) for name in ("INVOLVES", "STRUCTURALLY_RELATED_TO", "FOLLOWS")}
    bundle["counts"]["exclusions"] = len(bundle["exclusions"]["items"])
    # a HOLD verdict on ANY mention (here the non-selected one) leaves the issue exactly `temporal-review-pending`: no summary text exists for it
    bundle["issues"][0]["summary"] = summary_of(bundle, "temporal-review-pending")
    return seal(bundle)
