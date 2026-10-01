"""Requirement 76: review decisions overlay the published graph; the PoC ledger is never changed."""

from __future__ import annotations

import copy

import pytest

from .conftest import ALPHA_ISSUES, HELD_ISSUE, base_payload

ALLOWED_Q2 = "candidate-4ba793fe64ad22a83e594716"  # ALLOW in the ledger, issue q2
HOLD = "candidate-a14f9dee7d35615c950a6830"  # HOLD in the ledger, issue HELD_ISSUE
Q2_INVOLVES = "relation-6912ca4c4e5d12c91ff72ed5"


def _decide(kit, candidate, decision, reason="검수 사유", **extra):
    return kit.client.post(
        f"/api/admin/pipeline/candidates/{candidate}/decision", json={"decision": decision, "reason": reason, **extra}
    )


def _public_events(kit) -> set[str]:
    return {e["id"] for e in kit.client.get("/api/events").json()["items"]}


def _audit_count(kit, action="review.decide") -> int:
    return len(kit.client.get("/api/admin/audit-log", params={"action": action}).json()["items"])


def test_reject_removes_a_published_candidate_at_once_and_repeats_are_idempotent(admin):
    ledger_before = copy.deepcopy(admin.ledger.payload)
    assert ALPHA_ISSUES["q2"] in _public_events(admin)

    first = _decide(admin, ALLOWED_Q2, "reject", "근거가 부족합니다")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["idempotent"] is False and body["onUserGraph"] is False and body["graphVersion"] == "v1"
    assert body["decision"]["decision"] == "reject" and body["decision"]["adminEmail"] == "admin@zoop.local"
    assert ALPHA_ISSUES["q2"] not in _public_events(admin)
    graph = admin.client.get("/api/graph?mode=all").json()
    assert ALPHA_ISSUES["q2"] not in {n["id"] for n in graph["nodes"]}
    assert admin.client.get(f"/api/events/{ALPHA_ISSUES['q2']}").status_code == 404

    repeat = _decide(admin, ALLOWED_Q2, "reject", "다시 보냄")
    assert repeat.json()["idempotent"] is True
    assert repeat.json()["decision"]["id"] == body["decision"]["id"]
    assert repeat.json()["reviewRevision"] == body["reviewRevision"]
    assert _audit_count(admin) == 1  # the repeat wrote no record and no audit entry

    assert admin.ledger.payload == ledger_before  # the ledger is read, never written


def test_a_later_opposite_decision_replaces_the_earlier_one_and_keeps_history(admin):
    assert _decide(admin, ALLOWED_Q2, "reject").status_code == 200
    again = _decide(admin, ALLOWED_Q2, "allow", "다시 확인해 보니 맞습니다")
    assert again.status_code == 200 and again.json()["idempotent"] is False
    assert again.json()["onUserGraph"] is True
    assert ALPHA_ISSUES["q2"] in _public_events(admin)

    detail = admin.client.get(f"/api/admin/pipeline/candidates/{ALLOWED_Q2}").json()
    assert detail["decision"]["decision"] == "allow"
    assert [h["decision"] for h in detail["history"]] == ["allow", "reject"]  # newest first, nothing erased


def test_allowing_a_hold_candidate_publishes_it_marked_as_an_admin_approval(admin):
    assert HELD_ISSUE not in _public_events(admin)
    row = admin.client.get("/api/admin/pipeline/candidates", params={"status": "HOLD"}).json()["items"][0]
    assert row["candidateId"] == HOLD and row["onUserGraph"] is False and row["decision"] is None

    response = _decide(admin, HOLD, "allow", "원문 인용을 직접 확인했습니다")
    assert response.status_code == 200, response.text
    assert response.json()["onUserGraph"] is True
    assert HELD_ISSUE in _public_events(admin)
    event = admin.client.get(f"/api/events/{HELD_ISSUE}").json()
    assert event["approval"] == {"source": "admin-review", "label": "관리자 승인", "scope": "issue"}
    assert event["evidenceIds"], "the allowed issue keeps its original quote as evidence"
    other = admin.client.get(f"/api/events/{ALPHA_ISSUES['q1']}").json()
    assert other["approval"] is None  # PoC-approved issues carry no admin label
    for evidence_id in event["evidenceIds"]:
        assert admin.client.get(f"/api/evidence/{evidence_id}").json()["quoteVerified"] in (True, None)

    # The decision can be withdrawn: rejecting takes it off the graph again.
    assert _decide(admin, HOLD, "reject", "철회").json()["onUserGraph"] is False
    assert HELD_ISSUE not in _public_events(admin)


