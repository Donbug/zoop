#!/usr/bin/env python3
"""Worker-side bridge of the offline Korean-finance semantic-verification benchmark (`ai/evaluation`, family zoop-verify-run-1).

It turns the system-visible `cases.json` into verification-only jobs, runs them through the ACTUAL installed `zoop-ai` CLI against a
loopback fake native-Jev server, and exports what the worker recorded (normalized artifact, usage, duration and the raw receipt)
as a `zoop-verify-run-1` file for `python -m zoop_eval verify-score`.

Boundaries:

  * The bridge never opens the gold. It reads `cases.json` (the visible inputs) and the loopback script; the gold is
    opened only by the evaluation commands (validate, controls, score).
  * The fake server's answers come from an authored script: a visible control, not a model. The exported run is therefore always
    `authored_control` / `loopback_fake_native_server`; a real provider export is deliberately not implemented here (it needs an
    approved live run, a key and a budget) and the provenance label of a job is never trusted.
  * No real key, endpoint, account or model is involved: the child environment is built from nothing and every endpoint is loopback.

    ai/worker/.venv/bin/python ai/worker/scripts/verification_bench.py build-jobs --out-dir /tmp/zoop-vk-jobs
    ai/worker/.venv/bin/python ai/worker/scripts/verification_bench.py run --out /tmp/zoop-vk.run.json
    ai/worker/.venv/bin/python ai/worker/scripts/verification_bench.py export --state-dir S --out run.json
    ai/worker/.venv/bin/python ai/worker/scripts/verification_bench.py smoke

After a worker source change, rebuild the installed copy first (the CLI runs the installed package, not the source):
`make worker-install`.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import json
import secrets
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

WORKER = Path(__file__).resolve().parents[1]
EVALUATION = WORKER.parent / "evaluation"
sys.path.insert(0, str(WORKER / "tests"))
sys.path.insert(0, str(EVALUATION))

from fake_providers import FakeServer, fixture  # noqa: E402
from zoop_ai import native_jev  # noqa: E402
from zoop_ai.contracts import SCHEMA_VERSION, Submit, SummaryAnswer, digest, exact  # noqa: E402
from zoop_ai.provider import native_revision  # noqa: E402
from zoop_eval.contracts import SCHEMA_VERIFY_RUN, Rejected, read_json  # noqa: E402
from zoop_eval.verification import (  # noqa: E402
    GATES, NATIVE_INVALID, VerifyInputs, case_sha256, load_inputs, parse_loopback_script, scenario_response,
)

CLI = WORKER / ".venv" / "bin" / "zoop-ai"
VERIFY = "semantic-verification"
DEFAULT_CASES = EVALUATION / "corpus" / "fin-verify-ko-v1" / "cases.json"
DEFAULT_SCRIPT = EVALUATION / "fixtures" / "verification" / "controls" / "loopback-script.json"
GRANT_ID, GRANT_REVISION = "grant-synthetic-s1", "grant-synthetic-s1-1"
RAW_LOCATOR = "raw-1"
RECORDER = "ai/worker/scripts/verification_bench.py"


class BridgeError(Exception):
    pass


def job_id(case_id: str) -> str:
    return "verify-" + case_id


def build_job(case: dict[str, Any]) -> dict[str, Any]:
    """One verification-only Submit for a visible case. Validated with the worker's own models and `exact()` before it is returned."""
    body = case["document"]["text"]
    source_hash = digest(body)
    document = {"documentId": case["document"]["documentId"], "documentVersion": source_hash, "sourceId": "authored-synthetic",
                "textArtifactId": f"text-{case['document']['documentId']}-{source_hash[:16]}", "inputKind": "body",
                "cleanerVersion": "authored-nfc-1", "text": body, "sourceHash": source_hash,
                "rawLocators": [{"locatorId": RAW_LOCATOR, "start": 0, "end": len(body)}]}
    claims = case["candidate"]["claims"]
    candidate = {
        "text": "\n".join(c["text"] for c in claims if c["assertionKind"] != "limitation"),
        "claims": [dict(c) for c in claims],
        "citations": [{"evidenceId": r["evidenceId"], "documentId": document["documentId"], "documentVersion": source_hash,
                       "textArtifactId": document["textArtifactId"], "offsetUnit": "unicode_code_point", "start": r["start"],
                       "end": r["end"], "quote": r["quote"], "inputKind": "body", "rawLocatorIds": [RAW_LOCATOR]}
                      for r in case["candidate"]["citations"]],
        "limitations": [c["text"] for c in claims if c["assertionKind"] == "limitation"],
    }
    submit = {"schemaVersion": SCHEMA_VERSION, "jobId": job_id(case["caseId"]), "kind": VERIFY,
              "input": {"document": document, "company": dict(case["company"]), "grantId": GRANT_ID, "grantRevision": GRANT_REVISION,
                        "candidate": candidate},
              "mode": "live", "provenance": {"sourceKind": "synthetic", "executionMode": "live", "recordingKind": "provider"}}
    model = Submit.model_validate(submit)
    exact(SummaryAnswer.model_validate(candidate), model.input.document)
    return submit


