"""Requirement 76: users see the active published graph version; publishing and rollback are explicit and logged."""

from __future__ import annotations

import stat

from fastapi.testclient import TestClient

from .conftest import ALPHA_ISSUES, DEMO, base_payload

ALLOWED_Q2 = "candidate-4ba793fe64ad22a83e594716"


def _ledger_without_q2():
    payload = base_payload()
    payload["issues"] = [i for i in payload["issues"] if i["issue_id"] != ALPHA_ISSUES["q2"]]
    return payload


def _events(kit) -> set[str]:
    return {e["id"] for e in kit.client.get("/api/events").json()["items"]}


def _versions(kit):
    return kit.client.get("/api/admin/graph/versions").json()


def test_first_start_registers_the_snapshot_as_v1_and_responses_carry_the_version(admin):
    body = _versions(admin)
    assert body["activeVersionId"] == "v1"
    (v1,) = body["items"]
    assert (v1["id"], v1["kind"], v1["active"], v1["sequence"]) == ("v1", "seed", True, 1)
    assert v1["issueCount"] == 3 and v1["synthetic"] is True and len(v1["sha256"]) == 64
    assert body["activations"][0]["action"] == "seed"

    assert admin.client.get("/api/graph").json()["metadata"]["graphVersion"] == "v1"
    assert admin.client.get(f"/api/events/{ALPHA_ISSUES['q1']}").json()["metadata"]["graphVersion"] == "v1"
    assert admin.client.get("/api/health").json()["graphVersion"] == "v1"


