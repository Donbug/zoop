#!/usr/bin/env python3
"""Synthetic public G/T contract proof and shared Python/service/Java fixtures; no provider calls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import graph_handoff_smoke as hs


def build(root: Path, public_ids: dict | None = None) -> tuple:
    world = hs.build_world(root, a_countries=(), a2_countries=(), event_time="10.19일", a2_event_time="'25.8월",
                           raw_time_evidence=True, dated=True)
    verdicts = {"issue:supply": [
        hs.field_verdict(world, "a", "m-a", "eventTime", "10.19일", "HOLD", "unsupported-format", ["10.19일"]),
        hs.field_verdict(world, "a2", "m-a2", "eventTime", "'25.8월", "HOLD", "unsupported-format", ["'25.8월"])]}
    decisions = hs.decisions_doc(world, verdicts=verdicts, published_time=None)
    if public_ids:
        for company in decisions["companies"]:
            company["publicId"] = public_ids[company["publicId"]]
    hs.write_operator(world, decisions=decisions)
    operator = hs.Operator(world)
    before = {name: hs.tree(root / name) for name in ("ingestion", "extraction", "relation")}
    refusals = []
    for name, change, code in (
        ("missing-nonrepresentative", lambda d: d["issues"][0]["fieldVerdicts"].pop(), "mention_event_time_unreviewed"),
        ("allow-nonrepresentative", lambda d: d["issues"][0]["fieldVerdicts"][1].update(decision="ALLOW", reasonCode="stated"), "mention_event_time_unreviewed"),
        ("stale-value", lambda d: d["issues"][0]["fieldVerdicts"][1].update(value="25.8월"), "field_verdict_stale"),
        ("wrong-mention", lambda d: d["issues"][0]["fieldVerdicts"][1].update(mentionId="other"), "field_verdict_unbound"),
        ("wrong-time-evidence", lambda d: d["issues"][0]["fieldVerdicts"][1]["evidence"][0].update(quoteSha256="0" * 64), "field_verdict_evidence_mismatch"),
        ("wrong-geography-evidence", lambda d: d["issues"][0]["geography"]["evidence"][0].update(quoteSha256="0" * 64), "geography_evidence_mismatch"),
    ):
        changed = json.loads(json.dumps(decisions))
        change(changed)
        out = hs.freeze_export(operator, world, name, changed)
        assert hs.issue_exclusions(out["bundle"], "issue:supply") == [{"kind": "issue", "id": "issue:supply", "jobId": None, "code": code}], name
        refusals.append({"name": name, "code": code})
    out = hs.freeze_export(operator, world, "handoff-unknown-fields-1", decisions)
    issue = next(i for i in out["bundle"]["issues"] if i["id"] == hs.SUPPLY)
    assert issue["geography"]["countries"] == ["KR"] and all(b["countries"] == [] for b in issue["geography"]["basis"])
    assert {m["mentionId"]: (m["eventTime"], m["timePrecision"]) for m in issue["mentions"]} == {
        "m-a": ("10.19일", "unresolved"), "m-a2": ("'25.8월", "unresolved")}
    assert (issue["eventTime"], issue["timePrecision"]) == (None, "unknown")
    assert [m["mentionId"] for m in issue["fieldProvenance"]["sameValueMentions"]["eventTime"]] == ["m-a"]
    assert issue["summary"] == {"status": "unavailable", "code": "temporal-review-pending", "source": None}
    assert out["bundle"]["exclusions"]["counts"]["basis_validity_unprovable"] == 1
    assert {name: hs.tree(root / name) for name in before} == before
    world.unknown_refusals = refusals
    return world, out


def cases(bundle: dict) -> dict:
    """Each synthetic mutation keeps a recomputed content digest, so its targeted contract rule decides."""
    accepted, rejected = [{"name": "all-unknown-grounded-held", "bundle": bundle}], []

    def case(name, change, *, valid=False):
        copy = json.loads(json.dumps(bundle))
        issue = next(i for i in copy["issues"] if i["id"] == hs.SUPPLY)
        change(copy, issue)
        copy["digests"]["content"] = hs.content_digest(copy)
        (accepted if valid else rejected).append({"name": name, "bundle": copy})

    case("mixed-unknown-KR", lambda b, i: i["geography"]["basis"][0].update(countries=["KR"]), valid=True)
    case("ambiguous-preserved", lambda b, i: [v.update(reasonCode="ambiguous") for v in i["fieldVerdicts"]], valid=True)
    case("contradicted-preserved", lambda b, i: [v.update(decision="REJECT", reasonCode="contradicted") for v in i["fieldVerdicts"]], valid=True)
    for countries in (["US"], ["KR", "US"]):
        case("country-conflict-" + "-".join(countries), lambda b, i, c=countries: i["geography"]["basis"][0].update(countries=c))
    case("decision-superset", lambda b, i: (i["geography"].update(countries=["KR", "US"], value="international"),
                                           i["geography"]["basis"][0].update(countries=["KR"])))
    case("empty-decision", lambda b, i: i["geography"].update(countries=[]))
    case("malformed-code", lambda b, i: i["geography"].update(countries=["kr"]))
    case("wrong-class", lambda b, i: i["geography"].update(value="international"))
    case("empty-geography-evidence", lambda b, i: i["geography"].update(evidenceIds=[]))
    for mention in ("m-a", "m-a2"):
        case("unreviewed-" + mention, lambda b, i, m=mention: i.update(fieldVerdicts=[v for v in i["fieldVerdicts"] if v["mentionId"] != m]))
        case("allow-" + mention, lambda b, i, m=mention: next(v for v in i["fieldVerdicts"] if v["mentionId"] == m).update(decision="ALLOW", reasonCode="stated"))
    case("stale-verdict-value", lambda b, i: i["fieldVerdicts"][0].update(value="changed"))
    case("wrong-verdict-mention", lambda b, i: i["fieldVerdicts"][0].update(mentionId="other"))
    case("wrong-verdict-version", lambda b, i: i["fieldVerdicts"][0].update(documentVersion="0" * 64))
    case("missing-format-evidence", lambda b, i: i["fieldVerdicts"][0].update(evidenceIds=[]))
    case("foreign-verdict-evidence", lambda b, i: i["fieldVerdicts"][0].update(
        evidenceIds=next(x for x in b["issues"] if x["id"] == hs.FACTORY)["mentions"][0]["evidenceIds"]))
    case("unsupported-public-headline", lambda b, i: i.update(eventTime="10.19일", timePrecision="unresolved"))
    case("raw-marked-unknown", lambda b, i: i["mentions"][0].update(timePrecision="unknown"))
    case("old-bundle-version", lambda b, i: b.update(schemaVersion=hs.BUNDLE_7))
    case("old-policy-version", lambda b, i: b["policy"].update(version="zoop-public-projection-policy-1"))
    return {"accept": accepted, "reject": rejected}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--fixtures", required=True, type=Path)
    args = parser.parse_args()
    world, exported = build(hs.new_output(args.root, real_parent=True))
    hs.put_new(args.fixtures / "export-unknown-fields.json", exported)
    hs.put_new(args.fixtures / "public-unknown-fields-cases.json", cases(exported["bundle"]))
    print(json.dumps({"status": "passed", "providerCalls": 0, "modelCalls": 0, "receipt": exported["receipt"],
                      "refusals": world.unknown_refusals}, ensure_ascii=False))