def build_jobs(inputs: VerifyInputs) -> dict[str, dict[str, Any]]:
    return {case_id: build_job(case) for case_id, case in inputs.cases.items()}


def _request_key(document_text: str, company: str, claim_texts: list[str]) -> str:
    return json.dumps([document_text, company, claim_texts], ensure_ascii=False)


class Loopback:
    """The fake native server: looks an incoming request up by its visible content and answers from the authored script."""

    def __init__(self, inputs: VerifyInputs, script: dict[str, dict[str, Any]]):
        self.by_request = {_request_key(c["document"]["text"], c["company"]["name"], [x["text"] for x in c["candidate"]["claims"]]): case_id
                           for case_id, c in inputs.cases.items()}
        if len(self.by_request) != len(inputs.cases):
            raise BridgeError("two cases are indistinguishable to the fake server")
        self.inputs, self.script = inputs, script
        self.matched: list[str | None] = []
        self.server = FakeServer(self._respond)

    def _respond(self, request: dict[str, Any]) -> tuple[int, Any]:
        state = request["body"].get("state", {})
        claims = state.get("candidate", {}).get("claims", [])
        case_id = self.by_request.get(_request_key(state.get("document", {}).get("text", ""), state.get("company", {}).get("name", ""),
                                                   [c["text"] for c in claims]))
        self.matched.append(case_id)
        if case_id is None or request["path"] != "/v1/systemone":
            return 404, {"error": "unscripted request"}
        return scenario_response(self.script[case_id], len(claims), native_jev.MODEL)

    @property
    def base(self) -> str:
        return self.server.base

    @property
    def requests(self) -> list[dict[str, Any]]:
        return self.server.requests

    def close(self) -> None:
        self.server.close()


def child_env(base_url: str, key: str, cases: int, home: Path) -> dict[str, str]:
    # Built from nothing: no inherited variable can carry a real key, endpoint, proxy or model.
    return {"PATH": "/usr/bin:/bin", "HOME": str(home), "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
            "ZOOP_AI_LIVE_ENABLED": "1", "ZOOP_AI_GLOBAL_MAX_CALLS": str(cases), "ZOOP_AI_VERIFY_PROVIDER": "typesafe-native",
            "TYPESAFE_VALIDATION_MODEL": native_jev.MODEL, "TYPESAFE_BASE_URL": base_url, "TYPESAFE_API_KEY": key}


def cli(command: str, data: dict[str, Any], state: Path, env: dict[str, str], grants: Path | None = None) -> tuple[int, dict[str, Any]]:
    argv = [str(CLI), command, "--state-dir", str(state)] + (["--grants", str(grants)] if grants else [])
    done = subprocess.run(argv, input=json.dumps(data, ensure_ascii=False), env=env, capture_output=True, text=True, timeout=120)
    try:
        return done.returncode, json.loads(done.stdout)
    except json.JSONDecodeError:
        raise BridgeError(f"zoop-ai {command} produced no JSON (exit {done.returncode}): {done.stderr.strip()[:300]}") from None


def _receipt(state: Path, job: str) -> dict[str, Any] | None:
    db = sqlite3.connect(f"file:{state / 'worker.sqlite3'}?mode=ro&immutable=1", uri=True)
    try:
        row = db.execute("SELECT receipt FROM calls WHERE job_id=? AND stage=?", (job, VERIFY)).fetchone()
    finally:
        db.close()
    return json.loads(row[0]) if row and row[0] else None


