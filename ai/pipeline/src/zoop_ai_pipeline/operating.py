"""Single-owner finite batches of prepared native S2/S3 inputs on one durable metered ledger."""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
from contextlib import contextmanager
from pathlib import Path

from pydantic import ValidationError

from . import extraction, relation
from .extraction_contracts import ExtractionFailure, Submit as ExtractionSubmit
from .ingestion_contracts import Authority, IngestionFailure, now
from .live_budget import Budget, BudgetError
from .live_funding import operating_policy, stage_allowances
from .live_runtime import GATE, LiveFailure, LiveRuntime, MAX_CALLS_VAR, MAX_USD_VAR
from .relation_contracts import Submit as RelationSubmit, canonical, digest

CONFIG = "zoop-operating-runtime-config-1"
MANIFEST = "zoop-operating-input-manifest-1"
MAX_CONFIG_BYTES = 1000000
MAX_MANIFEST_BYTES = 20000000


def load(path: Path, limit: int) -> dict:
    with path.open("rb") as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("operating_input_limit")
    return json.loads(raw)


def configure(value: dict) -> dict:
    keys = {"schemaVersion", "policy", "ledgerDirectory", "stateDirectory", "runtime"}
    if not isinstance(value, dict) or set(value) != keys or value["schemaVersion"] != CONFIG:
        raise ValueError("operating_config_invalid")
    operating_policy(value["policy"])
    paths = []
    for name in ("ledgerDirectory", "stateDirectory"):
        path = Path(value[name])
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError("operating_path_invalid")
        paths.append(path)
    for i, path in enumerate(paths):
        if any(path == other or path.is_relative_to(other) or other.is_relative_to(path) for other in paths[i + 1:]):
            raise ValueError("operating_namespace_conflict")
    runtime = value["runtime"]
    if not isinstance(runtime, dict) or set(runtime) != {"model", "effort", "maxOutputTokens", "openaiEndpoint", "verifierEndpoint", "verifierModel"}:
        raise ValueError("operating_runtime_invalid")
    LiveRuntime(model=runtime["model"], effort=runtime["effort"], max_output=runtime["maxOutputTokens"],
                timeout=value["policy"]["requestTimeoutSeconds"], openai_url=runtime["openaiEndpoint"], jev_url=runtime["verifierEndpoint"],
                jev_model=runtime["verifierModel"], budget_identity=LiveRuntime._budget_identity(value["ledgerDirectory"]),
                funding=value["policy"], send=None, send_code="live_send_unavailable")
    return value


def manifest(value: dict) -> list[dict]:
    if not isinstance(value, dict) or set(value) != {"schemaVersion", "sets"} or value["schemaVersion"] != MANIFEST:
        raise ValueError("operating_manifest_invalid")
    units = value["sets"]
    if not isinstance(units, list) or not 1 <= len(units) <= 1000:
        raise ValueError("operating_manifest_invalid")
    ids, jobs = set(), set()
    for unit in units:
        if not isinstance(unit, dict) or set(unit) != {"setId", "extraction", "relationJobId", "stageAllowances", "ingestionStateDirectory", "sources"}:
            raise ValueError("operating_manifest_invalid")
        for key in ("setId", "relationJobId"):
            if not isinstance(unit[key], str) or re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", unit[key]) is None:
                raise ValueError("operating_manifest_invalid")
        for key in ("ingestionStateDirectory", "sources"):
            path = Path(unit[key])
            if not path.is_absolute() or path.resolve() != path:
                raise ValueError("operating_path_invalid")
        request = ExtractionSubmit.model_validate(unit["extraction"])
        if request.provenance.execution_mode != "live":
            raise ValueError("operating_live_input_required")
        stage_allowances(unit["stageAllowances"])
        if unit["setId"] in ids or request.job_id in jobs or unit["relationJobId"] in jobs or request.job_id == unit["relationJobId"]:
            raise ValueError("operating_manifest_duplicate")
        ids.add(unit["setId"])
        jobs.update((request.job_id, unit["relationJobId"]))
    return units


