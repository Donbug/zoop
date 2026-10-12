#!/usr/bin/env python3
"""BFF-owned integration tool: generate the portable S1 synthetic document/outlook fixtures, without model calls.

The fixtures live with the worker (ai/worker/fixtures/contracts) but are produced here because they need the BFF
outlook input builder and the pinned PoC Article version. The pure S1 schema is exported by ai/worker/scripts/export_schema.py.
"""
from __future__ import annotations

import json
from pathlib import Path

from datetime import datetime
import tempfile

from investmate.domain import Article

from zoop_ai.contracts import SCHEMA_VERSION, SourceGrant, Submit, digest
from zoop_ai.provider import request_identity, stage_config
from zoop_bff.dataset import evidence_id

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "ai/worker/fixtures/contracts/synthetic-document"


def generate() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    q1, q2 = "🚀 합성 알파의 매출이 늘었다.", "합성 베타의 비용이 늘었다."
    text = q1 + " " + q2
    article = Article(article_id="doc-synthetic-s1", title="[합성] 두 기업의 상반된 사업 변화", body=text,
                      url="https://synthetic.invalid/document-s1", publisher="SYNTHETIC—not real news",
                      published_at="2026-10-08T00:00:00+00:00", collected_at="2026-10-08T00:00:00+00:00",
                      language="ko", input_kind="body", synthetic=True, allow_model_send=False, withdrawn=False)
    version = article.version
    start2 = len(q1) + 1
    evidence = [{"article_id": article.article_id, "article_version": version, "start": start,
                 "end": start + len(quote), "quote": quote} for start, quote in [(0, q1), (start2, q2)]]
    participants = [{"company_id": "SYNTH-A", "name": "합성 알파", "role": "참여자"},
                    {"company_id": "SYNTH-B", "name": "합성 베타", "role": "참여자"}]
    issue_id = "event-synthetic-s1"
    snapshot = {"issues": [{"issue_id": issue_id, "articles": [article.model_dump(mode="json")],
                            "mentions": [{"mention_id": "mention-synthetic-s1", "article_id": article.article_id,
                                          "article_version": version, "title": "두 기업의 사업 변화",
                                          "event_time": "2026-10-08", "participants": participants,
                                          "action": "실적 발표", "evidence": evidence}],
                            "relations": [{"relation_id": "rel-doc-s1", "source": article.article_id,
                                           "target": issue_id, "relation_type": "REPORTS", "evidence": evidence}] +
                                         [{"relation_id": "rel-" + p["company_id"], "source": issue_id,
                                           "target": p["company_id"], "relation_type": "INVOLVES", "evidence": evidence}
                                          for p in participants]}], "errors": [],
                "zoop": {"companies": [{"company_id": p["company_id"], "name": p["name"]} for p in participants],
                         "source_label": "S1 authored synthetic contract", "as_of": "2026-10-08T00:00:00+00:00"}}
    grant = SourceGrant(grant_id="grant-synthetic-s1", revision="grant-synthetic-s1-1", source_id="authored-synthetic",
                        enabled=True, rights="known", allowed_operations=["read", "store", "model-send", "quote-display"],
                        recipients=["authored-replay", "openai-compatible"],
                        purposes=["document-summary", "document-sentiment", "semantic-verification"],
                        evidence=["Repository-authored synthetic text, no external source data"], expires_at=None)
    document = {"documentId": article.article_id, "documentVersion": version,
                "sourceId": "authored-synthetic", "textArtifactId": "text-synthetic-s1-" + version,
                "inputKind": "body", "cleanerVersion": "synthetic-identity-1", "text": text,
                "sourceHash": digest(text), "rawLocators": [{"locatorId": "raw-synthetic-s1", "start": 0, "end": len(text)}]}
    citations = [{"evidenceId": evidence_id(article.article_id, version, ev["start"], ev["end"]),
                  "documentId": article.article_id, "documentVersion": version,
                  "textArtifactId": document["textArtifactId"], "offsetUnit": "unicode_code_point",
                  "start": ev["start"], "end": ev["end"], "quote": ev["quote"], "inputKind": "body",
                  "rawLocatorIds": ["raw-synthetic-s1"]} for ev in evidence]
    jobs, replies = [], []
    for index, company in enumerate(participants):
        for kind in ["document-summary", "document-sentiment"]:
            request = Submit.model_validate({"schemaVersion": SCHEMA_VERSION,
                "jobId": "synthetic-" + company["company_id"] + "-" + kind,
                "kind": kind, "mode": "replay",
                "input": {"document": document, "company": {"companyId": company["company_id"], "name": company["name"]},
                          "grantId": grant.grant_id, "grantRevision": grant.revision, "candidate": None},
                "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"}})
            if kind == "document-summary":
                limitation = "합성 문서에 적힌 사업 변화만 요약합니다."
                claims = [{"claimId": "claim-a", "text": q1, "assertionKind": "fact", "evidenceIds": [citations[0]["evidenceId"]]},
                          {"claimId": "claim-b", "text": q2, "assertionKind": "fact", "evidenceIds": [citations[1]["evidenceId"]]},
                          {"claimId": "claim-limitation", "text": limitation, "assertionKind": "limitation", "evidenceIds": []}]
                response = {"text": "\n".join(c["text"] for c in claims if c["assertionKind"] != "limitation"),
                            "claims": claims, "citations": citations, "limitations": [limitation]}
            else:
                rationale = "합성 알파의 매출 증가가 확인됩니다." if index == 0 else "합성 베타의 비용 증가가 확인됩니다."
                limitation = "가격 전망이 아닌 사업 사실의 판정입니다."
                claims = [{"claimId": "claim-direction", "text": rationale, "assertionKind": "interpretation", "evidenceIds": [citations[index]["evidenceId"]]},
                          {"claimId": "claim-limitation", "text": limitation, "assertionKind": "limitation", "evidenceIds": []}]
                response = {"label": "positive" if index == 0 else "negative", "rationale": rationale,
                            "claims": claims, "citations": [citations[index]], "limitations": [limitation]}
            payload = {"schemaVersion": SCHEMA_VERSION, "document": document, "company": request.input.company.wire(),
                       "grantRef": {"grantId": grant.grant_id, "revision": grant.revision}}
            replies.append({"stage": kind, "inputDigest": request_identity(kind, payload, stage_config(kind, "replay")), "response": response})
            verify_payload = {**payload, "candidate": response}
            replies.append({"stage": "semantic-verification", "inputDigest": request_identity("semantic-verification", verify_payload, stage_config("semantic-verification", "replay")),
                            "response": {"claims": [{"claimId": c["claimId"], "decision": "supported", "reason": "합성 원문과 문맥이 주장을 뒷받침합니다."} for c in claims],
                                         "prohibitedAdvice": False, "unsupportedCausality": False}})
            jobs.append(request.wire())
    files = {"jobs": {"schemaVersion": SCHEMA_VERSION, "jobs": jobs},
             "replay": {"schemaVersion": SCHEMA_VERSION, "recordingKind": "authored-test", "responses": replies},
             "snapshot": snapshot, "grants": {"schemaVersion": SCHEMA_VERSION, "grants": [grant.wire()]}}
    for name, value in files.items():
        (OUT / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    generate_outlook(snapshot)
    return files


def generate_outlook(snapshot: dict) -> None:
    from zoop_bff.admin_services import build_admin_services
    from zoop_bff.ai_worker import outlook_job
    from zoop_bff.briefing_market import MarketIndicators
    from zoop_bff.briefing_rounds import scheduled_at
    from zoop_bff.config import Settings
    from zoop_bff.sentiment import outlook_input
    output = OUT.parent / "synthetic-outlook"
    output.mkdir(parents=True, exist_ok=True)
    (output / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    moment = datetime.fromisoformat("2026-10-08T18:15:00+09:00")
    rid = "brf-2026-10-08-evening"
    with tempfile.TemporaryDirectory(prefix="zoop-outlook-contract-") as tmp:
        services = build_admin_services(Settings(snapshot_path=output / "snapshot.json", company_catalog=None,
            state_dir=Path(tmp) / "bff", poc_sandbox=Path(tmp) / "no-sandbox", quote_provider="off",
            metrics_enabled=False, briefing_scheduler=False))
        try:
            services.clock.travel_to(moment)
            preview = services.briefings.sentiment_preview(rid)
            market = MarketIndicators(None).collect(moment.date(), "evening", scheduled_at(moment.date(), "evening"), now=moment)
            version, review, (_, rule) = services.provider.source.stamp()
            payload = outlook_input(rid, scheduled_at(moment.date(), "evening").isoformat(timespec="seconds"),
                preview["items"], market.model_dump(by_alias=True, mode="json"),
                graph_version=version, review_revision=review, rule_revision=rule)
        finally:
            services.db.close()
    grant = SourceGrant(grant_id="grant-synthetic-outlook", revision="grant-synthetic-outlook-1",
        source_id="authored-synthetic-round", enabled=True, rights="known",
        allowed_operations=["read", "store", "model-send", "quote-display"], recipients=["authored-replay"],
        purposes=["briefing-outlook"], evidence=["Repository-authored synthetic round and market-unavailable inputs"], expires_at=None)
    context = {"sourceId": grant.source_id, "grantId": grant.grant_id, "grantRevision": grant.revision,
               "sourceKind": "synthetic", "mode": "replay"}
    request = Submit.model_validate(outlook_job(payload, context))
    answer = {"label": "undetermined", "rationale": "회차의 합성 사업 사실만으로 전체 유불리를 확인하기 어렵습니다.",
              "issueIds": [i["eventId"] for i in payload["issues"]]}
    recording = {"schemaVersion": SCHEMA_VERSION, "recordingKind": "authored-test", "responses": [{
        "stage": "briefing-outlook", "inputDigest": request_identity("briefing-outlook",
            {"schemaVersion": SCHEMA_VERSION, **request.input.wire()}, stage_config("briefing-outlook", "replay")), "response": answer}]}
    for name, value in {"jobs": {"schemaVersion": SCHEMA_VERSION, "jobs": [request.wire()]},
                        "grants": {"schemaVersion": SCHEMA_VERSION, "grants": [grant.wire()]}, "replay": recording}.items():
        (output / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    generate()
