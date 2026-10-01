"""Publication rule R1@2: a HOLD candidate whose only unconfirmed claims are role texts is published without them."""

from __future__ import annotations

import copy

import pytest

from .conftest import ALPHA_ISSUES, HELD_ISSUE, base_payload

HOLD = "candidate-a14f9dee7d35615c950a6830"  # HOLD in the synthetic fixture: issue HELD_ISSUE, one participant, REPORTS + INVOLVES
INVOLVES = "relation-9acf00cab494f2342b33d605"
REPORTS = "relation-345ac4a744e9ed406034d14c"
REVIEW = "Support or contradiction probability requires review: "


def _row(payload, candidate=HOLD):
    return next(c for c in payload["candidates"] if c["candidate"]["candidate_id"] == candidate)


def role_only(payload, *, participants="participant_role:0", relation_role=False):
    """Make the fixture's HOLD candidate fail on role checks alone (as the PoC verifier words it)."""
    verdicts = {v["target"]: v for v in _row(payload)["validation"]["verdicts"]}
    verdicts["issue"].update(decision="HOLD", reason=REVIEW + participants)
    if relation_role:
        verdicts[INVOLVES].update(decision="HOLD", reason=REVIEW + "role")
    return payload


def role_only_payload(**options):
    return role_only(base_payload(), **options)


def _events(kit) -> set[str]:
    return {e["id"] for e in kit.client.get("/api/events").json()["items"]}


def _event(kit):
    return kit.client.get(f"/api/events/{HELD_ISSUE}").json()


def _switch(kit, enabled, reason="규칙 점검"):
    return kit.client.put("/api/admin/pipeline/rules/R1@2", json={"enabled": enabled, "reason": reason})


def _decide(kit, decision, **extra):
    return kit.client.post(
        f"/api/admin/pipeline/candidates/{HOLD}/decision", json={"decision": decision, "reason": "검수", **extra}
    )


def test_a_role_only_hold_is_published_without_the_unconfirmed_roles(make_admin):
    kit = make_admin(role_only_payload(relation_role=True))
    kit.login()
    assert HELD_ISSUE in _events(kit)  # the rule is on by default

    event = _event(kit)
    assert event["approval"] == {"source": "review-rule", "label": "자동 검수 규칙", "scope": "issue", "ruleId": "R1@2"}
    (participant,) = event["mentions"][0]["participants"]
    assert (participant["role"], participant["roleUnconfirmed"]) == (None, True)
    relation = next(r for r in event["relations"] if r["relationType"] == "INVOLVES")
    assert (relation["role"], relation["roleUnconfirmed"]) == (None, True)
    (company,) = event["companies"]
    assert (company["role"], company["roleUnconfirmed"]) == (None, True)
    assert event["evidenceIds"], "the quotes stay the event's evidence"
    other = next(e for e in kit.client.get("/api/events").json()["items"] if e["id"] != HELD_ISSUE)
    assert kit.client.get(f"/api/events/{other['id']}").json()["approval"] is None


def test_roles_the_verifier_did_confirm_are_kept(make_admin):
    kit = make_admin(role_only_payload())  # only the participant role is unconfirmed, the relation role passed
    kit.login()
    event = _event(kit)
    assert event["mentions"][0]["participants"][0]["roleUnconfirmed"] is True
    assert event["companies"][0]["role"] == "발표자" and event["companies"][0]["roleUnconfirmed"] is False


def _with_other_check(payload):
    _row(payload)["validation"]["verdicts"][0]["reason"] = REVIEW + "participant_role:0, title"


def _with_relation_check(payload):
    verdicts = {v["target"]: v for v in _row(payload)["validation"]["verdicts"]}
    verdicts[INVOLVES].update(decision="HOLD", reason=REVIEW + "role, assertion_status")


def _with_reject(payload):
    verdicts = {v["target"]: v for v in _row(payload)["validation"]["verdicts"]}
    verdicts[INVOLVES].update(decision="REJECT", reason="Source contradiction probability meets rejection policy.")


def _with_other_reason(payload):
    _row(payload)["validation"]["verdicts"][0]["reason"] = "No usable complete canonical web evidence for this assertion."


def _without_mention_quote(payload):
    _row(payload)["candidate"]["mention"]["evidence"] = []


def _without_relation_quote(payload):
    next(r for r in _row(payload)["candidate"]["relations"] if r["relation_id"] == REPORTS)["evidence"] = []


def _with_quote_not_in_the_article(payload):
    _row(payload)["candidate"]["mention"]["evidence"][0]["quote"] = "기사에 없는 문장"


