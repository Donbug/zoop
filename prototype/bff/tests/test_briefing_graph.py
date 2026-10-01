"""FS032 (D03): the relationship graph opened from a briefing keeps the relations and evidence of its own round."""

from __future__ import annotations

import json
import stat
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from .conftest import ALPHA_ISSUES, DEMO, HELD_ISSUE, base_payload
from .test_review_rules import role_only_payload

KST = timezone(timedelta(hours=9))
MORNING = "brf-2026-09-17-morning"
EVENING = "brf-2026-09-17-evening"
ALLOWED_Q2 = "candidate-4ba793fe64ad22a83e594716"  # published candidate of issue q2


def at(hour: int, minute: int = 0, day: str = "2026-09-17") -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, minute=minute, tzinfo=KST)


def _ledger_without_q2():
    payload = base_payload()
    payload["issues"] = [i for i in payload["issues"] if i["issue_id"] != ALPHA_ISSUES["q2"]]
    return payload


def _publish(kit, hour: int = 7, minute: int = 45, rid: str = MORNING):
    kit.clock.travel_to(at(hour, minute))
    assert kit.services.briefings.tick() == [rid]


def _graph(kit, rid: str = MORNING, **params):
    return kit.client.get("/api/graph", params={"round": rid, **params})


def _nodes(response) -> set[str]:
    return {n["id"] for n in response.json()["nodes"]}


def _basis(kit, rid: str = MORNING):
    return kit.client.get(f"/api/briefings/{rid}/graph")


def _reject_q2(kit):
    return kit.client.post(
        f"/api/admin/pipeline/candidates/{ALLOWED_Q2}/decision", json={"decision": "reject", "reason": "근거가 부족합니다"}
    )


def _switch_rule(kit, enabled: bool):
    return kit.client.put("/api/admin/pipeline/rules/R1@2", json={"enabled": enabled, "reason": "규칙 점검"})


def test_a_round_graph_is_what_was_published_whatever_is_reviewed_or_published_later(make_admin):
    kit = make_admin(ledger_payload=_ledger_without_q2())
    kit.login()
    _publish(kit)
    q2 = ALPHA_ISSUES["q2"]

    basis = _basis(kit).json()
    items = kit.client.get("/api/briefings").json()["items"]
    assert (basis["status"], basis["graphVersion"], basis["roundId"], basis["dataAsOf"]) == ("available", "v1", MORNING, "2026-09-17T07:40:00+09:00")
    assert basis["keyIssueIds"] == [i["eventId"] for i in items] and basis["message"] is None and basis["correctionCount"] == 0

    published = _graph(kit)
    assert published.status_code == 200 and published.json()["metadata"]["graphVersion"] == "v1"
    assert published.json() == kit.client.get("/api/graph").json()  # at publication both are the same graph
    assert q2 in _nodes(published)
    involves = next(e for e in published.json()["edges"] if e["relationType"] == "INVOLVES" and q2 in (e["source"], e["target"]))
    edge_before = kit.client.get(f"/api/graph/edges/{involves['id']}", params={"round": MORNING})
    event_before = kit.client.get(f"/api/events/{q2}", params={"round": MORNING})
    evidence_id = event_before.json()["evidenceIds"][0]
    evidence_before = kit.client.get(f"/api/evidence/{evidence_id}", params={"round": MORNING})
    company_id = next(n["id"] for n in published.json()["nodes"] if n["kind"] == "company")
    company_before = kit.client.get(f"/api/companies/{company_id}", params={"round": MORNING})
    assert 200 == edge_before.status_code == event_before.status_code == evidence_before.status_code == company_before.status_code

    version_file = kit.state_dir / "graph" / "v1.json"
    file_before = (version_file.read_bytes(), version_file.stat().st_mtime_ns, stat.S_IMODE(version_file.stat().st_mode))

    # 1) a review record removes the event from the current graph; 2) a rule switch; 3) a new graph version.
    assert _reject_q2(kit).status_code == 200
    assert q2 not in _nodes(kit.client.get("/api/graph"))
    assert kit.client.get(f"/api/events/{q2}").status_code == 404
    assert _switch_rule(kit, False).status_code == 200
    assert kit.client.post("/api/admin/graph/versions", json={"reason": "원장 반영"}).status_code == 201
    assert kit.client.get("/api/graph").json()["metadata"]["graphVersion"] == "v2"

    # The round still answers from its own moment: graph, edge, event, evidence and company panels.
    assert _graph(kit).json() == published.json()
    assert kit.client.get(f"/api/graph/edges/{involves['id']}", params={"round": MORNING}).json() == edge_before.json()
    assert kit.client.get(f"/api/events/{q2}", params={"round": MORNING}).json() == event_before.json()
    assert kit.client.get(f"/api/evidence/{evidence_id}", params={"round": MORNING}).json() == evidence_before.json()
    assert kit.client.get(f"/api/companies/{company_id}", params={"round": MORNING}).json() == company_before.json()
    assert kit.client.get(f"/api/graph/edges/{involves['id']}").status_code == 404  # the current graph no longer has it
    assert _basis(kit).json() == basis
    assert kit.client.get("/api/briefings").json()["items"] == items

    # Another round keeps its own moment too: the evening round was published from v2 and never shows v1's relations.
    kit.clock.travel_to(at(18, 15))
    assert kit.services.briefings.tick() == [EVENING]
    evening = _graph(kit, EVENING)
    assert evening.json()["metadata"]["graphVersion"] == "v2" and q2 not in _nodes(evening)
    assert q2 in _nodes(_graph(kit, MORNING))
    assert _basis(kit, EVENING).json()["graphVersion"] == "v2"

    # The published version file is neither rewritten nor made writable.
    assert (version_file.read_bytes(), version_file.stat().st_mtime_ns, stat.S_IMODE(version_file.stat().st_mode)) == file_before
    assert file_before[2] & 0o222 == 0