def test_publishing_replaces_what_users_see_and_rollback_restores_it(make_admin):
    kit = make_admin(ledger_payload=_ledger_without_q2())
    kit.login()
    assert ALPHA_ISSUES["q2"] in _events(kit)
    v1_sha = _versions(kit)["items"][0]["sha256"]

    published = kit.client.post("/api/admin/graph/versions", json={"reason": "원장 반영"})
    assert published.status_code == 201, published.text
    assert published.json()["previousActiveVersionId"] == "v1"
    v2 = published.json()["version"]
    assert (v2["id"], v2["kind"], v2["active"], v2["issueCount"], v2["createdBy"]) == ("v2", "ledger", True, 2, "admin@zoop.local")
    assert v2["policyVersion"] and v2["sourceLabel"] == "ledger:fake_ledger" and v2["reason"] == "원장 반영"
    assert ALPHA_ISSUES["q2"] not in _events(kit)
    assert kit.client.get("/api/graph").json()["metadata"]["graphVersion"] == "v2"

    # The ledger now equals the active version: nothing new to publish.
    again = kit.client.post("/api/admin/graph/versions", json={"reason": "한 번 더"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "version_unchanged"
    assert again.json()["error"]["details"]["activeVersionId"] == "v2"

    back = kit.client.post("/api/admin/graph/versions/v1/activate", json={"reason": "되돌리기"})
    assert back.status_code == 200
    assert back.json() == {"activeVersionId": "v1", "previousActiveVersionId": "v2", "idempotent": False}
    assert ALPHA_ISSUES["q2"] in _events(kit)
    assert kit.client.get("/api/graph").json()["metadata"]["graphVersion"] == "v1"

    repeat = kit.client.post("/api/admin/graph/versions/v1/activate", json={"reason": "다시"})
    assert repeat.json()["idempotent"] is True
    assert kit.client.post("/api/admin/graph/versions/v9/activate", json={"reason": "없음"}).status_code == 404

    listing = _versions(kit)
    assert [(a["versionId"], a["action"]) for a in listing["activations"]] == [("v1", "activate"), ("v2", "publish"), ("v1", "seed")]
    v1 = next(v for v in listing["items"] if v["id"] == "v1")
    assert v1["sha256"] == v1_sha  # a version is never rewritten
    actions = [e["action"] for e in kit.client.get("/api/admin/audit-log").json()["items"]]
    assert actions.count("graph.publish") == 1 and actions.count("graph.activate") == 1  # the repeat left no entry


def test_version_files_are_read_only_and_tampering_is_detected(admin):
    version_file = admin.state_dir / "graph" / "v1.json"
    assert not (version_file.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    assert admin.client.get("/api/events").status_code == 200

    version_file.chmod(0o644)
    version_file.write_text(version_file.read_text().replace("합성", "변조"), encoding="utf-8")
    response = admin.client.get("/api/events")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "source_unavailable"
    assert response.json()["error"]["details"]["cause"] == "ChecksumMismatch"


def test_review_records_apply_over_every_version_and_survive_a_restart(make_admin):
    kit = make_admin(ledger_payload=_ledger_without_q2())
    kit.login()
    assert kit.client.post(
        f"/api/admin/pipeline/candidates/{ALLOWED_Q2}/decision", json={"decision": "reject", "reason": "오승인"}
    ).status_code == 200
    assert kit.client.post("/api/admin/graph/versions", json={"reason": "반영"}).status_code == 201
    assert kit.client.post("/api/admin/graph/versions/v1/activate", json={"reason": "되돌림"}).status_code == 200
    assert ALPHA_ISSUES["q2"] not in _events(kit)  # still rejected on the older version

    restarted = kit.restart()
    restarted.login()
    listing = _versions(restarted)
    assert listing["activeVersionId"] == "v1" and [v["id"] for v in listing["items"]] == ["v2", "v1"]
    assert ALPHA_ISSUES["q2"] not in _events(restarted)
    seeds = [a for a in listing["activations"] if a["action"] == "seed"]
    assert len(seeds) == 1  # the restart did not register the snapshot again


def test_a_dead_ledger_only_blocks_the_ledger_apis(admin):
    admin.ledger.down = True
    for url in ("/api/admin/pipeline/overview", "/api/admin/pipeline/candidates", f"/api/admin/pipeline/candidates/{ALLOWED_Q2}"):
        response = admin.client.get(url)
        assert response.status_code == 503, url
        assert response.json()["error"]["code"] == "ledger_unavailable"
    publish = admin.client.post("/api/admin/graph/versions", json={"reason": "반영"})
    assert publish.status_code == 503 and publish.json()["error"]["code"] == "ledger_unavailable"
    decide = admin.client.post(
        f"/api/admin/pipeline/candidates/{ALLOWED_Q2}/decision", json={"decision": "reject", "reason": "x"}
    )
    assert decide.status_code == 503

    # Everything that does not need the ledger keeps working, including what users see.
    assert admin.client.get("/api/events").status_code == 200
    assert _versions(admin)["activeVersionId"] == "v1"
    dashboard = admin.client.get("/api/admin/dashboard")
    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["ledger"]["status"] == "unavailable" and body["ledger"]["error"]["code"] == "ledger_unavailable"
    assert body["candidates"] is None and body["graph"]["graphDb"] is None
    assert body["graph"]["activeVersionId"] == "v1"

    admin.ledger.down = False
    assert admin.client.get("/api/admin/dashboard").json()["ledger"]["status"] == "connected"


def test_graphdb_reflection_is_measured_from_the_outbox_and_neo4j(admin):
    def projection():
        return admin.client.get("/api/admin/pipeline/overview").json()["projection"]

    reflected = projection()
    assert reflected["status"] == "reflected" and reflected["pendingJobs"] == 0
    assert reflected["neo4j"]["status"] == "reachable" and reflected["neo4j"]["issuesInLedger"] == 3

    admin.ledger.pending = 2
    admin.services.pipeline.forget()
    pending = projection()
    assert pending["status"] == "pending" and pending["pendingJobs"] == 2 and pending["oldestPendingAt"]

    admin.ledger.pending = 0
    admin.neo4j.drop = {ALPHA_ISSUES["q1"]}
    admin.services.pipeline.forget()
    mismatch = projection()
    assert mismatch["status"] == "mismatch" and mismatch["neo4j"]["missingIssueIds"] == [ALPHA_ISSUES["q1"]]

    # Neo4j also holds an issue the ledger never had (the shared instance projects other ledgers too):
    # reported, counted in the same unit as the ledger (3 of 3 ledger issues reflected), not "unreflected".
    admin.neo4j.drop = set()
    admin.neo4j.extra = {"issue-elsewhere": set()}
    admin.services.pipeline.forget()
    foreign = projection()
    assert foreign["status"] == "reflected" and foreign["neo4j"]["staleIssueIds"] == ["issue-elsewhere"]
    assert (foreign["neo4j"]["issuesProjected"], foreign["neo4j"]["issuesInLedger"]) == (3, 3)
    assert foreign["neo4j"]["missingIssueIds"] == []

    # Publishing a graph version never touches GraphDB, so it cannot change the reflection result.
    assert admin.client.post("/api/admin/graph/versions", json={"reason": "반영"}).status_code in (201, 409)
    admin.services.pipeline.forget()
    assert projection()["status"] == "reflected"

    # A ledger issue whose projection holds relations the ledger no longer has is a real divergence.
    admin.neo4j.extra = {ALPHA_ISSUES["q1"]: {"relation-gone"}}
    admin.services.pipeline.forget()
    diverged = projection()
    assert diverged["status"] == "mismatch" and ALPHA_ISSUES["q1"] in diverged["neo4j"]["staleIssueIds"]

    admin.neo4j.extra = {}
    admin.neo4j.down = True
    admin.services.pipeline.forget()
    down = projection()
    assert down["status"] == "unavailable" and down["neo4j"]["status"] == "unreachable"
    assert down["neo4j"]["error"]["code"] == "neo4j_unreachable"
    assert admin.client.get("/api/admin/dashboard").json()["graph"]["graphDb"]["status"] == "unavailable"


def test_overview_compares_the_ledger_with_the_active_version(make_admin):
    kit = make_admin(ledger_payload=_ledger_without_q2())
    kit.login()
    overview = kit.client.get("/api/admin/pipeline/overview").json()
    assert overview["publication"]["ledgerMatchesActive"] is False
    assert overview["publication"]["issuesOnlyInActive"] == [ALPHA_ISSUES["q2"]]
    assert overview["policy"]["decisionPolicy"] == {"supportMin": 0.65, "contradictionMax": 0.1, "rejectMin": 0.9}
    assert overview["candidates"]["hold"] == 1 and overview["review"]["holdPendingReview"] == 1

    kit.client.post("/api/admin/graph/versions", json={"reason": "반영"})
    overview = kit.client.get("/api/admin/pipeline/overview").json()
    assert overview["publication"]["ledgerMatchesActive"] is True
    assert overview["publication"]["issuesOnlyInLedger"] == [] and overview["publication"]["issuesOnlyInActive"] == []


def test_saved_member_settings_survive_publishing_and_rolling_back_a_version(make_admin):
    # NEW exists only in the ledger, so only version v2 knows it.
    ledger = base_payload()
    q2 = next(i for i in ledger["issues"] if i["issue_id"] == ALPHA_ISSUES["q2"])
    q2["mentions"][0]["participants"].append({"company_id": "KRX:NEW1", "name": "신규기업", "role": "investor"})
    kit = make_admin(ledger_payload=ledger)
    kit.login()
    assert kit.client.post("/api/admin/graph/versions", json={"reason": "신규 기업 반영"}).status_code == 201

    member = TestClient(kit.client.app)
    assert member.post("/api/auth/login", json=DEMO).status_code == 200
    version = member.get("/api/me/settings").json()["version"]
    saved = member.put("/api/me/settings", json={"version": version, "watchlistIds": ["KRX:NEW1"]})
    assert saved.status_code == 200, saved.text
    assert member.post("/api/portfolio/connections", json={"mockPortfolioId": "mock-basic"}).status_code == 201
    holdings = member.get("/api/portfolio").json()["holdings"]

    # Rolling back to v1 makes KRX:NEW1 unknown to the active data, but the member's settings stay valid.
    assert kit.client.post("/api/admin/graph/versions/v1/activate", json={"reason": "되돌림"}).status_code == 200
    assert "KRX:NEW1" not in {c["id"] for c in member.get("/api/companies").json()["items"]}
    finish = member.put(
        "/api/me/settings",
        json={"version": saved.json()["version"], "watchlistIds": ["KRX:NEW1"], "completed": True, "tutorialCompleted": True},
    )
    assert finish.status_code == 200, finish.text
    assert finish.json()["watchlistIds"] == ["KRX:NEW1"] and finish.json()["completed"] is True
    assert member.get("/api/portfolio").json()["holdings"] == holdings  # the connected account is frozen too
    assert member.get("/api/graph?mode=personal").status_code == 200

    # Unknown ids are still rejected: only companies some published version knows (or the catalog) are valid.
    unknown = member.put(
        "/api/me/settings", json={"version": finish.json()["version"], "watchlistIds": ["KRX:NEW1", "KRX:NEVER"]}
    )
    assert unknown.status_code == 422 and unknown.json()["error"]["details"]["companyIds"] == ["KRX:NEVER"]