def test_a_candidate_without_a_quote_cannot_be_allowed(make_admin):
    ledger = base_payload()
    held = next(c for c in ledger["candidates"] if c["candidate"]["candidate_id"] == HOLD)
    held["candidate"]["mention"]["evidence"] = []
    kit = make_admin(ledger_payload=ledger)
    kit.login()
    response = _decide(kit, HOLD, "allow")
    assert response.status_code == 422 and response.json()["error"]["code"] == "evidence_required"
    assert HELD_ISSUE not in _public_events(kit)


def test_reviewability_rules(make_admin):
    ledger = base_payload()
    rows = {c["candidate"]["candidate_id"]: c for c in ledger["candidates"]}
    rows[HOLD]["status"] = "REJECT"
    rows[ALLOWED_Q2]["active"] = False
    kit = make_admin(ledger_payload=ledger)
    kit.login()

    rejected = _decide(kit, HOLD, "allow")
    assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "status_not_reviewable"
    inactive = _decide(kit, ALLOWED_Q2, "reject")
    assert inactive.status_code == 409 and inactive.json()["error"]["code"] == "candidate_inactive"
    assert _decide(kit, "candidate-nope", "reject").status_code == 404
    unknown_relation = _decide(kit, "candidate-3112cdeb376c3e4aeb285c5d", "reject", relationId="relation-nope")
    assert unknown_relation.status_code == 422 and unknown_relation.json()["error"]["code"] == "unknown_relation"
    blank = _decide(kit, "candidate-3112cdeb376c3e4aeb285c5d", "reject", reason="")
    assert blank.status_code == 422 and blank.json()["error"]["code"] == "validation_error"
    assert _audit_count(kit) == 0  # nothing above changed anything


def test_a_relation_can_be_rejected_on_its_own(admin):
    def q2_company_edges():
        graph = admin.client.get("/api/graph?mode=all").json()
        return [e for e in graph["edges"] if e["relationType"] == "INVOLVES" and ALPHA_ISSUES["q2"] in (e["source"], e["target"])]

    assert q2_company_edges()
    response = _decide(admin, ALLOWED_Q2, "reject", relationId=Q2_INVOLVES)
    assert response.status_code == 200 and response.json()["decision"]["targetType"] == "relation"
    assert ALPHA_ISSUES["q2"] in _public_events(admin)  # the event stays
    assert not q2_company_edges()  # only that relation is gone

    detail = admin.client.get(f"/api/admin/pipeline/candidates/{ALLOWED_Q2}").json()
    relation = next(r for r in detail["relations"] if r["relationId"] == Q2_INVOLVES)
    assert relation["onUserGraph"] is False and relation["decision"]["decision"] == "reject"
    assert detail["onUserGraph"] is True and detail["decision"] is None


@pytest.mark.parametrize("params,expected", [
    ({"status": "HOLD"}, {HOLD}),
    ({"status": "ALLOW", "limit": 2}, {"candidate-4ba793fe64ad22a83e594716", "candidate-5fbd505e85d52ac3d7896eb5"}),
    ({"q": "A14F9DEE"}, {HOLD}),  # case-insensitive match on the candidate id
    ({"published": "false"}, {HOLD}),
])
def test_candidate_list_filters_and_counts(admin, params, expected):
    page = admin.client.get("/api/admin/pipeline/candidates", params=params).json()
    assert {i["candidateId"] for i in page["items"]} == expected
    assert page["counts"] == {"ALLOW": 4, "HOLD": 1, "REJECT": 0, "inactive": 0}


def test_candidate_list_pages_with_a_cursor_and_filters_by_decision(admin):
    first = admin.client.get("/api/admin/pipeline/candidates", params={"limit": 2}).json()
    assert len(first["items"]) == 2 and first["nextCursor"]
    second = admin.client.get("/api/admin/pipeline/candidates", params={"limit": 2, "cursor": first["nextCursor"]}).json()
    seen = [i["candidateId"] for i in first["items"] + second["items"]]
    assert len(set(seen)) == 4  # no row twice, newest first

    _decide(admin, HOLD, "reject")
    rejected = admin.client.get("/api/admin/pipeline/candidates", params={"decision": "reject"}).json()
    assert [i["candidateId"] for i in rejected["items"]] == [HOLD]
    undecided = admin.client.get("/api/admin/pipeline/candidates", params={"decision": "none"}).json()
    assert HOLD not in {i["candidateId"] for i in undecided["items"]}
