"""Authored finite calendars exercise Friday carry through real service/native boundaries."""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import date, timedelta

from online_admission_support import check
from relation_support import canonical


def calendar_inputs(case):
    next_day, bound = {"weekend": ("2026-10-19", 291600), "monday_holiday": ("2026-10-20", 378000),
                       "long_closure": ("2026-11-02", 1501200)}[case]
    return {"case": case, "nextDay": next_day, "nextSlot": next_day + "T17:35:00+09:00", "bound": bound,
            "holidayDay": "2026-10-17" if case == "weekend" else "2026-10-19"}


def configure_calendar(root, profile, inputs):
    start, reopen = date(2026, 10, 16), date.fromisoformat(inputs["nextDay"])
    end = reopen + timedelta(days=3)
    rows = []
    for n in range((end - start).days + 1):
        day = start + timedelta(days=n)
        closed = start < day < reopen and day.weekday() < 5
        rows.append({"date": day.isoformat(), "isBusinessDay": day.weekday() < 5 and not closed,
                     "holidayNames": ["Authored synthetic closure"] if closed else [], "sourceIds": ["authored"]})
    artifact = {"schemaVersion": 1, "timezone": "Asia/Seoul", "calendarKind": "KR_CIVIL_WEEKDAY_PUBLIC_HOLIDAYS",
                "coverage": {"startDate": start.isoformat(), "endDate": (end - timedelta(days=1)).isoformat(),
                             "lookaheadEndDate": end.isoformat()}, "evidenceCutoff": "2026-10-16", "dates": rows,
                "sources": [{"id": "authored", "url": "https://example.invalid/authored-calendar",
                             "sha256": hashlib.sha256(b"authored calendar fixture").hexdigest(), "retrievedAt": "2026-10-16"}],
                "operationalApproval": False}
    path = root / "calendar.json"
    path.write_text(canonical(artifact))
    doc = json.loads(profile.read_bytes())
    doc.update(schemaVersion="zoop-ai-round-profile-2", initialFrom="2026-10-16T00:00:00+09:00",
               selection={"limit": 8, "cadenceMinutes": 30, "eligibility": {
                   "kind": "through-next-business-day-close-1", "calendar": {"path": str(path),
                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}, "inventoryMaxAgeSeconds": inputs["bound"]}})
    profile.write_text(canonical(doc))
    (root / "clock").write_text(inputs["holidayDay"] + "T18:05:00+09:00")


def exercise_calendar(root, workspace, info, plans, service, start, wait_status, inputs):
    holiday = "round-" + inputs["holidayDay"].replace("-", "") + "T0905"
    request = {"schemaVersion": "zoop-ai-round-run-1", "roundId": holiday}
    check(service.request("POST", "/internal/v1/round-runs", body=request, key=holiday).status_code == 202, "holiday not reserved")
    result = wait_status("runs", holiday, {"no_new_material", "failed"}).json()
    check((result["state"], result["code"]) == ("no_new_material", "non_business_day"), canonical(result))
    check((root / "ingestion-commands").read_text().splitlines() == ["round-calendar"], "holiday dispatched ingestion")
    check(not (root / "s2-commands").exists(), "holiday dispatched planning")
    freeze_id = holiday[:-4] + "1805"
    freeze = {"schemaVersion": "zoop-ai-round-handoff-1", "roundId": freeze_id, "bindings": info["bindings"]}
    check(service.request("POST", "/internal/v1/round-handoffs", body=freeze, key=freeze_id).status_code == 202, "holiday freeze refused")
    frozen = wait_status("handoffs", freeze_id, {"no_public_material", "failed"}).json()
    check(frozen["state"] == "no_public_material" and frozen["code"] == "window_empty", canonical(frozen))
    check((root / "handoff-commands").read_text().splitlines().count("freeze-round") == 1, "planless freeze not executed once")
    service.close()
    # Replay precedes both future-slot and calendar clock checks, including after a restart.
    (root / "clock").write_text("2026-10-16T09:05:00+09:00")
    service = start()
    replay = service.request("POST", "/internal/v1/round-runs", body=request, key=holiday)
    check(replay.status_code == 200 and replay.json()["code"] == "non_business_day", "restart replay rechecked clock")
    check((root / "ingestion-commands").read_text().splitlines() == ["round-calendar"], "restart replay reran native calendar")
    (root / "clock").write_text(inputs["nextSlot"])
    shutil.copyfile(info["emptyManifest"], info["fixtureManifest"])
    next_id = "round-" + inputs["nextDay"].replace("-", "") + "T1735"
    next_body = {"schemaVersion": "zoop-ai-round-run-1", "roundId": next_id}
    check(service.request("POST", "/internal/v1/round-runs", body=next_body, key=next_id).status_code == 202, "carry round refused")
    from support import wait_for
    def settled(round_id=next_id):
        response = service.request("GET", "/internal/v1/round-runs/" + round_id)
        check(response.status_code == 200, response.text)
        value = response.json()
        return value if value["state"] != "running" else None
    ready = wait_for(settled, timeout=90)
    check(ready["state"] == "ready", canonical(ready))
    manifest = json.loads((plans / ready["planId"] / "manifest.json").read_bytes())
    check(manifest["selection"]["schemaVersion"] == "zoop-extraction-round-selection-3", "calendar selection version lost")
    check(manifest["selectionReport"][0]["slot"] == "2026-10-16T09:05:00+09:00", "carry origin refreshed")
    check(manifest["selection"]["observations"] == [info["s2Request"]["incoming"]], "Friday ref not retained")
    check(ready["ingestionRoundId"] != info["s2Request"]["incoming"]["roundId"], "later round identity replaced origin")
    before = (root / "ingestion-commands").read_text()
    service.close()
    (root / "clock").write_text("2026-10-16T09:05:00+09:00")
    service = start()
    replay = service.request("POST", "/internal/v1/round-runs", body=next_body, key=next_id)
    check(replay.status_code == 200 and replay.json()["planId"] == ready["planId"], "ready replay changed plan")
    check((root / "ingestion-commands").read_text() == before, "ready replay repeated ingestion")
    (root / "clock").write_text("2027-01-04T09:05:00+09:00")
    unknown_id = "round-20270104T0905"
    unknown_body = {"schemaVersion": "zoop-ai-round-run-1", "roundId": unknown_id}
    check(service.request("POST", "/internal/v1/round-runs", body=unknown_body, key=unknown_id).status_code == 202, "unknown horizon not journaled")
    unknown = wait_for(lambda: settled(unknown_id), timeout=60)
    check((unknown["state"], unknown["code"]) == ("failed", "calendar_horizon_unavailable"), canonical(unknown))
    check((root / "ingestion-commands").read_text() == before + "round-calendar\n", "unknown horizon dispatched tick")
    with sqlite3.connect((workspace.state / "rounds" / "rounds.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        check(db.execute("SELECT count(*) FROM observation_claims").fetchone()[0] == 1, "restart dropped permanent claim")
    check(not (root / "network-attempt").exists(), "native network attempted")
    report = {"state": "passed", "case": inputs["case"], "inventoryMaxAgeSeconds": inputs["bound"],
              "originalSlot": "2026-10-16T09:05:00+09:00", "serviceAsOf": inputs["nextSlot"], "planId": ready["planId"],
              "holiday": result, "freeze": frozen, "providerCalls": 0, "networkAttempts": 0}
    (root / "report.json").write_text(canonical(report) + "\n")
    return report