class Owner:
    def __init__(self, config: dict, *, initialize: bool = False, transport=None):
        self.config = configure(config)
        self.transport = transport
        if any(os.environ.get(name) for name in (MAX_USD_VAR, MAX_CALLS_VAR)):
            raise LiveFailure("operating_caps_forbidden")
        self.budget = (Budget.initialize(config["ledgerDirectory"], config["policy"]) if initialize else
                       Budget(config["ledgerDirectory"], None, None, policy=config["policy"]))
        if initialize:
            self.budget.bind("config", config)
            self.budget.bind("output-layout", "shared-native-1")
        elif self.budget.bound("config") != config or self.budget.bound("output-layout") != "shared-native-1":
            raise BudgetError("operating_binding_changed")
        self.root = Path(config["stateDirectory"])
        self._check_native_stores()

    def runtime(self, unit: dict, token: str, *, need_send: bool = False) -> LiveRuntime:
        config = self.config
        options = config["runtime"]
        send = LiveRuntime._env_send(os.environ, self.transport, config["ledgerDirectory"], config["policy"])
        send.update(directory=config["ledgerDirectory"], set=unit["setId"], owner=token)
        if need_send and os.environ.get(GATE) != "1":
            raise LiveFailure("live_not_enabled")
        if need_send:
            try:
                self.budget.check_active(token)
            except BudgetError as exc:
                raise LiveFailure(exc.code) from None
        if need_send and any(send["problems"].values()):
            raise LiveFailure(next(code for code in send["problems"].values() if code))
        return LiveRuntime(model=options["model"], effort=options["effort"], max_output=options["maxOutputTokens"],
                           timeout=config["policy"]["requestTimeoutSeconds"], openai_url=options["openaiEndpoint"],
                           jev_url=options["verifierEndpoint"], jev_model=options["verifierModel"],
                           budget_identity=LiveRuntime._budget_identity(config["ledgerDirectory"]), funding=config["policy"],
                           send=send, send_code="live_send_unavailable")

    def directory(self, stage: str) -> Path:
        return self.root / stage

    def _check_native_stores(self) -> dict:
        identities = {stage: self.budget.bound("native-store:" + stage) for stage in ("s2", "s3")}
        for stage, expected in identities.items():
            if expected is None:
                continue
            name = "extraction.sqlite3" if stage == "s2" else "relation.sqlite3"
            try:
                stat = (self.directory(stage) / name).stat()
            except OSError:
                raise BudgetError("operating_native_state_missing") from None
            if [stat.st_dev, stat.st_ino] != expected:
                raise BudgetError("operating_native_state_replaced")
        return identities

    @contextmanager
    def native(self, unit: dict, stage: str):
        directory = self.directory(stage)
        job = unit["extraction"]["jobId"] if stage == "s2" else unit["relationJobId"]
        expected_job = self.budget.bound("native:" + unit["setId"] + ":" + stage)
        expected_store = self._check_native_stores()[stage]
        if expected_job is not None and expected_store is None:
            raise BudgetError("operating_native_state_missing")
        ingestion = Path(unit["ingestionStateDirectory"])
        store = (extraction.Store(directory, ingestion) if stage == "s2" else
                 relation.Store(directory, self.directory("s2"), ingestion))
        try:
            if expected_job is not None:
                row = store.one("SELECT input_digest,binding FROM jobs WHERE job_id=?", (job,))
                if row is None:
                    raise BudgetError("operating_native_state_missing")
                if expected_job != {"jobId": job, "inputDigest": row["input_digest"], "bindingDigest": digest(json.loads(row["binding"]))}:
                    raise BudgetError("operating_native_state_replaced")
            yield store
        finally:
            store.close()

    def pin_native(self, unit: dict, stage: str, store):
        name = "extraction.sqlite3" if stage == "s2" else "relation.sqlite3"
        stat = (self.directory(stage) / name).stat()
        self.budget.bind("native-store:" + stage, [stat.st_dev, stat.st_ino])
        job = unit["extraction"]["jobId"] if stage == "s2" else unit["relationJobId"]
        row = store.one("SELECT input_digest,binding FROM jobs WHERE job_id=?", (job,))
        self.budget.bind("native:" + unit["setId"] + ":" + stage,
                         {"jobId": job, "inputDigest": row["input_digest"], "bindingDigest": digest(json.loads(row["binding"]))})

    def sources(self, unit: dict):
        return extraction.Sources(Path(unit["ingestionStateDirectory"]), Authority(Path(unit["sources"])))

    def register(self, value: dict) -> dict:
        units = manifest(value)
        with self.budget.owner() as token:
            for unit in units:
                self._register(unit, token)
        return {"registered": [unit["setId"] for unit in units], "metering": self.budget.snapshot()}

    def _register(self, unit: dict, token: str) -> None:
        context = {key: unit[key] for key in ("ingestionStateDirectory", "sources")}
        bound = self.budget.bound("native-input-context")
        if bound is not None and bound != context:
            raise BudgetError("operating_source_context_changed")
        ingestion = Path(unit["ingestionStateDirectory"])
        for name in ("ledgerDirectory", "stateDirectory"):
            path = Path(self.config[name])
            if path == ingestion or path.is_relative_to(ingestion) or ingestion.is_relative_to(path):
                raise ValueError("operating_namespace_conflict")
        runtime = self.runtime(unit, token)
        pins = {"unit": unit, "runtimeIdentity": runtime.binding()["identity"]}
        with self.native(unit, "s2") as store:
            access = extraction.LiveAccess(from_env=lambda **kwargs: runtime)
            engine = extraction.Extractor(store, self.sources(unit), access)
            request, fixtures = ExtractionSubmit.model_validate(unit["extraction"]), extraction.Fixtures(None, None)
            engine.admission(request, fixtures)
            self.budget.admit_operating_set(unit["setId"], pins, unit["stageAllowances"], token, jobs=(unit["extraction"]["jobId"], unit["relationJobId"]), source_context=context)
            engine.freeze(request, fixtures)
            self.pin_native(unit, "s2", store)

    def recover(self, store, job_id: str, runtime: LiveRuntime) -> int:
        """Copy only durable matching monetary receipts into their original native attempt slots under the native writer lock."""
        recovered = 0
        restored_deferral = False
        with store.transaction():
            for call in store.all("SELECT * FROM calls WHERE job_id=? AND state='started' AND response IS NULL", (job_id,)):
                receipt = self.budget.receipt(call["attempt_id"])
                if receipt is None:
                    if self.budget.is_deferred(call["attempt_id"]):
                        store.db.execute("UPDATE calls SET state='deferred' WHERE attempt_id=?", (call["attempt_id"],))
                        restored_deferral = True
                    continue
                if (receipt["attemptId"] != call["attempt_id"] or receipt["stage"] != call["stage"]
                        or receipt["bindingIdentity"] != runtime.binding()["identity"]):
                    raise BudgetError("operating_receipt_conflict")
                store.db.execute("UPDATE calls SET state='received',response=?,response_digest=?,received_at=? WHERE attempt_id=?",
                                 (canonical(receipt), digest(receipt), now(), call["attempt_id"]))
                recovered += 1
            unknown = store.one("SELECT 1 FROM calls WHERE job_id=? AND state='started' AND response IS NULL", (job_id,))
            if (recovered or restored_deferral) and unknown is None:
                store.db.execute("UPDATE jobs SET state='queued',resume_mode='resume',failure=NULL WHERE job_id=? AND state='reconciling'", (job_id,))
        return recovered

    def run(self, max_sets: int, *, set_ids: list[str] | None = None) -> dict:
        if type(max_sets) is not int or not 1 <= max_sets <= 1000:
            raise ValueError("operating_batch_limit_invalid")
        results = []
        with self.budget.owner() as token:
            entries = self.budget.sets()
            if set_ids is not None:
                selected = set(set_ids)
                if selected - {entry["id"] for entry in entries}:
                    raise BudgetError("operating_set_unavailable")
                entries = [entry for entry in entries if entry["id"] in selected]
            self._check_native_stores()
            for entry in entries:
                if entry["complete"]:
                    continue
                if len(results) >= max_sets:
                    break
                self.budget.check_active(token)
                unit = entry["pins"]["unit"]
                if self.budget.bound("native:" + unit["setId"] + ":s2") is None:
                    self._register(unit, token)
                runtime = self.runtime(unit, token)
                with self.native(unit, "s2") as store:
                    access = extraction.LiveAccess(from_env=lambda **kwargs: self.runtime(unit, token, **kwargs))
                    engine = extraction.Extractor(store, self.sources(unit), access)
                    recovered = self.recover(store, unit["extraction"]["jobId"], runtime)
                    result = engine.resume(unit["extraction"]["jobId"], extraction.Fixtures(None, None))
                item = {"setId": unit["setId"], "s2": {k: result[k] for k in ("jobId", "state", "phase", "failure", "stages")},
                        "recoveredReceipts": recovered}
                results.append(item)
                if result["state"] != "ready" or result["delivery"]["status"] != "current":
                    break
                self.budget.check_active(token)
                request = RelationSubmit.model_validate({"schemaVersion": "zoop-relation-s3", "jobId": unit["relationJobId"],
                    "provenance": unit["extraction"]["provenance"],
                    "upstream": {"jobId": result["jobId"], "inputDigest": result["inputDigest"]}})
                with self.native(unit, "s3") as store:
                    engine = relation.Engine(store, self.sources(unit), self.directory("s2"), Path(unit["ingestionStateDirectory"]),
                                             lambda need_send: self.runtime(unit, token, need_send=need_send))
                    engine.freeze(request)
                    self.pin_native(unit, "s3", store)
                    item["recoveredReceipts"] += self.recover(store, unit["relationJobId"], runtime)
                    result = engine.resume(unit["relationJobId"], relation.Fixtures(None, None))
                item["s3"] = {k: result[k] for k in ("jobId", "state", "phase", "failure")}
                if result["state"] != "ready" or result["delivery"]["status"] != "current":
                    break
                self.budget.complete_set(unit["setId"])
        snapshot = self.budget.snapshot()
        completed = {entry["id"] for entry in self.budget.sets() if entry["complete"]}
        lifecycle = self.config["policy"]["lifecycle"]
        complete = (set(lifecycle["setIds"]) <= completed if lifecycle["kind"] == "frontier" else
                    snapshot["sets"]["admitted"] == snapshot["sets"]["complete"])
        state = ("blocked" if any(item["setId"] not in completed for item in results) else
                 "complete" if complete else "batch-complete")
        return {"status": state, "sets": results, "metering": snapshot}

    def status(self) -> dict:
        native = {}
        with self.budget.owner():
            for entry in self.budget.sets():
                unit = entry["pins"]["unit"]
                for stage in ("s2", "s3"):
                    if self.budget.bound("native:" + unit["setId"] + ":" + stage) is None:
                        continue
                    with self.native(unit, stage) as store:
                        job = unit["extraction"]["jobId"] if stage == "s2" else unit["relationJobId"]
                        for call in store.all("SELECT attempt_id,state FROM calls WHERE job_id=?", (job,)):
                            native[call["attempt_id"]] = {"stage": stage, "state": call["state"]}
            monetary = self.budget.attempts()
            return {"metering": self.budget.snapshot(), "nativeAttempts": native, "monetaryAttempts": monetary,
                    "reconciliation": {"monetaryWithoutNative": sorted(set(monetary) - set(native)),
                        "nativeWithoutMonetary": sorted(set(native) - set(monetary)),
                        "receiptsAwaitingNativeRecovery": sorted(k for k in monetary.keys() & native.keys()
                            if monetary[k]["receipt"] and native[k]["state"] == "started")}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "register", "run", "status", "pause", "resume", "stop", "force-stop"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--max-sets", type=int)
    parser.add_argument("--set-id", action="append", dest="set_ids", metavar="ID",
                        help="run only these already-admitted sets, in admission order; repeatable")
    parser.add_argument("--reason")
    args = parser.parse_args(argv)
    if (args.command == "register") != (args.manifest is not None) or (args.command == "run") != (args.max_sets is not None):
        parser.error("register requires --manifest; run requires --max-sets")
    if args.set_ids is not None and args.command != "run":
        parser.error("--set-id requires run")
    control = args.command in {"pause", "resume", "stop", "force-stop"}
    if control != (args.reason is not None):
        parser.error("control commands require --reason")
    previous = {}
    try:
        owner = Owner(load(args.config, MAX_CONFIG_BYTES), initialize=args.command == "init")
        if args.command == "run":
            def stop(signum, frame):
                raise KeyboardInterrupt
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous[signum] = signal.signal(signum, stop)
        if args.command == "register":
            result = owner.register(load(args.manifest, MAX_MANIFEST_BYTES))
        elif args.command == "run":
            try:
                result = owner.run(args.max_sets, set_ids=args.set_ids)
            except KeyboardInterrupt:
                result = {"error": "operating_owner_interrupted", "metering": owner.budget.snapshot()}
                print(canonical(result))
                return 2
        elif args.command == "status":
            result = owner.status()
        elif control:
            owner.budget.control(args.command, args.reason)
            result = {"metering": owner.budget.snapshot()}
        else:
            result = {"metering": owner.budget.snapshot()}
        print(canonical(result))
        return 2 if result.get("status") == "blocked" else 0
    except (BudgetError, LiveFailure, ExtractionFailure, IngestionFailure) as exc:
        print(canonical({"error": exc.code}))
        return 2
    except (OSError, ValueError, TypeError, KeyError, ValidationError):
        print(canonical({"error": "operating_input_or_configuration_invalid"}))
        return 2
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    raise SystemExit(main())