def _record(inputs: VerifyInputs, case_id: str, result: dict[str, Any], raw: dict[str, Any] | None) -> dict[str, Any]:
    base = {"caseId": case_id, "caseSha256": case_sha256(inputs.cases[case_id]), "claimBinding": inputs.binding(case_id)}
    calls = [c for c in result["calls"] if c["stage"] == VERIFY]
    call = None
    if raw is not None:
        if len(calls) != 1:
            raise BridgeError(f"{case_id}: a receipt exists but the job has {len(calls)} verification calls")
        c = calls[0]
        call = {"attemptId": c["attemptId"], "model": c["config"]["model"], "providerRevision": c["config"]["providerRevision"],
                "promptVersion": c["config"]["promptVersion"], "policyVersion": c["config"]["policyVersion"],
                "usage": {"inputTokens": (c["usage"] or {}).get("inputTokens"), "outputTokens": (c["usage"] or {}).get("outputTokens")},
                # A loopback fake server charges nothing; this is a statement about the fake, never about Jev pricing.
                "cost": {"usd": 0, "source": "loopback_no_charge"}}
    if result["state"] == "ready":
        artifact = next((a for a in result["artifacts"] if a["kind"] == VERIFY), None)
        if artifact is None or raw is None or call is None:
            raise BridgeError(f"{case_id}: a ready job without its verification artifact or receipt")
        verdicts = artifact["result"]["claims"]
        if [v["claimId"] for v in verdicts] != inputs.claim_ids(case_id) or artifact["validation"]["semantic"] not in GATES:
            raise BridgeError(f"{case_id}: the artifact does not bind to the case's claims in order")
        return {**base, "status": "ok",
                "result": {"gate": artifact["validation"]["semantic"], "claims": [{"claimId": v["claimId"], "decision": v["decision"]} for v in verdicts],
                           "prohibitedAdvice": artifact["result"]["prohibitedAdvice"], "unsupportedCausality": artifact["result"]["unsupportedCausality"]},
                "raw": raw, "call": call, "latencyMs": calls[0]["durationMs"]}
    if result["state"] == "reconciling":
        return {**base, "status": "error", "error": {"code": "provider_response_unknown", "outcome": "unknown"}}
    failure = (result.get("failure") or {}).get("code")
    if result["state"] != "failed" or not failure:
        raise BridgeError(f"{case_id}: job ended in state {result['state']!r} without a failure code")
    if failure in NATIVE_INVALID:
        if raw is None or call is None:
            raise BridgeError(f"{case_id}: {failure} without a kept receipt")
        return {**base, "status": "error", "error": {"code": failure, "outcome": "definite"}, "raw": raw, "call": call,
                "latencyMs": calls[0]["durationMs"]}
    return {**base, "status": "error", "error": {"code": failure, "outcome": "definite"}}


def export_run(inputs: VerifyInputs, state: Path, env: dict[str, str], *, run_id: str, endpoint_kind: str = "loopback_fake") -> dict[str, Any]:
    if endpoint_kind != "loopback_fake":
        raise BridgeError("only loopback_fake export is implemented: a real provider run needs an approved live run, key and budget")
    records, configs = [], []
    for case_id in inputs.cases:
        code, result = cli("get", {"schemaVersion": SCHEMA_VERSION, "jobId": job_id(case_id)}, state, env)
        if code != 0:
            raise BridgeError(f"{case_id}: get failed: {result}")
        records.append(_record(inputs, case_id, result, _receipt(state, job_id(case_id))))
        configs += [c["config"] for c in result["calls"] if c["stage"] == VERIFY]
    if not configs:
        raise BridgeError("no verification call was recorded, so the run cannot name its model and policy")
    first = configs[0]
    if any(c != first for c in configs):
        raise BridgeError("the ledger holds more than one verification configuration; one model/policy/prompt version per run")
    system = {"name": "zoop-ai-native-jev-verify", "adapter": "typesafe-native", "endpointKind": endpoint_kind, "model": first["model"],
              "providerRevision": first["providerRevision"], "promptVersion": first["promptVersion"], "policyVersion": first["policyVersion"],
              "adapterIdentity": native_jev.identity(), "policy": policy()}
    return {"schema": SCHEMA_VERIFY_RUN, "runId": run_id, "label": "loopback fake native server (authored control)",
            "provenance": {"kind": "authored_control", "executionMode": "authored", "recorder": RECORDER, "recordedAt": None,
                           "controlKind": "loopback_fake_native_server",
                           "note": "real zoop-ai CLI and native request path against a local fake server answering from an authored script; not a model"},
            "corpus": {"corpusId": inputs.corpus_id, "corpusRevision": inputs.revision, "inputsSha256": inputs.inputs_sha256, "split": inputs.split},
            "system": system, "records": records}