def _with_unknown_participant(payload):
    _row(payload)["validation"]["verdicts"][0]["reason"] = REVIEW + "participant_role:7"


def _inactive(payload):
    _row(payload)["active"] = False


def _field_rejected(payload):
    _row(payload)["validation"]["field_verdicts"] = [{"field": "countries", "decision": "REJECT", "reason": "x"}]


@pytest.mark.parametrize(
    "mutate",
    [
        _with_other_check,
        _with_relation_check,
        _with_reject,
        _with_other_reason,
        _without_mention_quote,
        _without_relation_quote,
        _with_quote_not_in_the_article,
        _with_unknown_participant,
        _inactive,
        _field_rejected,
    ],
)
def test_the_rule_does_not_apply_beyond_its_conditions(make_admin, mutate):
    payload = role_only_payload()
    mutate(payload)
    kit = make_admin(payload)
    kit.login()
    assert HELD_ISSUE not in _events(kit)
    rows = kit.client.get("/api/admin/pipeline/candidates", params={"rule": "true"}).json()["items"]
    assert rows == []  # the admin list does not claim the rule covers it either


def test_the_switch_takes_the_event_off_and_back_and_repeats_are_idempotent(make_admin):
    kit = make_admin(role_only_payload())
    kit.login()
    rule = kit.client.get("/api/admin/pipeline/rules").json()["items"][0]
    assert (rule["id"], rule["enabled"], rule["defaultEnabled"], rule["history"]) == ("R1@2", True, True, [])
    assert (rule["eligible"], rule["publishedCandidates"], rule["publishedEvents"]) == (1, 1, 1)

    assert _switch(kit, True).json()["idempotent"] is True  # already on by default: nothing to record
    off = _switch(kit, False, "역할 문구 검토 중")
    assert off.status_code == 200 and off.json()["idempotent"] is False
    assert off.json()["rule"]["enabled"] is False and off.json()["rule"]["publishedEvents"] == 0
    assert HELD_ISSUE not in _events(kit)
    assert kit.client.get(f"/api/events/{HELD_ISSUE}").status_code == 404

    assert _switch(kit, False, "다시 보냄").json()["idempotent"] is True
    on = _switch(kit, True, "점검 끝")
    assert on.json()["idempotent"] is False and on.json()["rule"]["publishedEvents"] == 1
    assert HELD_ISSUE in _events(kit)

    history = kit.client.get("/api/admin/pipeline/rules").json()["items"][0]["history"]
    assert [(h["enabled"], h["reason"], h["adminEmail"]) for h in history] == [
        (True, "점검 끝", "admin@zoop.local"),
        (False, "역할 문구 검토 중", "admin@zoop.local"),
    ]
    audit = kit.client.get("/api/admin/audit-log", params={"action": "review.rule"}).json()["items"]
    assert [(a["targetId"], a["detail"]["enabled"], a["reason"]) for a in audit] == [
        ("R1@2", True, "점검 끝"),
        ("R1@2", False, "역할 문구 검토 중"),
    ]  # the repeats wrote nothing


def test_the_switch_needs_a_reason_and_a_known_rule(make_admin):
    kit = make_admin(role_only_payload())
    kit.login()
    blank = kit.client.put("/api/admin/pipeline/rules/R1@2", json={"enabled": False, "reason": ""})
    assert blank.status_code == 422 and blank.json()["error"]["code"] == "validation_error"
    truthy = kit.client.put("/api/admin/pipeline/rules/R1@2", json={"enabled": "false", "reason": "문자열"})
    assert truthy.status_code == 422
    unknown = kit.client.put("/api/admin/pipeline/rules/R9@1", json={"enabled": False, "reason": "없는 규칙"})
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "rule_not_found"
    assert HELD_ISSUE in _events(kit)
    assert kit.client.get("/api/admin/audit-log", params={"action": "review.rule"}).json()["items"] == []


def test_the_switch_survives_a_restart(make_admin):
    kit = make_admin(role_only_payload())
    kit.login()
    assert _switch(kit, False).status_code == 200
    again = kit.restart()
    again.login()
    assert again.client.get("/api/admin/pipeline/rules").json()["items"][0]["enabled"] is False
    assert HELD_ISSUE not in _events(again)


