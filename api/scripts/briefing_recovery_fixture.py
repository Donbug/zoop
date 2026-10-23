#!/usr/bin/env python3
"""Authored recovery recordings for PostgreSQL/HTTP tests; no credentials or network."""
import contextlib
from datetime import timedelta
import importlib.util
import io
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import briefing_grouped_recovery_run as recovery_run


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create(directory, editorial=False):
    fixture_module = load("recovery_pg_fixture", ROOT / "scripts/tests/test_briefing_grouped_run.py")
    item_fixture = load("recovery_pg_transport", ROOT / "scripts/tests/test_briefing_item_recovery.py")
    base = recovery_run.base
    fixture = fixture_module.GroupedRunTest()
    fixture.setUp()
    try:
        directory = directory.resolve(); base.private_dir(directory)
        fixture.root = directory; fixture.archive_path = directory / "archive.json"; fixture.output = directory / "base"
        fixture.clock.root = directory; fixture.clock.sources = directory / "sources.jsonl"
        fixture.clock.clocks = directory / "clocks.json"; fixture.clock.html = directory / "html"; fixture.clock.html.mkdir()
        rows = []
        for index, spec in enumerate(fixture_module.run.sim.windows()):
            stamp = (fixture_module.run.sim.aware(spec["window"]["to"]) - timedelta(minutes=10)).isoformat()
            for offset in range(3 if index == 0 else 1):
                number = len(rows)
                quote = f"합성 기업이 건물 관리 기술 {number}번 적용 계약을 체결했습니다. 실제 뉴스가 아닌 시험 문장입니다."
                document = fixture_module.fixtures.document("recovery-doc-" + str(number), stamp, quote)
                rows.append({**document, "authoredPublishedAt": stamp, "allowModelSend": False,
                             "rightsStatus": "unconfirmed", "sourceKind": "news"})
        fixture.clock.prepare(rows, [])
        documents, _, source = fixture_module.run.sim.load_inputs(fixture.clock.sources, fixture.clock.clocks)
        archive = fixture_module.fixtures.archive(*[("recovery-issue-" + str(i), [(doc,
            fixture_module.fixtures.mention(doc, "recovery-mention-" + str(i)))]) for i, doc in enumerate(documents)])
        # Two exact spans from one document are valid within one issue; only cross-issue reuse is forbidden.
        mention = archive["issues"][2]["mentions"][0]; quote = "작성한 합성 원문입니다."
        mention["evidence"].append({"evidenceId": "ev-recovery-second-span", "articleId": mention["articleId"],
            "articleVersion": mention["articleVersion"], "quote": quote, "start": 0, "end": len(quote)})
        archive["documents"] = [{k: v for k, v in doc.items() if k != "clockTime"} for doc in archive["documents"]]
        archive.update(sourceFileSha256=source["sourceFileSha256"], clockFileSha256=source["clockFileSha256"])
        fixture_module.fixtures.record_grounding(archive, directory)
        fixture.archive_path.write_bytes(base.canonical(archive))

        class BaseTransport(fixture_module.fixtures.AuthoredTransport):
            def __call__(self, raw):
                status, response = super().__call__(raw)
                request = base.strict_load(raw); data = base.strict_load(request["input"])
                if request["text"]["format"]["name"].endswith("_generation") and data["context"]["date"] == "2026-10-02" and data["edition"] == "morning":
                    value = base.strict_load(response); part = value["output"][0]["content"][0]; answer = base.strict_load(part["text"])
                    for key, item in answer["items"].items():
                        item["claims"] = [] if key == "recovery-issue-0" else item["claims"][:1]
                    part["text"] = base.canonical(answer).decode(); response = base.canonical(value)
                return status, response

        fixture.execute(BaseTransport())

        class RecoveryTransport(item_fixture.AuthoredTransport):
            def __call__(self, raw):
                status, response = super().__call__(raw)
                request = base.strict_load(raw); data = base.strict_load(request["input"])
                if request["text"]["format"]["name"].endswith("_generation"):
                    value = base.strict_load(response); part = value["output"][0]["content"][0]; answer = base.strict_load(part["text"])
                    for draft in answer["items"].values():
                        draft["claims"][0]["text"] = draft["claims"][0]["text"].split(".")[0] + "."
                    part["text"] = base.canonical(answer).decode(); response = base.canonical(value)
                if request["text"]["format"]["name"].endswith("_novelty"):
                    value = base.strict_load(response); part = value["output"][0]["content"][0]; answer = base.strict_load(part["text"])
                    for key, decision in answer["decisions"].items():
                        decision.update(decision="REPEAT" if key == "recovery-issue-3" else "NEW", deltaEvidenceIds=[])
                    part["text"] = base.canonical(answer).decode(); response = base.canonical(value)
                return status, response

        transport = RecoveryTransport(verification_mutations={"recovery-issue-1:claim:0": {"verdict": "UNSUPPORTED"}})
        output = directory / "output"
        args = recovery_run.parser().parse_args(["--base-bundle", str(fixture.output / "bundle-v2.json"), "--output", str(output),
            "--user-inbox-ref", "inbox/authored-recovery.md", "--max-repairs", "0", "--workers", "1", "--execute-authorized"])
        if editorial:
            original = base.strict_load((fixture.output / "bundle-v2.json").read_bytes())["rounds"][-1]
            hold = {"roundId": original["roundId"], "issueId": "recovery-issue-15", "code": "editorial_test_no_material_delta",
                    "reason": "Authored conservative hold; it cannot authorize a publication.",
                    "evidenceIds": [original["selected"][0]["sources"][0]["evidenceId"]]}
            path = directory / "authored-editorial.json"
            path.write_bytes(base.canonical({"userInboxRef": "inbox/authored-recovery.md", "holds": [hold]}))
            args.review_holds = str(path)
        with contextlib.redirect_stdout(io.StringIO()): proof = recovery_run.run(args, transport)
        assert proof["publishedRounds"] == (12 if editorial else 13) and proof["publishedItems"] == (13 if editorial else 14) and proof["partialRounds"] == 1, proof
        return {"sources": str(fixture.clock.sources), "clocks": str(fixture.clock.clocks), "bundle": str(output / "bundle-v2.json"),
                "newAuthoredCalls": len(transport.requests), "realPaidCalls": 0}
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    print(create(Path(sys.argv[1]), "--editorial" in sys.argv))