def policy() -> dict[str, float]:
    return {"choiceProbability": native_jev.CHOICE_PROBABILITY, "choiceConfidence": native_jev.CHOICE_CONFIDENCE, "noulTrue": native_jev.NOUL_TRUE,
            "noulFalse": native_jev.NOUL_FALSE, "distributionTolerance": native_jev.DISTRIBUTION_TOLERANCE}


def run_loopback(inputs: VerifyInputs, script: dict[str, dict[str, Any]], work: Path, *, run_id: str) -> tuple[dict[str, Any], Loopback, str]:
    """Submit and run every case through the installed CLI; return (run document, the server with its request log, the key used)."""
    if not CLI.exists():
        raise BridgeError(f"installed CLI missing: {CLI} (run `make worker-install`)")
    server = Loopback(inputs, script)
    key = "loopback-" + secrets.token_hex(8)
    state, grants = work / "ledger", work / "grants.json"
    try:
        grant = {**fixture("grants")["grants"][0], "recipients": ["typesafe-native:" + native_revision(server.base)],
                 "purposes": [VERIFY]}
        grants.write_text(json.dumps({"schemaVersion": SCHEMA_VERSION, "grants": [grant]}))
        env = child_env(server.base, key, len(inputs.cases), work)
        for case_id, job in build_jobs(inputs).items():
            code, _ = cli("submit", job, state, env, grants)
            if code != 0:
                raise BridgeError(f"{case_id}: submit refused")
            cli("run", {"schemaVersion": SCHEMA_VERSION, "jobId": job["jobId"]}, state, env, grants)
        return export_run(inputs, state, env, run_id=run_id), server, key
    except BaseException:
        server.close()
        raise