def test_an_admin_reject_beats_the_rule_and_the_switch_cannot_revive_it(make_admin):
    kit = make_admin(role_only_payload())
    kit.login()
    assert HELD_ISSUE in _events(kit)
    rejected = _decide(kit, "reject")
    assert rejected.status_code == 200 and rejected.json()["onUserGraph"] is False
    assert HELD_ISSUE not in _events(kit)

    assert _switch(kit, False).status_code == 200
    assert _switch(kit, True).status_code == 200
    assert HELD_ISSUE not in _events(kit)  # rule back on, the rejected candidate stays off
    row = kit.client.get("/api/admin/pipeline/candidates", params={"rule": "true"}).json()["items"][0]
    assert row["rule"]["applied"] is False and row["rule"]["notAppliedReason"] == "admin_decision"


def test_an_admin_allow_beats_the_rule_and_keeps_the_roles_the_admin_saw(make_admin):
    kit = make_admin(role_only_payload())
    kit.login()
    allowed = _decide(kit, "allow")
    assert allowed.status_code == 200 and allowed.json()["onUserGraph"] is True
    event = _event(kit)
    assert event["approval"] == {"source": "admin-review", "label": "관리자 승인", "scope": "issue", "ruleId": None}
    assert event["mentions"][0]["participants"][0]["role"] == "발표자"


def test_a_rejected_relation_is_left_out_while_the_rest_of_the_rule_published_event_stays(make_admin):
    kit = make_admin(role_only_payload())
    kit.login()
    assert _decide(kit, "reject", relationId=INVOLVES).status_code == 200
    assert HELD_ISSUE in _events(kit)  # as for a PoC-approved candidate, rejecting one relation does not remove the event
    event = _event(kit)
    assert [r["relationType"] for r in event["relations"]] == ["REPORTS"] and event["companies"] == []
    assert event["approval"]["source"] == "review-rule"
    row = kit.client.get("/api/admin/pipeline/candidates", params={"rule": "true"}).json()["items"][0]
    assert row["rule"]["applied"] is True and row["onUserGraph"] is True


def test_a_snapshot_exclusion_of_a_relation_applies_to_a_rule_published_candidate(make_admin):
    payload = role_only_payload()
    payload["review_exclusions"] = [
        {
            "relation_id": INVOLVES,
            "issue_id": HELD_ISSUE,
            "candidate_ids": [HOLD],
            "source": HELD_ISSUE,
            "target": "SYNTH-ALPHA",
            "authority_decision": "ALLOW",
            "publication_decision": "EXCLUDED_AFTER_MANUAL_REVIEW",
            "reason": "인용이 기업을 직접 언급하지 않음",
        }
    ]
    kit = make_admin(payload)
    kit.login()
    migrated = kit.services.reviews.current("relation", INVOLVES)
    assert migrated is not None and (migrated.decision, migrated.origin) == ("reject", "snapshot-migration")
    assert HELD_ISSUE in _events(kit)
    event = _event(kit)
    assert all(r["id"] != INVOLVES for r in event["relations"]) and event["companies"] == []


FOLLOWS = "relation-0f0110e5000000000000f011"
PREVIOUS = ALPHA_ISSUES["q1"]  # an event the rule-published event can follow


def follows_payload(status: str | None):
    """The HOLD candidate also claims to follow another published event, and the PoC passed that relation."""
    payload = role_only_payload()
    row = _row(payload)
    mention = row["candidate"]["mention"]
    if status is None:
        mention.pop("assertion_status", None)
    else:
        mention["assertion_status"] = status
    row["candidate"]["relations"].append(
        {
            "role": None,
            "basis": [],
            "source": row["candidate"]["issue_id"],
            "target": PREVIOUS,
            "evidence": copy.deepcopy(mention["evidence"]),
            "relation_id": FOLLOWS,
            "relation_type": "FOLLOWS",
            "assertion_status": None,
        }
    )
    row["validation"]["verdicts"].append({"target": FOLLOWS, "decision": "ALLOW", "reason": "Every required check satisfies the configured probability policy."})
    return payload


def test_a_rule_published_event_follows_an_earlier_one_only_when_it_has_occurred(make_admin):
    kit = make_admin(follows_payload("occurred"))
    kit.login()
    event = _event(kit)
    assert [f["id"] for f in event["follows"]["previous"]] == [PREVIOUS]
    assert any(r["id"] == FOLLOWS for r in event["relations"])
    row = kit.client.get(f"/api/admin/pipeline/candidates/{HOLD}").json()
    assert row["rule"]["droppedRelations"] == []


