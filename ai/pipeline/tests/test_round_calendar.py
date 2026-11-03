"""Calendar deadline, retrieval proof, native inventory and immutable CLI plan behavior."""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

import pytest

from tests.test_round_plan import cli_plan, sha, world  # noqa: F401
from tests.test_round_enqueue import simple_round as ingest_simple_round, tree
from zoop_ai_pipeline.extraction import Fixtures
from zoop_ai_pipeline.extraction_plan import parse_selection, verify_plan
from zoop_ai_pipeline.ingestion_contracts import Authority, IngestionFailure
from zoop_ai_pipeline.ingestion_inventory import inventory, parse_inventory
from zoop_ai_pipeline.round_calendar import CalendarEligibility


def policy(*, close_through="2026-10-18", bound=291600, start_day="2026-10-16", end_day="2026-11-05"):
    start, end = date.fromisoformat(start_day), date.fromisoformat(end_day)
    rows = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        holiday = start < day <= date.fromisoformat(close_through) and day.weekday() < 5
        rows.append({"date": str(day), "isBusinessDay": day.weekday() < 5 and not holiday,
                     "holidayNames": ["authored closure"] if holiday else [], "sourceIds": ["fixture"]})
    raw = json.dumps({"schemaVersion": 1, "timezone": "Asia/Seoul", "calendarKind": "KR_CIVIL_WEEKDAY_PUBLIC_HOLIDAYS",
        "coverage": {"startDate": str(start), "endDate": str(end - timedelta(days=1)), "lookaheadEndDate": str(end)},
        "evidenceCutoff": "2026-10-16", "dates": rows, "operationalApproval": False,
        "sources": [{"id": "fixture", "url": "https://example.invalid/authored", "sha256": "a" * 64, "retrievedAt": "2026-10-16"}]})
    return {"kind": "through-next-business-day-close-1", "calendarJson": raw,
            "calendarSha256": hashlib.sha256(raw.encode()).hexdigest(), "inventoryMaxAgeSeconds": bound}


@pytest.mark.parametrize("closed,next_day,bound", [("2026-10-18", "2026-10-19", 291600),
    ("2026-10-19", "2026-10-20", 378000), ("2026-11-01", "2026-11-02", 1501200)])
def test_friday_origin_stays_eligible_through_next_business_close(closed, next_day, bound):
    value = policy(close_through=closed, bound=bound)
    calendar = CalendarEligibility.model_validate(value).calendar()
    assert calendar.required_bound == bound
    assert calendar.eligible("2026-10-16T09:05:00+09:00", next_day + "T18:05:00+09:00")
    assert not calendar.eligible("2026-10-16T09:05:00+09:00", next_day + "T18:05:01+09:00")
    with pytest.raises(IngestionFailure, match="calendar_inventory_bound_insufficient"):
        CalendarEligibility.model_validate({**value, "inventoryMaxAgeSeconds": bound - 1}).calendar()


def test_long_closure_crosses_year_without_elapsed_cap():
    calendar = CalendarEligibility.model_validate(policy(start_day="2026-12-23", end_day="2027-01-12",
        close_through="2027-01-04", bound=1155600)).calendar()
    assert calendar.required_bound == 1155600
    assert calendar.eligible("2026-12-23T09:05:00+09:00", "2027-01-05T18:05:00+09:00")


def test_calendar_unknown_digest_and_horizon_fail_closed():
    value = policy()
    with pytest.raises(IngestionFailure, match="calendar_digest_mismatch"):
        CalendarEligibility.model_validate({**value, "calendarSha256": "b" * 64}).calendar()
    calendar = CalendarEligibility.model_validate(value).calendar()
    with pytest.raises(IngestionFailure, match="calendar_horizon_unavailable"):
        calendar.eligible("2026-10-16T09:05:00+09:00", "2026-11-05T09:05:00+09:00")
    doc = json.loads(value["calendarJson"])
    doc["dates"].pop(2)
    raw = json.dumps(doc)
    with pytest.raises(IngestionFailure, match="calendar_invalid"):
        CalendarEligibility.model_validate({**value, "calendarJson": raw,
            "calendarSha256": hashlib.sha256(raw.encode()).hexdigest()}).calendar()