def test_a_publication_rule_switch_after_publishing_does_not_change_the_round(make_admin):
    kit = make_admin(role_only_payload())
    kit.login()
    assert HELD_ISSUE in {e["id"] for e in kit.client.get("/api/events").json()["items"]}  # R1@2 is on by default
    _publish(kit)
    published = _graph(kit)
    assert HELD_ISSUE in _nodes(published)
    event = kit.client.get(f"/api/events/{HELD_ISSUE}", params={"round": MORNING}).json()
    assert event["approval"]["source"] == "review-rule"

    kit.clock.advance(3600)  # the switch comes an hour after publication (rule changes are stamped to the second)
    assert _switch_rule(kit, False).status_code == 200
    assert HELD_ISSUE not in _nodes(kit.client.get("/api/graph"))
    assert _graph(kit).json() == published.json()
    assert kit.client.get(f"/api/events/{HELD_ISSUE}", params={"round": MORNING}).json() == event
    stored = kit.client.get(f"/api/admin/briefings/{MORNING}").json()["published"]
    assert stored["ruleRevision"] == 0  # recorded at publication, not the later switch

    # A round stored before the rule revision was recorded is cut by time: the rule state when it was generated.
    legacy = {k: v for k, v in stored.items() if k != "ruleRevision"}
    row = kit.services.db.one("SELECT * FROM briefing_rounds WHERE id=?", (MORNING,))
    kit.services.db.execute(
        "INSERT INTO briefing_rounds(id,date,edition,status,data,payload,updated_at) VALUES (?,?,?,?,?,?,?)",
        (EVENING, "2026-09-17", "evening", "published", row["data"], json.dumps(legacy), row["updated_at"]),
    )
    assert _basis(kit, EVENING).json()["status"] == "available"
    assert _graph(kit, EVENING).json() == published.json()