@pytest.mark.parametrize("status", ["planned", "forecast", "announced", "cancelled", None])
def test_a_rule_published_event_that_has_not_occurred_is_not_linked_as_a_follow_up(make_admin, status):
    kit = make_admin(follows_payload(status))
    kit.login()
    assert HELD_ISSUE in _events(kit)  # the event itself (and its company) is still published
    event = _event(kit)
    assert event["follows"] == {"previous": [], "next": []}
    assert all(r["id"] != FOLLOWS for r in event["relations"])
    assert [c["id"] for c in event["companies"]] == ["SYNTH-ALPHA"]
    graph = kit.client.get("/api/graph?mode=all").json()
    assert all(e["relationType"] != "FOLLOWS" or HELD_ISSUE not in (e["source"], e["target"]) for e in graph["edges"])
    detail = kit.client.get(f"/api/admin/pipeline/candidates/{HOLD}").json()
    assert detail["rule"]["droppedRelations"] == [FOLLOWS] and detail["rule"]["applied"] is True
    (follows,) = [r for r in detail["relations"] if r["relationId"] == FOLLOWS]
    assert follows["onUserGraph"] is False


def test_a_version_published_later_gets_the_rule_too(make_admin):
    ledger = role_only_payload()
    kit = make_admin(base_payload(), ledger_payload=ledger)  # the seed (v1) has no such candidate in it
    kit.login()
    assert HELD_ISSUE not in _events(kit)
    assert kit.client.get("/api/admin/pipeline/rules").json()["items"][0]["eligible"] == 0  # counts the active version only
    first_row = kit.client.get("/api/admin/pipeline/candidates", params={"rule": "true"}).json()["items"][0]
    assert first_row["rule"]["applied"] is False and first_row["rule"]["notAppliedReason"] == "not_published"

    published = kit.client.post("/api/admin/graph/versions", json={"reason": "원장 반영"})
    assert published.status_code == 201, published.text
    assert HELD_ISSUE in _events(kit)
    assert kit.client.get("/api/admin/pipeline/rules").json()["items"][0]["eligible"] == 1
    assert _event(kit)["approval"]["source"] == "review-rule"

    rolled_back = kit.client.post("/api/admin/graph/versions/v1/activate", json={"reason": "되돌림"})
    assert rolled_back.status_code == 200
    assert HELD_ISSUE not in _events(kit)


def test_candidate_views_show_the_rule_and_what_it_leaves_out(make_admin):
    kit = make_admin(role_only_payload(relation_role=True))
    kit.login()
    detail = kit.client.get(f"/api/admin/pipeline/candidates/{HOLD}").json()
    assert detail["rule"] == {
        "ruleId": "R1@2",
        "applied": True,
        "notAppliedReason": None,
        "withheldParticipants": [0],
        "withheldRelations": [INVOLVES],
        "droppedRelations": [],
    }
    assert detail["onUserGraph"] is True
    assert detail["mention"]["participants"][0]["role"] == "발표자"  # the admin still sees what the model claimed

    others = kit.client.get("/api/admin/pipeline/candidates", params={"rule": "false"}).json()["items"]
    assert HOLD not in {i["candidateId"] for i in others} and all(i["rule"] is None for i in others)

    _switch(kit, False)
    detail = kit.client.get(f"/api/admin/pipeline/candidates/{HOLD}").json()
    assert detail["rule"]["applied"] is False and detail["rule"]["notAppliedReason"] == "rule_disabled"
    assert detail["onUserGraph"] is False


def test_overview_and_dashboard_count_what_the_rule_published(make_admin):
    plain = make_admin()
    plain.login()
    assert plain.client.get("/api/admin/pipeline/overview").json()["review"]["holdPendingReview"] == 1

    kit = make_admin(role_only_payload())
    kit.login()
    review = kit.client.get("/api/admin/pipeline/overview").json()["review"]
    assert (review["ruleCandidates"], review["ruleEvents"], review["holdPendingReview"]) == (1, 1, 0)
    graph = kit.client.get("/api/admin/dashboard").json()
    assert graph["graph"]["rules"][0]["publishedEvents"] == 1
    assert graph["candidates"]["holdPendingReview"] == 0

    _switch(kit, False)
    review = kit.client.get("/api/admin/pipeline/overview").json()["review"]
    assert (review["ruleCandidates"], review["ruleEvents"], review["holdPendingReview"]) == (0, 0, 1)


def test_the_rule_never_edits_the_ledger_or_the_stored_version(make_admin):
    payload = role_only_payload(relation_role=True)
    before = copy.deepcopy(payload)
    kit = make_admin(payload)
    kit.login()
    assert HELD_ISSUE in _events(kit)
    assert kit.ledger.payload == before
    stored = kit.services.graphs.read_payload(kit.services.graphs.active())
    assert stored == before
