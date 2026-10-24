#!/usr/bin/env python3
"""Native ISSUE_SUMMARY verifier benchmark recorder; no gold in run/loopback/assemble.

Loopback is an authored HTTP control, never model-quality or model-latency evidence.
Live requires separate experiment approval; flags are prerequisites, not permission.
Journals are exclusive, private and never resumed: assemble only decodes saved receipts.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import http.server
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
PIPELINE = Path(__file__).resolve().parents[1]
EVALUATION = PIPELINE.parent / "evaluation"
sys.path.insert(0, str(EVALUATION))

from zoop_ai_pipeline import issue_summary as isum
from zoop_ai_pipeline import issue_summary_jev as jev
from zoop_ai_pipeline import live_jev
from zoop_ai_pipeline import live_runtime as live
from zoop_ai_pipeline.issue_summary_contracts import MAX_CLAIMS
from zoop_ai_pipeline.live_budget import nano_from_usd, usd
from zoop_ai_pipeline.relation_contracts import canonical, digest
from zoop_eval.contracts import Rejected, read_json
from zoop_eval.summary_verification import load_summary_inputs, load_summary_script, parse_summary_run, script_response

DEFAULT_CASES = EVALUATION / "corpus/fin-summary-verify-ko-v1/cases.json"
DEFAULT_CONTROLS = EVALUATION / "fixtures/summary-verification"
BUNDLED_SHA = "c57e0f8cb4c1caac5713b89b311a64f451cad6fd205c218a98bcc6167c1c2dd8"
RECORDER = "ai/pipeline/scripts/summary_verify_bench.py"
STAGE = jev.STAGE
RUN_SCHEMA = "zoop-summary-verify-run-1"


class BenchFailure(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise BenchFailure(code)


def install_guard(port: int | None = None, *, deny_gold: bool = True, restrict_network: bool = True):
    """Process-local audit boundary: no DNS, external sockets, binds, gold or dotenv reads.

    A producer permits only its explicitly owned IPv4 loopback port. Assembly and
    preflight tests pass no port and cannot connect anywhere. Never installed in
    the smoke parent, which opens gold only after every producer has terminated.
    """
    def guard(event, args):
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(args[0]))
            names = (path.name, path.resolve().name)
            if any(name == ".env" or name.startswith(".env.") for name in names):
                raise BenchFailure("bench_secret_file_forbidden")
            if deny_gold and "gold.json" in names:
                raise BenchFailure("bench_gold_forbidden")
        if not restrict_network:
            return
        if event == "socket.connect":
            address = args[1]
            if port is not None and isinstance(address, tuple) and address[:2] == ("127.0.0.1", port):
                return
            raise BenchFailure("bench_external_network_forbidden")
        if event == "socket.getaddrinfo":
            if port is not None and args[0] == "127.0.0.1" and args[1] == port:
                return
            raise BenchFailure("bench_external_network_forbidden")
        if event in {"socket.bind", "socket.gethostbyname", "socket.gethostbyaddr", "socket.sendto"}:
            raise BenchFailure("bench_external_network_forbidden")
    sys.addaudithook(guard)


def adapter_preimage():
    policy = {"choiceProbability": live_jev.CHOICE_PROBABILITY, "choiceConfidence": live_jev.CHOICE_CONFIDENCE,
              "distributionTolerance": live_jev.DISTRIBUTION_TOLERANCE}
    preimage = {"revision": jev.ADAPTER_REVISION, "api": live_jev.API, "model": live_jev.MODEL, "policy": policy,
                "task": jev.TASK, "maxClaims": MAX_CLAIMS, "contexts": jev.CONTEXTS, "claimQuestion": jev.CLAIM_QUESTION,
                "claimCriteria": jev.CLAIM_CRITERIA, "adviceQuestion": jev.ADVICE_QUESTION, "adviceCriteria": jev.ADVICE_CRITERIA,
                "causalityQuestion": jev.CAUSALITY_QUESTION, "causalityCriteria": jev.CAUSALITY_CRITERIA,
                "framingQuestion": jev.FRAMING_QUESTION, "framingCriteria": jev.FRAMING_CRITERIA,
                "options": [jev.CLAIM_OPTIONS, jev.CHECK_OPTIONS]}
    require(digest(preimage) == jev.identity(), "bench_adapter_mismatch")
    return json.loads(canonical(preimage))


def normalized(runtime, receipt):
    answer = runtime.answer(STAGE, receipt)
    return {"outcome": jev.outcome(answer), "claims": [{"claimId": c["claimId"], "decision": c["decision"]} for c in answer["claims"]],
            **{key: answer[key] for key in ("prohibitedAdvice", "unsupportedCausality", "backgroundAsCurrent")}}


def exclusive_json(path: Path, value):
    """Publish only complete, durable JSON, atomically and without replacing a name.

    A killed writer may leave a private .pending file. Assembly reads only the
    published journal names, so a partial write cannot masquerade as a receipt.
    A hard link is the atomic no-clobber operation; rename would replace a file.
    """
    fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".pending", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write((canonical(value) + "\n").encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.link(staging, path)
    finally:
        os.unlink(staging)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def fresh_directory(path: Path):
    return not path.is_symlink() and (not path.exists() or (path.is_dir() and not any(path.iterdir())))


def visible_root(inputs):
    return {key: value for key, value in inputs.items() if key not in {"inputsSha256", "casesById"}}


def base_record(case, run_id):
    return {"caseId": case["caseId"], "caseSha256": digest(case),
            "claimBinding": [{"claimId": claim["claimId"], "key": f"claim-{i}"} for i, claim in enumerate(case["payload"]["claims"])],
            "attemptId": f"sumbench-{run_id}-{case['caseId']}"}


def error_record(base, code, phase, *, unknown=False):
    return {**base, "status": "error", "error": {"code": code, "phase": phase, "outcome": "unknown" if unknown else "definite"}}


def prepare(runtime, case):
    payload = case["payload"]
    prepared = runtime.prepare(STAGE, payload)
    claims = [{"claimId": c["claimId"], "text": c["text"], "evidenceIds": c["quoteIds"]} for c in payload["claims"]]
    via_s2 = runtime.prepare(STAGE, isum.verifier_payload(payload, claims))
    require(prepared == via_s2, "bench_s2_mapping_mismatch")
    return prepared


def preflight(args, inputs):
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", args.run_id), "bench_run_id_invalid")
    endpoint = os.environ.get(live.JEV_URL_VAR, "")
    require(bool(endpoint), "bench_endpoint_required")
    if args.mode == "loopback":
        url = urlsplit(endpoint)
        require(url.scheme == "http" and url.hostname == "127.0.0.1" and url.port is not None and url.path == "/v1"
                and not url.username and not url.password and not url.query and not url.fragment, "bench_loopback_endpoint_required")
        require(bool(re.fullmatch(r"[0-9a-f]{64}", args.script_sha256 or "")), "bench_script_digest_required")
        require(args.script_variant in {"oracle", "deviations"}, "bench_script_variant_required")
        require(os.environ.get(live.JEV_KEY_VAR, "").startswith("tsk-summary-loopback-"), "bench_fake_key_required")
    else:
        require(Path(args.cases).resolve() == DEFAULT_CASES.resolve() and inputs["inputsSha256"] == BUNDLED_SHA,
                "bench_bundled_inputs_required")
        require(args.confirm_inputs_sha256 == BUNDLED_SHA, "bench_confirmation_required")
        require(endpoint == live.DEFAULT_JEV_URL, "bench_live_endpoint_required")
    require(not args.out_dir.exists() and not args.out_dir.is_symlink(), "bench_directory_exists")
    runtime = live.LiveRuntime.from_env(family=live.ISSUE_SUMMARY)
    directory = Path(os.environ[live.BUDGET_DIR_VAR])
    require(fresh_directory(directory), "bench_budget_not_fresh")
    # Verify-only: the existing runtime requires a Jev key, not an unrelated OpenAI key.
    key = os.environ.get(live.JEV_KEY_VAR, "")
    require(bool(key) and key.isascii() and key.isprintable() and " " not in key, "live_typesafe_key_required")
    try:
        max_nano = nano_from_usd(os.environ.get(live.MAX_USD_VAR, ""))
        calls = os.environ.get(live.MAX_CALLS_VAR, "")
        require(calls.isascii() and calls.isdigit() and 1 <= int(calls) <= 100_000, "live_budget_config_invalid")
    except ValueError:
        raise BenchFailure("live_budget_config_invalid") from None
    bound = 0
    for case in inputs["cases"]:
        try:
            bound += prepare(runtime, case)["reservation"]["worstCaseNanoUsd"]
        except live.LiveFailure:
            # The run records this case's prepare failure; it never sends it.
            continue
    require(int(calls) >= len(inputs["cases"]) and max_nano >= bound, "bench_budget_insufficient")
    return runtime, {"caseCount": len(inputs["cases"]), "inputsSha256": inputs["inputsSha256"], "worstCaseUsd": usd(bound),
                     "maxUsd": usd(max_nano), "maxCalls": int(calls), "keyPresent": bool(key), "budgetFresh": True}


def run(args):
    inputs = load_summary_inputs(args.cases)
    runtime, plan = preflight(args, inputs)
    preimage = adapter_preimage()
    if args.check:
        return plan
    args.out_dir.mkdir(mode=0o700)
    binding = runtime.binding()
    authored = args.mode == "loopback"
    provenance = {"kind": "authored_control" if authored else "real_measured", "executionMode": args.mode,
                  "recorder": RECORDER, "recordedAt": datetime.now(timezone.utc).isoformat(),
                  "note": ("Authored_control/loopback: native HTTP requests to an owned local simulator; external provider/model calls: 0. "
                           "Model quality is not measured. Send intervals include runtime budget, authorization, network and settlement; "
                           "they are not model latency.") if authored else
                          "Native verifier send intervals include runtime budget, authorization, network and settlement; runtime estimates are not provider bills. Experiment approval is separate."}
    if authored:
        provenance.update(controlKind="loopback_fake_native_server", scriptSha256=args.script_sha256, scriptVariant=args.script_variant)
    meta = {"schema": RUN_SCHEMA, "runId": args.run_id, "provenance": provenance,
            "corpus": {"corpusId": inputs["corpusId"], "corpusRevision": inputs["revision"], "inputsSha256": inputs["inputsSha256"], "split": inputs["split"]},
            "system": {"stage": STAGE, "endpointKind": "loopback_fake" if authored else "provider", "binding": binding, "adapterPreimage": preimage},
            "timing": {"clock": "time.perf_counter_ns", "scope": "live-runtime-send-1", "concurrency": 1}}
    exclusive_json(args.out_dir / "meta.json", meta)
    exclusive_json(args.out_dir / "binding.json", binding)
    exclusive_json(args.out_dir / "inputs.json", visible_root(inputs))
    records = []
    for index, case in enumerate(inputs["cases"]):
        prefix = args.out_dir / f"{index:03d}"
        base = base_record(case, args.run_id)
        try:
            prepared = prepare(runtime, case)
        except live.LiveFailure as exc:
            record = error_record(base, exc.code, "prepare")
        else:
            base["prepared"] = prepared
            exclusive_json(prefix.with_suffix(".intent.json"), base)
            authorized = None
            start = time.perf_counter_ns()
            def authorize():
                nonlocal authorized
                authorized = time.perf_counter_ns() - start
            try:
                receipt = runtime.send(prepared, attempt_id=base["attemptId"], authorize=authorize)
            except live.LiveFailure as exc:
                timing = {"sendCallNs": time.perf_counter_ns() - start, "authorizedOffsetNs": authorized}
                record = error_record({**base, "timing": timing}, exc.code, "send", unknown=exc.uncertain)
            else:
                timing = {"sendCallNs": time.perf_counter_ns() - start, "authorizedOffsetNs": authorized}
                exclusive_json(prefix.with_suffix(".receipt.json"), {"receipt": receipt, "timing": timing})
                captured = {**base, "receipt": receipt, "timing": timing}
                try:
                    record = {**captured, "status": "ok", "result": normalized(runtime, receipt)}
                except live.LiveFailure as exc:
                    record = error_record(captured, exc.code, "decode")
        exclusive_json(prefix.with_suffix(".outcome.json"), record)
        records.append(record)
    result = {**meta, "records": records}
    parse_summary_run(result, inputs)
    exclusive_json(args.out_dir / "run.json", result)
    return result


def assemble(directory):
    """Read-only, env-less decode; a crash never grants permission to resend."""
    inputs = load_summary_inputs(directory / "inputs.json")
    meta, binding = read_json(directory / "meta.json"), read_json(directory / "binding.json")
    require(meta["system"]["binding"] == binding, "bench_journal_binding_mismatch")
    runtime = live.LiveRuntime.from_binding(binding)
    records = []
    for index, case in enumerate(inputs["cases"]):
        prefix = directory / f"{index:03d}"
        base = base_record(case, meta["runId"])
        intent, captured, outcome = (prefix.with_suffix(suffix) for suffix in (".intent.json", ".receipt.json", ".outcome.json"))
        if intent.exists():
            stored = read_json(intent)
            require(all(stored.get(key) == value for key, value in base.items()), "bench_journal_case_mismatch")
            require(stored.get("prepared") == prepare(runtime, case), "bench_journal_prepared_mismatch")
            base = stored
        if captured.exists():
            require(intent.exists(), "bench_journal_intent_missing")
            saved = read_json(captured)
            captured_base = {**base, "receipt": saved["receipt"], "timing": saved["timing"]}
            try:
                record = {**captured_base, "status": "ok", "result": normalized(runtime, saved["receipt"])}
            except live.LiveFailure as exc:
                record = error_record(captured_base, exc.code, "decode")
            if outcome.exists():
                require(read_json(outcome) == record, "bench_journal_outcome_mismatch")
        elif outcome.exists():
            record = read_json(outcome)
            require(all(record.get(key) == value for key, value in base.items()), "bench_journal_case_mismatch")
            require("receipt" not in record and record.get("status") == "error", "bench_journal_receipt_missing")
        elif intent.exists():
            record = error_record(base, "bench_outcome_unrecorded", "unrecorded", unknown=True)
        else:
            record = error_record(base, "bench_not_attempted", "unrecorded")
        records.append(record)
    return parse_summary_run({**meta, "records": records}, inputs)


def child_env(base, key, count, home, budget):
    # Start from nothing: no inherited provider credentials, proxies, dotenv or PYTHONPATH.
    return {"PATH": "/usr/bin:/bin", "HOME": str(home), "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
            live.GATE: "1", live.MODEL_VAR: live.MODEL, live.EFFORT_VAR: "high", live.JEV_MODEL_VAR: live_jev.MODEL,
            live.JEV_URL_VAR: base, live.OPENAI_URL_VAR: base, live.JEV_KEY_VAR: key,
            live.BUDGET_DIR_VAR: str(budget), live.MAX_USD_VAR: "1", live.MAX_CALLS_VAR: str(count), live.TIMEOUT_VAR: "10"}


def child(arguments, env, *, hook="", network_port=None):
    # The guard is active before argument parsing/loading any input or starting the runtime.
    program = ("import runpy,sys\n"
               f"sys.path.insert(0,{str(PIPELINE)!r})\n"
               "from scripts import summary_verify_bench as b\n"
               f"b.install_guard({network_port!r})\n" + hook + "raise SystemExit(b.main(sys.argv[1:]))\n")
    return subprocess.run([sys.executable, "-c", program, *map(str, arguments)], env=env, capture_output=True, text=True, timeout=180)


class Loopback:
    """Owned HTTP listener. Matching uses the complete native request, never gold labels."""
    def __init__(self, inputs, script, key):
        self.requests, self.failures = [], []
        self.key = key
        by_request = {digest(jev.build_request(case["payload"], live_jev.MODEL)[0]): case["caseId"] for case in inputs["cases"]}
        require(len(by_request) == len(inputs["cases"]), "bench_ambiguous_request")
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    require(0 < length <= live.MAX_VERIFIER_REQUEST_BYTES, "bench_request_size")
                    body = json.loads(self.rfile.read(length))
                    case_id = by_request.get(digest(body))
                    require(self.path == "/v1/systemone" and case_id is not None, "bench_unscripted_request")
                    require(self.headers.get("Authorization") == "Bearer " + owner.key, "bench_unexpected_key")
                    owner.requests.append({"caseId": case_id, "path": self.path, "body": body, "fakeKeyMatched": True})
                    response = script_response(inputs, script, case_id)
                    if response is None:
                        self.close_connection = True
                        self.connection.shutdown(socket.SHUT_RDWR)
                        return
                    status, content = response
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                except Exception as exc:
                    owner.failures.append(getattr(exc, "code", type(exc).__name__))
                    self.close_connection = True
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def loopback(args):
    require(not args.out.exists() and not args.out.is_symlink(), "bench_output_exists")
    inputs = load_summary_inputs(args.cases)
    script = load_summary_script(args.script, inputs)
    journal = args.out_dir or Path(str(args.out) + ".journal")
    budget = args.budget_dir or Path(str(args.out) + ".budget")
    require(not journal.exists() and not journal.is_symlink(), "bench_directory_exists")
    require(fresh_directory(budget), "bench_budget_not_fresh")
    key = "tsk-summary-loopback-" + secrets.token_hex(24)
    server = Loopback(inputs, script, key)
    try:
        with tempfile.TemporaryDirectory(prefix="zoop-summary-home-") as home:
            env = child_env(server.base, key, len(inputs["cases"]), Path(home), budget.resolve())
            done = child(["run", "--mode", "loopback", "--cases", args.cases, "--out-dir", journal, "--run-id", args.run_id,
                          "--script-sha256", digest(script), "--script-variant", script["variant"]], env, network_port=server.port)
        require(done.returncode == 0, "bench_child_failed:" + (json.loads(done.stdout).get("error", "unknown") if done.stdout.startswith("{") else "no_result"))
        require(not server.failures, "bench_server_failed")
        require([r["caseId"] for r in server.requests] == [c["caseId"] for c in inputs["cases"]], "bench_post_count_mismatch")
        result = parse_summary_run(read_json(journal / "run.json"), inputs)
        for case_id in ("NS10", "NS23"):
            if case_id not in inputs["casesById"]:
                continue
            payload = inputs["casesById"][case_id]["payload"]
            cited = {qid for claim in payload["claims"] for qid in claim["quoteIds"]}
            quotes = [q for q in payload["quotes"] if q["quoteId"] in cited]
            sent = next(r["body"]["state"]["quotes"] for r in server.requests if r["caseId"] == case_id)
            require(sent == [{"label": f"Q{i}", "context": q["context"], "text": q["text"]} for i, q in enumerate(quotes, 1)],
                    "bench_uncited_quote_leak")
        for root in (journal, budget):
            for path in root.rglob("*"):
                if path.is_file():
                    require(key.encode() not in path.read_bytes(), "bench_key_written")
        require(key not in done.stdout and key not in done.stderr, "bench_key_printed")
        exclusive_json(args.out, result)
        return result
    finally:
        server.close()


def tamper_matrix(inputs, oracle, deviations, root):
    """Consumer integrity checks against captured native requests/receipts."""
    checks = []

    def add(name, code, mutate, source=oracle):
        changed = copy.deepcopy(source)
        mutate(changed)
        try:
            parse_summary_run(changed, inputs)
        except Rejected as exc:
            require(exc.code == code, f"bench_tamper_{name}:{exc.code}!={code}")
        else:
            raise BenchFailure("bench_tamper_accepted:" + name)
        checks.append(name)

    def at(run, case_id):
        return next(record for record in run["records"] if record["caseId"] == case_id)

    def set_at(path, value):
        def change(run):
            node = run
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = value
        return change

    def rehash(record):
        prepared = record["prepared"]
        prepared["requestDigest"] = digest(prepared["body"])
        prepared["requestBytes"] = len(canonical(prepared["body"]).encode())
        bound = prepared["requestBytes"] * len(prepared["body"]["questions"]) + live.INPUT_OVERHEAD_TOKENS
        nano = bound * live.PRICING[live_jev.MODEL]["input"]
        prepared["reservation"] = {"inputTokensUpperBound": bound, "outputTokensMax": 0, "worstCaseNanoUsd": nano, "worstCaseUsd": usd(nano)}
        prepared["digest"] = digest({k: v for k, v in prepared.items() if k != "digest"})
        record["receipt"]["requestDigest"] = prepared["requestDigest"]
        record["receipt"]["cost"]["reservedUsd"] = usd(nano)

    def probability(run, coherent):
        receipt = run["records"][0]["receipt"]
        raw = json.loads(receipt["http"]["bodyText"])
        raw["answers"]["claim-0"]["probabilities"] = {"supported": 0.85, "contradicted": 0.05, "insufficient": 0.10}
        receipt["http"]["bodyText"] = canonical(raw)
        if coherent:
            receipt["http"]["bodySha256"] = hashlib.sha256(receipt["http"]["bodyText"].encode()).hexdigest()

    add("dropped", "missing_record", lambda run: run["records"].pop())
    add("duplicate", "duplicate_record", lambda run: run["records"].append(copy.deepcopy(run["records"][0])))
    add("case", "case_binding_mismatch", set_at(["records", 0, "caseSha256"], "0" * 64))
    multi = next(i for i, r in enumerate(oracle["records"]) if len(r["claimBinding"]) > 1)
    add("claim-order", "claim_binding_mismatch", lambda run: run["records"][multi]["claimBinding"].reverse())
    add("outcome", "normalization_mismatch", set_at(["records", 0, "result", "outcome"], "verifier-reject"))
    add("decision", "normalization_mismatch", set_at(["records", 0, "result", "claims", 0, "decision"], "contradicted"))
    add("framing", "normalization_mismatch", lambda run: at(run, "NS22")["result"].update(backgroundAsCurrent="absent"), deviations)
    add("body", "receipt_body_mismatch", lambda run: probability(run, False))
    add("body-rehashed", "normalization_mismatch", lambda run: probability(run, True))
    add("usage", "usage_mismatch", set_at(["records", 0, "receipt", "usage", "inputTokens"], 1))
    add("cost", "cost_mismatch", set_at(["records", 0, "receipt", "cost", "estimatedUsd"], "999"))
    add("receipt-binding", "receipt_binding_mismatch", set_at(["records", 0, "receipt", "bindingIdentity"], "0" * 64))
    add("binding-policy", "binding_invalid", set_at(["system", "binding", "verifier", "policy", "choiceProbability"], 0.91))

    def binding_rehash(run):
        binding = run["system"]["binding"]
        binding["verifier"]["policy"]["choiceProbability"] = 0.91
        preimage = run["system"]["adapterPreimage"]
        preimage["policy"]["choiceProbability"] = 0.91
        identity = digest(preimage)
        binding["verifier"]["adapterIdentity"] = identity
        binding["stages"][STAGE]["questionsDigest"] = identity
        binding["stages"][STAGE]["promptVersion"] = jev.PROMPT_PREFIX + identity[:16]
        binding["identity"] = digest({k: v for k, v in binding.items() if k != "identity"})
        for record in run["records"]:
            prepared = record["prepared"]
            prepared["bindingIdentity"] = binding["identity"]
            prepared["schemaDigest"] = identity
            prepared["promptVersion"] = binding["stages"][STAGE]["promptVersion"]
            prepared["digest"] = digest({k: v for k, v in prepared.items() if k != "digest"})
    add("binding-rehashed", "receipt_binding_mismatch", binding_rehash)

    def question(run, coherent):
        record = run["records"][0]
        record["prepared"]["body"]["questions"]["claim-0"]["criteria"]["supported"] += " Changed."
        if coherent:
            rehash(record)
    add("question", "prepared_invalid", lambda run: question(run, False))
    add("question-rehashed", "questions_mismatch", lambda run: question(run, True))

    def uncited(run):
        record = at(run, "NS10")
        payload = inputs["casesById"]["NS10"]["payload"]
        cited = {qid for claim in payload["claims"] for qid in claim["quoteIds"]}
        unused = next(q for q in payload["quotes"] if q["quoteId"] not in cited)
        record["prepared"]["body"]["state"]["quotes"].append({"label": "Q2", "context": unused["context"], "text": unused["text"]})
        rehash(record)
    add("uncited", "request_mapping_mismatch", uncited)

    def context(run):
        record = run["records"][0]
        record["prepared"]["body"]["state"]["quotes"][0]["context"] = "background"
        rehash(record)
    add("context", "request_mapping_mismatch", context)

    def expect(run):
        record = run["records"][0]
        record["prepared"]["expect"]["claims"][0]["quoteIds"] = ["unknown"]
        record["prepared"]["digest"] = digest({k: v for k, v in record["prepared"].items() if k != "digest"})
    add("expect", "request_mapping_mismatch", expect)
    add("preimage", "adapter_preimage_mismatch", set_at(["system", "adapterPreimage", "task"], "Changed task."))
    add("relabelled", "provenance_invalid", set_at(["provenance", "kind"], "real_measured"))
    add("error-code", "error_not_reproducible", lambda run: at(run, "NS19")["error"].update(code="live_http_404"), deviations)
    add("unknown-definite", "error_invalid", lambda run: at(run, "NS17")["error"].update(outcome="definite"), deviations)
    add("timing", "timing_invalid", lambda run: run["records"][0]["timing"].update(
        authorizedOffsetNs=run["records"][0]["timing"]["sendCallNs"] + 1))
    add("inputs-digest", "corpus_mismatch", set_at(["corpus", "inputsSha256"], "0" * 64))
    for name, code, mutate in (
        ("gold", "gold_leak", lambda case: case.update(tags=["forbidden"])),
        ("empty-citations", "claim_citation_invalid", lambda case: case["payload"]["claims"][0].update(quoteIds=[])),
        ("unknown-citations", "claim_citation_invalid", lambda case: case["payload"]["claims"][0].update(quoteIds=["missing"])),
    ):
        raw = copy.deepcopy(visible_root(inputs))
        mutate(raw["cases"][0])
        path = root / (name + ".cases.json")
        exclusive_json(path, raw)
        try:
            load_summary_inputs(path)
        except Rejected as exc:
            require(exc.code == code, "bench_input_tamper:" + exc.code)
        else:
            raise BenchFailure("bench_input_tamper_accepted")
        checks.append(name)
    return checks


def smoke(controls):
    """Actual isolated subprocesses and HTTP; gold opens only after producers finish."""
    from zoop_eval.summary_verification import derive_receipt, script_expectation

    with tempfile.TemporaryDirectory(prefix="zoop-summary-bench-") as temporary:
        root = Path(temporary)
        inputs = load_summary_inputs(DEFAULT_CASES)
        runs = {}
        for variant in ("oracle", "deviations"):
            args = parser().parse_args(["loopback", "--script", str(controls / f"{variant}.script.json"), "--out", str(root / f"{variant}.json"),
                                       "--run-id", "smoke-" + variant])
            runs[variant] = loopback(args)
            script = load_summary_script(args.script, inputs)
            expected = script_expectation(inputs, script)
            for record in runs[variant]["records"]:
                actual = {key: record[key] for key in ("status", "result", "error") if key in record}
                require(actual == expected[record["caseId"]], "bench_script_expectation:" + record["caseId"])
                if "receipt" in record:
                    runtime = live.LiveRuntime.from_binding(runs[variant]["system"]["binding"])
                    try:
                        native = normalized(runtime, record["receipt"])
                    except live.LiveFailure as exc:
                        try:
                            derive_receipt(record["receipt"], runtime.binding())
                        except Rejected as mirror:
                            require(mirror.code == exc.code, "bench_decode_error_parity")
                        else:
                            raise BenchFailure("bench_decode_error_missing")
                    else:
                        require(native == derive_receipt(record["receipt"], runtime.binding()), "bench_decode_parity")
            done = child(["assemble", "--out-dir", str(args.out) + ".journal"], {"PATH": "/usr/bin:/bin", "HOME": str(root)})
            require(done.returncode == 0 and json.loads(done.stdout) == runs[variant], "bench_assemble_mismatch")
        tampered = tamper_matrix(inputs, runs["oracle"], runs["deviations"], root)
        script = load_summary_script(controls / "oracle.script.json", inputs)
        key = "tsk-summary-loopback-" + secrets.token_hex(24)
        server = Loopback(inputs, script, key)
        try:
            crash_cases = [
                ("intent", ".intent.json", "after", 0, "unknown"),
                ("receipt", ".receipt.json", "after", 1, "ok"),
                ("intent-unpublished", ".intent.json", "before", 0, "not-attempted"),
                ("receipt-unpublished", ".receipt.json", "before", 1, "unknown"),
                ("outcome-unpublished", ".outcome.json", "before", 1, "ok"),
            ]
            for label, suffix, publication, expected_posts, first in crash_cases:
                journal = root / ("crash-" + label)
                env = child_env(server.base, key, len(inputs["cases"]), root, root / ("budget-" + label))
                arguments = ["run", "--mode", "loopback", "--out-dir", journal, "--run-id", "crash-" + label, "--script-sha256", digest(script)]
                hook = ("import os\n_original = b.exclusive_json\n"
                        "def _crash(path, value):\n"
                        " _original(path,value)\n"
                        f" if str(path).endswith({suffix!r}): os._exit(9)\n"
                        "b.exclusive_json = _crash\n")
                if publication == "before":
                    hook = ("import os\nfrom pathlib import Path\n_link=b.os.link\n"
                            "def _crash(source,destination,*args,**kwargs):\n"
                            f" if str(destination).endswith({suffix!r}):\n"
                            "  Path(source).write_bytes(b'{\"partial\":')\n"
                            "  os._exit(9)\n"
                            " return _link(source,destination,*args,**kwargs)\n"
                            "b.os.link=_crash\n")
                before = len(server.requests)
                killed = child(arguments, env, hook=hook, network_port=server.port)
                require(killed.returncode == 9 and len(server.requests) - before == expected_posts, "bench_crash_boundary")
                snapshot = {str(p.relative_to(journal)): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
                            for p in journal.iterdir() if p.is_file()}
                recovered = child(["assemble", "--out-dir", journal], {"PATH": "/usr/bin:/bin", "HOME": str(root)})
                require(recovered.returncode == 0, "bench_crash_assemble")
                records = json.loads(recovered.stdout)["records"]
                if first == "ok":
                    require(records[0]["result"] == runs["oracle"]["records"][0]["result"], "bench_receipt_recovery")
                else:
                    require(records[0]["error"] == {
                        "code": "bench_outcome_unrecorded" if first == "unknown" else "bench_not_attempted",
                        "phase": "unrecorded", "outcome": "unknown" if first == "unknown" else "definite"}, "bench_intent_recovery")
                if publication == "before":
                    require(not (journal / ("000" + suffix)).exists() and any(journal.glob("*.pending")), "bench_partial_published")
                require(all(r["error"]["code"] == "bench_not_attempted" for r in records[1:]), "bench_not_attempted_missing")
                again = child(arguments, env, network_port=server.port)
                require(again.returncode == 2 and json.loads(again.stdout)["error"] == "bench_directory_exists"
                        and len(server.requests) - before == expected_posts, "bench_crash_resent")
                require(snapshot == {str(p.relative_to(journal)): (p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns)
                                     for p in journal.iterdir() if p.is_file()}, "bench_assemble_wrote")
                require(journal.stat().st_mode & 0o777 == 0o700 and all(p.stat().st_mode & 0o777 == 0o600 for p in journal.iterdir()),
                        "bench_journal_permissions")
        finally:
            server.close()
        env = child_env(live.DEFAULT_JEV_URL, key, len(inputs["cases"]), root, root / "live-budget")
        arguments = ["run", "--mode", "live", "--check", "--out-dir", root / "live-journal", "--run-id", "live-check"]
        refusals = []
        for name, extra, altered, code in (
            ("no-confirm", [], {}, "bench_confirmation_required"),
            ("wrong-confirm", ["--confirm-inputs-sha256", "0" * 64], {}, "bench_confirmation_required"),
            ("wrong-endpoint", ["--confirm-inputs-sha256", BUNDLED_SHA], {live.JEV_URL_VAR: "http://127.0.0.1:1/v1"}, "bench_live_endpoint_required"),
            ("missing-gate", ["--confirm-inputs-sha256", BUNDLED_SHA], {live.GATE: "0"}, "live_not_enabled"),
            ("wrong-model", ["--confirm-inputs-sha256", BUNDLED_SHA], {live.JEV_MODEL_VAR: "jev-latest"}, "live_jev_model_unsupported"),
        ):
            done = child(arguments + extra, {**env, **altered})
            require(done.returncode == 2 and json.loads(done.stdout)["error"] == code, "bench_live_refusal:" + name)
            refusals.append(name)
        missing_url = dict(env)
        del missing_url[live.JEV_URL_VAR]
        done = child(["run", "--mode", "loopback", "--out-dir", root / "unset-journal", "--run-id", "unset", "--script-sha256", digest(script)], missing_url)
        require(done.returncode == 2 and json.loads(done.stdout)["error"] == "bench_endpoint_required", "bench_endpoint_defaulted")
        refusals.append("unset-loopback-endpoint")
        success = child(arguments + ["--confirm-inputs-sha256", BUNDLED_SHA], env)
        require(success.returncode == 0 and json.loads(success.stdout)["keyPresent"] is True and key not in success.stdout,
                "bench_live_check_failed")
        require(not (root / "live-budget").exists() and not (root / "live-journal").exists(), "bench_check_wrote")
        (root / "live-budget").mkdir()
        exclusive_json(root / "live-budget" / "foreign.json", {})
        done = child(arguments + ["--confirm-inputs-sha256", BUNDLED_SHA], env)
        require(done.returncode == 2 and json.loads(done.stdout)["error"] == "bench_budget_not_fresh", "bench_reused_budget")
        refusals.append("reused-budget")
        hook = (
            "from pathlib import Path\nimport socket\n"
            "for action,code in [(lambda: b.DEFAULT_CASES.with_name('gold.json').read_bytes(),'bench_gold_forbidden'),\n"
            " (lambda: Path('.env').read_bytes(),'bench_secret_file_forbidden'),\n"
            " (lambda: socket.create_connection(('203.0.113.1',443),timeout=1),'bench_external_network_forbidden')]:\n"
            " try: action()\n"
            " except b.BenchFailure as exc: assert exc.code == code\n"
            " else: raise AssertionError('guard permitted forbidden action')\n")
        guarded = child(["assemble", "--out-dir", str(root / "oracle.json") + ".journal"], {"PATH": "/usr/bin:/bin", "HOME": str(root)}, hook=hook)
        require(guarded.returncode == 0, "bench_guard_failed")
        # Only now is gold in scope: every producer and live/no-network check has exited.
        from zoop_eval.summary_verification import load_summary_corpus, score_summary_run
        corpus = load_summary_corpus()
        scores = {variant: score_summary_run(corpus, result) for variant, result in runs.items()}
        require(scores["oracle"]["claims"]["accuracy"]["value"] == 1 and scores["oracle"]["outcomes"]["accuracy"]["value"] == 1
                and scores["oracle"]["errors"]["total"] == 0, "bench_oracle_score")
        require(scores["deviations"]["claims"]["accuracy"]["num"] == 22 and scores["deviations"]["outcomes"]["accuracy"]["num"] == 14
                and scores["deviations"]["errors"]["total"] == 5 and scores["deviations"]["errors"]["unknown"] == 1, "bench_deviation_score")
        for record in runs["oracle"]["records"]:
            gold = corpus["goldById"][record["caseId"]]
            result = record["result"]
            require(result["outcome"] == gold["expectedGate"] and
                    {c["claimId"]: c["decision"] for c in result["claims"]} == gold["goldClaimLabels"] and
                    [result[k] for k in ("prohibitedAdvice", "unsupportedCausality", "backgroundAsCurrent")] ==
                    [gold[k] for k in ("expectedAdvice", "expectedCausality", "expectedFraming")], "bench_oracle_gold_mismatch")
        return {"status": "passed", "executionMode": "loopback", "provenanceKind": "authored_control",
                "controlHttpRequests": sum(len(result["records"]) for result in runs.values()), "crashHttpRequests": len(server.requests),
                "externalProviderRequests": 0, "externalModelCalls": 0, "modelQualityMeasured": False,
                "timingNote": "Native send intervals include runtime budget, authorization, local HTTP and settlement; not model latency.",
                "casesPerControl": len(inputs["cases"]), "controls": list(runs), "tamperChecks": tampered,
                "liveRefusals": refusals, "crashBoundaries": [case[0] for case in crash_cases], "goldOpenedAfterProducers": True,
                "externalNetworkBlocked": True, "scores": scores}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    produce = commands.add_parser("run")
    produce.add_argument("--mode", choices=("loopback", "live"), required=True)
    produce.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    produce.add_argument("--out-dir", type=Path, required=True)
    produce.add_argument("--run-id", required=True)
    produce.add_argument("--script-sha256")
    produce.add_argument("--script-variant", choices=("oracle", "deviations"), default="oracle")
    produce.add_argument("--confirm-inputs-sha256")
    produce.add_argument("--check", action="store_true")
    local = commands.add_parser("loopback")
    local.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    local.add_argument("--script", type=Path, required=True)
    local.add_argument("--out", type=Path, required=True)
    local.add_argument("--out-dir", type=Path)
    local.add_argument("--budget-dir", type=Path)
    local.add_argument("--run-id", default="local-" + secrets.token_hex(6))
    assembly = commands.add_parser("assemble")
    assembly.add_argument("--out-dir", type=Path, required=True)
    assembly.add_argument("--out", type=Path)
    checks = commands.add_parser("smoke")
    checks.add_argument("--controls-dir", type=Path, default=DEFAULT_CONTROLS)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "run":
            if args.mode == "loopback":
                endpoint = os.environ.get(live.JEV_URL_VAR, "")
                install_guard(urlsplit(endpoint).port if endpoint else None)
            else:
                install_guard(restrict_network=False)
            result = run(args)
        elif args.command == "assemble":
            install_guard()
            result = assemble(args.out_dir)
            if args.out:
                exclusive_json(args.out, result)
        elif args.command == "loopback":
            install_guard(restrict_network=False)
            result = loopback(args)
        else:
            result = smoke(args.controls_dir)
        print(canonical(result))
        return 0
    except (BenchFailure, live.LiveFailure, Rejected) as exc:
        print(canonical({"error": exc.code}))
        return 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Never render arbitrary OS/provider text or configuration values (including keys).
        print(canonical({"error": "bench_" + type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