def test_a_missing_or_altered_graph_version_is_announced_and_never_replaced_by_the_newest(make_admin):
    kit = make_admin(ledger_payload=_ledger_without_q2())
    kit.login()
    _publish(kit)
    assert kit.client.post("/api/admin/graph/versions", json={"reason": "원장 반영"}).status_code == 201
    current = kit.client.get("/api/graph").json()
    assert current["metadata"]["graphVersion"] == "v2"
    published = _graph(kit).json()
    briefing = kit.client.get("/api/briefings").json()

    version_file = kit.state_dir / "graph" / "v1.json"
    original = version_file.read_bytes()
    version_file.chmod(0o644)
    version_file.write_bytes(original + b" ")
    for broken in (True, False):  # altered, then gone
        if not broken:
            version_file.unlink()
        basis = _basis(kit).json()
        assert basis["status"] == "unavailable" and "최신 자료로 바꿔 보여드리지 않아요" in basis["message"]
        assert basis["keyIssueIds"] == [] and basis["graphVersion"] == "v1"
        for path in ("/api/graph", f"/api/events/{ALPHA_ISSUES['q1']}", f"/api/graph/edges/{published['edges'][0]['id']}"):
            response = kit.client.get(path, params={"round": MORNING})
            assert response.status_code == 404 and response.json()["error"]["code"] == "briefing_graph_unavailable", path
        assert kit.client.get("/api/graph").json() == current  # the current graph is untouched
        assert kit.client.get("/api/briefings").json() == briefing  # the briefing text stays readable

    version_file.write_bytes(original)
    assert _basis(kit).json()["status"] == "available"
    assert _graph(kit).json() == published


def test_rounds_without_a_graph_to_show_say_why(make_admin):
    kit = make_admin()
    kit.login()
    _publish(kit)
    published = _graph(kit).json()

    not_yet = _basis(kit, EVENING).json()
    assert not_yet["status"] == "not_published" and not_yet["keyIssueIds"] == [] and not_yet["graphVersion"] is None
    response = _graph(kit, EVENING)
    assert response.status_code == 404 and response.json()["error"]["code"] == "briefing_not_published"
    assert _basis(kit, "not-a-round").status_code == 404
    assert _graph(kit, "not-a-round").json()["error"]["code"] == "briefing_round_not_found"

    suspend = kit.client.post(f"/api/admin/briefings/{MORNING}/suspension", json={"action": "suspend", "reason": "원문 정정 확인 중"})
    assert suspend.status_code == 200
    basis = _basis(kit).json()
    assert (basis["status"], basis["reason"], basis["keyIssueIds"], basis["companyIds"]) == ("suspended", "원문 정정 확인 중", [], [])
    for path in ("/api/graph", f"/api/events/{ALPHA_ISSUES['q1']}", "/api/evidence/anything"):
        denied = kit.client.get(path, params={"round": MORNING})
        assert denied.status_code == 403 and denied.json()["error"]["code"] == "briefing_round_suspended", path

    kit.client.post(f"/api/admin/briefings/{MORNING}/suspension", json={"action": "resume", "reason": "확인 끝"})
    assert _basis(kit).json()["status"] == "available"
    assert _graph(kit).json() == published


def test_a_correction_sits_beside_the_graph_without_changing_it(make_admin):
    kit = make_admin()
    kit.login()
    _publish(kit)
    published = _graph(kit).json()
    first = kit.client.get("/api/briefings").json()["items"][0]
    done = kit.client.post(
        f"/api/admin/briefings/{MORNING}/corrections",
        json={"eventId": first["eventId"], "correctedText": "정정된 제목입니다", "reason": "수치 오기"},
    )
    assert done.status_code == 201
    assert _basis(kit).json()["correctionCount"] == 1
    assert _graph(kit).json() == published


def test_only_the_market_wide_map_exists_for_a_round(make_admin):
    kit = make_admin()
    kit.login()
    _publish(kit)
    member = TestClient(kit.client.app)
    assert member.post("/api/auth/login", json=DEMO).status_code == 200
    response = member.get("/api/graph", params={"round": MORNING, "mode": "personal"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "round_all_only"
    assert member.get("/api/graph", params={"round": MORNING, "mode": "all"}).status_code == 200