def test_native_inventory_paging_and_cli_planner_share_original_calendar_deadline(world, tmp_path):
    kit = world.kit
    origin = "2026-10-16T09:05:00+09:00"
    rid, _ = ingest_simple_round(kit, "friday", ["one", "two"], slot=origin)
    value = policy(close_through="2026-11-01", bound=1501200)
    request = {"schemaVersion": "zoop-ingestion-round-inventory-2", "sourceId": "synthetic-source", "scopeId": "body",
               "asOf": "2026-11-02T17:35:00+09:00", "maxAgeSeconds": 1501200, "eligibility": value, "limit": 1}
    before = tree(kit.root / "ingestion")
    first = inventory(parse_inventory(request), kit.root / "ingestion", Authority(kit.registry_path))
    assert first["observations"][0]["slot"] == origin
    second_request = {**request, "after": first["next"], "checkpointRevision": first["checkpoint"]["revision"]}
    second = inventory(parse_inventory(second_request), kit.root / "ingestion", Authority(kit.registry_path))
    assert second["next"] is None
    with pytest.raises(IngestionFailure, match="calendar_cursor_binding_mismatch"):
        inventory(parse_inventory({**second_request, "asOf": "2026-11-02T17:36:00+09:00"}), kit.root / "ingestion", Authority(kit.registry_path))
    selected = parse_selection({"schemaVersion": "zoop-extraction-round-selection-3", "asOf": request["asOf"],
        "eligibility": value, "observations": [row["observation"] for page in (first, second) for row in page["observations"]]})
    out = tmp_path / "calendar-plan"
    code, receipt = cli_plan(world, out, rid, selected)
    assert code == 0, receipt
    manifest = json.loads((out / "manifest.json").read_bytes())
    assert manifest["counts"]["units"] == 2
    assert [row["slot"] for row in manifest["selectionReport"]] == [origin, origin]
    verified = verify_plan(out, sha((out / "receipt.json").read_bytes()), Fixtures(world.replay.read_bytes(), None),
                           kit.root / "ingestion", kit.registry_path)
    assert verified["planId"] == receipt["planId"]
    assert cli_plan(world, out, rid, selected) == (0, {**receipt, "outcome": "existing"})
    expired = parse_selection({**selected.wire(), "asOf": "2026-11-02T18:05:01+09:00"})
    code, refused = cli_plan(world, tmp_path / "expired", rid, expired)
    assert code == 2 and refused["error"]["code"] == "plan_has_no_units"
    assert {row["code"] for row in refused["error"]["detail"]["selectionReport"]} == {"automatic_window_expired"}
    aged = {**request, "asOf": "2026-11-02T18:05:01+09:00"}
    assert inventory(parse_inventory(aged), kit.root / "ingestion", Authority(kit.registry_path))["observations"] == []
    assert tree(kit.root / "ingestion") == before


def test_explicit_elapsed_mode_has_distinct_plan_jobs_and_unchanged_elapsed_expiry(world, tmp_path):
    rid, _ = ingest_simple_round(world.kit, "elapsed-mode", ["one"], slot="2026-10-16T09:05:00+09:00")
    from tests.test_round_enqueue import candidates, observation
    refs = [observation(rid, candidates(world.kit, rid)[0])]
    old = {"schemaVersion": "zoop-extraction-round-selection-2", "asOf": "2026-10-16T09:35:00+09:00",
           "maxAgeSeconds": 1800, "observations": refs}
    explicit = {"schemaVersion": "zoop-extraction-round-selection-3", "asOf": old["asOf"], "observations": refs,
                "eligibility": {"kind": "elapsed-age-1", "maxAgeSeconds": 1800}}
    plans = []
    for index, value in enumerate((old, explicit)):
        out = tmp_path / str(index)
        code, receipt = cli_plan(world, out, rid, parse_selection(value))
        assert code == 0, receipt
        plans.append(json.loads((out / "manifest.json").read_bytes()))
    assert plans[0]["planId"] != plans[1]["planId"]
    assert plans[0]["units"][0]["jobId"] != plans[1]["units"][0]["jobId"]
    expired = parse_selection({**explicit, "asOf": "2026-10-16T09:35:01+09:00"})
    code, refused = cli_plan(world, tmp_path / "expired-elapsed", rid, expired)
    assert code == 2 and refused["error"]["detail"]["selectionReport"][0]["code"] == "too_old"
