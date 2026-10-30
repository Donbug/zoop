#!/usr/bin/env python3
"""Authors the re-analysis fixture of the Spring review-target tests with the REAL plan builder, the REAL S2 pipeline and the REAL service
wire model (#132, PR #395).

One authored document goes through the actual ingestion CLI as one complete round. `plan_round` then plans that round twice, under two
enqueue ids: two plans of the same observation, which is what an operator's re-analysis is. Each plan's approved S2 request is run by the
actual extraction pipeline on an authored replay recording, and its result is rendered by `zoop_ai_service.extraction_wire
.ExtractionJobContent`, the projection the AI service answers the application with. Nothing here is derived from the Java code under test.

The two units differ in their S2 job id and input digest (both derive from the plan, so from the enqueue id) and name the same analysed
document on every event candidate. The Java test reads exactly that.

Run it from the repository root with the ai/pipeline interpreter and the service sources on the path:

  PYTHONPATH=ai/service/src ai/pipeline/.venv/bin/python api/scripts/export_reanalysis_fixtures.py

The output is committed: api/src/test/resources/review/reanalysis-two-plans.json. Regenerate it only when the plan or S2 result contract
changes, and re-run the Java tests afterwards.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "ai" / "pipeline"
sys.path[:0] = [str(PIPELINE)]

from scripts.extraction_smoke import CATALOGUE, PROMPT, Q3, Kit, page  # noqa: E402
from zoop_ai_pipeline.extraction import Fixtures  # noqa: E402
from zoop_ai_pipeline.extraction_contracts import SCHEMA, EnqueueRound  # noqa: E402
from zoop_ai_pipeline.extraction_plan import plan_round  # noqa: E402
from zoop_ai_service.extraction_wire import ExtractionJobContent  # noqa: E402

OUTPUT = ROOT / "api" / "src" / "test" / "resources" / "review" / "reanalysis-two-plans.json"
SOURCE = "synthetic-source"
PRINCIPAL = "alpha"
ENQUEUE_IDS = ("reanalysis-1", "reanalysis-2")


def descriptor(round_id: str, enqueue_id: str) -> dict:
    return {"schemaVersion": SCHEMA, "enqueueId": enqueue_id, "roundId": round_id, "sourceId": SOURCE,
            "provenance": {"sourceKind": "synthetic", "executionMode": "replay", "recordingKind": "authored-test"},
            "promptVersion": PROMPT, "catalogue": CATALOGUE, "snapshot": {"revision": "snapshot-1", "events": []}, "topic": None}


def main() -> None:
    with tempfile.TemporaryDirectory() as work:
        kit = Kit(Path(work) / "owned")
        (ref,) = kit.ingest("reanalysis", [{"supplier": "supplier-r", "html": page(Q3, "계약 상대는 합성상대다.")}])
        article = kit.article(ref)
        replay = kit.replay("reanalysis-s2").extract(article, [kit.mention(article, "m-1", [kit.evidence(article, Q3)])]).write()

        plans = []
        for enqueue_id in ENQUEUE_IDS:
            out = Path(work) / enqueue_id
            plan_round(EnqueueRound.model_validate(descriptor(ref["roundId"], enqueue_id)), Fixtures(replay.read_bytes(), None),
                       PRINCIPAL, kit.root / "ingestion", kit.registry_path, out)
            (unit,) = json.loads((out / "manifest.json").read_bytes())["units"]
            (approval,) = json.loads((out / "approvals.json").read_bytes())["approvals"]
            kit.job("run", approval["request"], replay=replay)
            raw = kit.job("result", {"schemaVersion": SCHEMA, "jobId": unit["jobId"]})
            content = ExtractionJobContent.model_validate(raw)
            plans.append({"enqueueId": enqueue_id, "s2JobId": unit["jobId"], "s2InputDigest": unit["inputDigest"],
                          "s2Result": content.model_dump(by_alias=True, mode="json")})

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({"recordingKind": "authored-test", "document": {"documentId": ref["documentId"],
                                                                                    "documentVersion": ref["documentVersion"]},
                                  "plans": plans}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