def _write(path: Path, document: dict[str, Any]) -> None:
    path.write_text(json.dumps(document, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def _script(path: Path, inputs: VerifyInputs) -> dict[str, dict[str, Any]]:
    return parse_loopback_script(read_json(path), inputs)


# --------------------------------------------------------------------------------------------------------------- smoke

FAILURES: list[str] = []


def check(ok: bool, message: str) -> None:
    print(("  ok   " if ok else "  FAIL ") + message)
    if not ok:
        FAILURES.append(message)


_GOLD_WATCH: dict[str, Any] = {"installed": False, "active": 0, "opened": []}


def _gold_audit(event: str, args: tuple) -> None:
    if _GOLD_WATCH["active"] and event == "open" and args and Path(str(args[0])).name == "gold.json":
        _GOLD_WATCH["opened"].append(str(args[0]))


@contextlib.contextmanager
def watching_gold():
    """Yield a list that collects every attempt, in this process, to open a file named gold.json while the block runs.
    (The CLI child processes get no corpus path at all; they only see job JSON.)"""
    if not _GOLD_WATCH["installed"]:
        sys.addaudithook(_gold_audit)
        _GOLD_WATCH["installed"] = True
    _GOLD_WATCH["active"] += 1
    start = len(_GOLD_WATCH["opened"])
    seen: list[str] = []
    try:
        yield seen
    finally:
        _GOLD_WATCH["active"] -= 1
        seen.extend(_GOLD_WATCH["opened"][start:])



def smoke(args) -> int:
    from zoop_eval.verification import build_control, load_verify_corpus, parse_verify_run, score_verify_run

    with tempfile.TemporaryDirectory(prefix="zoop-verify-smoke-") as tmp:
        # Producer phase: only a private copy of cases.json and the script exist here. No gold file is in reach, and an audit hook
        # records any attempt to open a file named gold.json while the producer runs.
        producer = Path(tmp) / "producer"
        producer.mkdir()
        (producer / "cases.json").write_bytes((args.corpus_dir / "cases.json").read_bytes())
        (producer / "script.json").write_bytes(args.script.read_bytes())
        inputs = load_inputs(producer / "cases.json")
        script = _script(producer / "script.json", inputs)
        print("== loopback pipeline: authored inputs -> installed CLI -> fake native server -> receipts -> export")
        with watching_gold() as gold_opened:
            run, server, key = run_loopback(inputs, script, Path(tmp), run_id="smoke-loopback")
        check(not gold_opened and not (producer / "gold.json").exists(), "the producer never tried to open the gold")
        try:
            requests = server.requests
            check(len(requests) == len(inputs.cases) and sorted(c for c in server.matched if c) == sorted(inputs.cases),
                  "the fake server saw exactly one request per case, each recognized from its visible content")
            check(all(r["path"] == "/v1/systemone" and r["authorization"] == "Bearer " + key for r in requests),
                  "every request was one POST /systemone carrying only the loopback key")
            check(not [h for r in requests for h in r["headers"] if h.startswith("typesafe-")], "no TypeSafe-* (data-sharing) header was sent")
            check(all(r["body"]["model"] == native_jev.MODEL and "reasoning_effort" not in r["body"] for r in requests),
                  "every native request pins the model and carries no reasoning effort")
            sent = json.dumps(requests, ensure_ascii=False)
            check("expectedGate" not in sent and "decision" not in json.dumps([r["body"]["state"] for r in requests]),
                  "no gold-side key reached the producer side")
        finally:
            server.close()
        check(run["provenance"]["kind"] == "authored_control" and run["provenance"]["controlKind"] == "loopback_fake_native_server"
              and run["system"]["endpointKind"] == "loopback_fake", "the export labels the run an authored loopback control")
        statuses = {r["caseId"]: r["status"] for r in run["records"]}
        check(set(statuses.values()) == {"ok", "error"} and len(statuses) == len(inputs.cases), "ok and error records were both recorded")
        out = Path(tmp) / "loopback.run.json"
        _write(out, run)

        print("== strict scoring of the exported run (the gold is opened only now, after the producer finished)")
        corpus = load_verify_corpus(args.corpus_dir)
        check(corpus.inputs.inputs_sha256 == inputs.inputs_sha256, "the gold is bound to the very cases.json the producer used")
        score = score_verify_run(corpus, parse_verify_run(read_json(out), corpus))
        expected = score_verify_run(corpus, parse_verify_run(build_control(corpus, "loopback_script_expected"), corpus))
        for section in ("claims", "gate", "flags", "errors"):
            check(score[section] == expected[section], f"{section}: the pipeline result equals what the script must yield under the policy")
        check(score["gate"]["unsafeAccept"]["num"] >= 1 and score["errors"]["cases"]["num"] == 3,
              "the authored deviations show up: an unsafe accept and the three injected errors")
        check(score["calibration"]["status"] == "not_evaluated", "no calibration is reported for authored loopback probabilities")
        check(score["cost"]["usd"]["total"] == 0 and score["cost"]["source"] == ["loopback_no_charge"],
              "loopback cost is 0 only as loopback_no_charge, not as a Jev price")

        print("== negative controls: plausible failures must be rejected")
        def mutated(change, code: str, label: str) -> None:
            doc = copy.deepcopy(run)
            change(doc)
            try:
                parse_verify_run(doc, corpus)
            except Rejected as exc:
                check(exc.code == code, f"{label} -> {code}" if exc.code == code else f"{label}: rejected as {exc.code}, wanted {code}")
            else:
                check(False, f"{label}: was accepted")

        ok_first = next(i for i, r in enumerate(run["records"]) if r["status"] == "ok")
        mutated(lambda d: d["records"].pop(ok_first), "missing_record", "a dropped case record")
        mutated(lambda d: d["records"].append(copy.deepcopy(d["records"][0])), "duplicate_record", "a duplicated record")
        mutated(lambda d: d["records"][ok_first].update(caseSha256="0" * 64), "case_binding_mismatch", "a case that no longer matches cases.json")
        mutated(lambda d: d["records"][ok_first]["claimBinding"].reverse(), "claim_binding_mismatch", "claims bound in another order")
        mutated(lambda d: d["records"][ok_first]["result"].update(gate="supported" if d["records"][ok_first]["result"]["gate"] != "supported" else "reject"),
                "normalization_mismatch", "a gate that the raw receipt does not yield")
        mutated(lambda d: d["records"][ok_first]["raw"]["answers"]["claim-0"]["probabilities"].update(supported=0.01),
                "raw_receipt_invalid", "a tampered probability distribution")
        mutated(lambda d: d["system"].update(model="jev-latest"), "model_not_pinned", "a moving model alias")
        mutated(lambda d: d["records"][ok_first]["call"].update(promptVersion="other"), "mixed_versions", "mixed prompt versions")
        mutated(lambda d: d["provenance"].update(kind="real_measured", executionMode="live", recordedAt="2026-10-15T00:00:00+00:00"),
                "provenance_invalid", "a loopback run relabelled as a real measurement")
        mutated(lambda d: d["provenance"].update(kind="real_measured", executionMode="replay", recordedAt="2026-10-15T00:00:00+00:00"),
                "provenance_invalid", "a replay relabelled as a real measurement")
        mutated(lambda d: d["records"][ok_first]["call"]["cost"].update(source="unknown"), "cost_unproven", "an unknown cost reported as 0")
        mutated(lambda d: d["records"][ok_first]["call"]["usage"].update(inputTokens=1), "usage_mismatch", "usage that disagrees with the receipt")
        mutated(lambda d: d["corpus"].update(inputsSha256="0" * 64), "corpus_mismatch", "another corpus digest")
    print()
    print("verification-bench smoke: " + ("PASS" if not FAILURES else f"FAIL ({len(FAILURES)} checks)"))
    return 1 if FAILURES else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    jobs = sub.add_parser("build-jobs", help="write one validated verification-only Submit JSON per case (no gold, no server)")
    jobs.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    jobs.add_argument("--out-dir", type=Path, required=True)
    run = sub.add_parser("run", help="run every case through the installed CLI against the loopback fake server and export the run")
    run.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    run.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--run-id", default="loopback-fake-native-dev")
    export = sub.add_parser("export", help="export an existing worker ledger of verify-* jobs (loopback only)")
    export.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    export.add_argument("--state-dir", type=Path, required=True)
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--run-id", default="loopback-fake-native-dev")
    smoke_cmd = sub.add_parser("smoke", help="loopback pipeline + strict scoring + negative controls; exit 0 only if every check passed")
    smoke_cmd.add_argument("--corpus-dir", type=Path, default=DEFAULT_CASES.parent)
    smoke_cmd.add_argument("--script", type=Path, default=DEFAULT_SCRIPT)
    args = parser.parse_args(argv)
    try:
        if args.command == "smoke":
            return smoke(args)
        inputs = load_inputs(args.cases)
        if args.command == "build-jobs":
            args.out_dir.mkdir(parents=True, exist_ok=True)
            for case_id, job in build_jobs(inputs).items():
                _write(args.out_dir / f"{job['jobId']}.json", job)
            print(json.dumps({"ok": True, "jobs": len(inputs.cases), "outDir": str(args.out_dir), "inputsSha256": inputs.inputs_sha256}))
        elif args.command == "run":
            script = _script(args.script, inputs)
            with tempfile.TemporaryDirectory(prefix="zoop-verify-run-") as tmp:
                document, server, _ = run_loopback(inputs, script, Path(tmp), run_id=args.run_id)
                server.close()
            _write(args.out, document)
            print(json.dumps({"ok": True, "out": str(args.out), "records": len(document["records"]),
                              "provenance": "authored_control/loopback_fake_native_server: a harness control, not a model"}))
        else:
            env = child_env("http://127.0.0.1:9/v1", "unused", len(inputs.cases), args.state_dir)
            _write(args.out, export_run(inputs, args.state_dir, env, run_id=args.run_id))
            print(json.dumps({"ok": True, "out": str(args.out)}))
    except (BridgeError, Rejected) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
