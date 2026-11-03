"""Durable exact-body round orchestration over native ownership and admission seams."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
import threading
import time
from types import SimpleNamespace
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from . import handoff_access, plan_verify
from .config import ConfigError
from .handoff_reads import HandoffError, HandoffReads
from .handoff_runtime import HandoffProcess
from .jobs import ApiError, Reply
from .ledger import stamp
from .plan_admission import settings
from .plan_authority import canonical
from .relation_runtime import GateBusy
from .round_runtime import RoundProcess
from .round_store import RoundStore, save_private
from .round_wire import HandoffStatus, RunStatus
from .runtime import Deadlines

KST = timezone(timedelta(hours=9))


class RoundHandoffReads(HandoffReads):
    """Current read grant and native pins are rechecked by the existing read verifier."""
    def __init__(self, config, process, gate, store):
        super().__init__(config, process, gate)
        self.store = store

    def _entry(self, owner, handoff_id, seen):
        grant = self.store.grant(owner, handoff_id)
        if grant is None:
            raise HandoffError(403, "handoff_not_allowed")
        return handoff_access.Entry(owner, handoff_id, grant["manifest_digest"], grant["bundle_digest"])


class RoundService:
    def __init__(self, config, gate, *, online_authority, relation_ledger, log, deadlines=Deadlines(), clock=time.time):
        self.config, self.gate, self.deadlines, self.clock = config, gate, deadlines, clock
        self.authority, self.relation_ledger, self._log = online_authority, relation_ledger, log
        self.profile = config.rounds
        if config.state_dir.stat().st_dev != config.plan_root.stat().st_dev:
            raise ConfigError("ZOOP_AI_SERVICE_ROUND_PROFILE", "round_plan_filesystem_mismatch")
        self.store = RoundStore(config.state_dir, {**self.profile.binding(), "handoffState": str(config.handoff.state_dir),
                                                 "planRoot": str(config.plan_root)})
        self.process = RoundProcess(config, deadlines)
        self._operation = threading.Lock()
        self._wake, self._stop = threading.Event(), threading.Event()
        self._thread = threading.Thread(target=self._loop, name="zoop-ai-round-dispatcher", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                if self.step():
                    continue
            except Exception as error:
                self._log({"event": "round_dispatcher_error", "errorClass": type(error).__name__})
                self._stop.wait(1.0)
            self._wake.wait(0.25)
            self._wake.clear()

    def step(self):
        if not self._operation.acquire(blocking=False):
            return False
        try:
            pending = self.store.pending()
            if pending:
                return self._execute(pending[0], SimpleNamespace(runtime=[]))
            for row in self.store.incomplete():
                try:
                    with self.gate.hold(0):
                        if not self._analysis_complete(row["owner"], plan_verify.decode(row["body"]), SimpleNamespace(runtime=[])):
                            continue
                    return self._execute(row, SimpleNamespace(runtime=[]))
                except GateBusy:
                    return False
                except (ApiError, OSError, ValueError, KeyError, TypeError, sqlite3.Error, plan_verify.InstallError) as error:
                    code = error.code if isinstance(error, ApiError) else "round_outcome_unknown"
                    self.store.save(row, self._failure(row, code))
                    return True
            return False
        finally:
            self._operation.release()

    def _directory(self, owner, round_id):
        parent = self.store.root / hashlib.sha256(owner.encode()).hexdigest()
        parent.mkdir(mode=0o700, exist_ok=True)
        directory = parent / round_id
        directory.mkdir(mode=0o700, exist_ok=True)
        return directory

    def _reader(self, owner, handoff_id):
        grant = self.store.grant(owner, handoff_id)
        if grant is None:
            raise HandoffError(403, "handoff_not_allowed")
        parent = self.store.root / hashlib.sha256(owner.encode()).hexdigest()
        directory = parent / grant["round_id"]
        try:
            for path in (parent, directory):
                info = path.lstat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                    raise HandoffError(503, "service_configuration_invalid")
        except OSError:
            raise HandoffError(503, "service_configuration_invalid") from None
        handoff = replace(self.config.handoff, canonical_path=directory / "canonical.json", decisions_path=directory / "decisions.json",
                          bindings_path=directory / "bindings.json")
        cfg = replace(self.config, handoff=handoff)
        return RoundHandoffReads(cfg, HandoffProcess(cfg, self.deadlines), self.gate, self.store)


    def _slot(self, family, body):
        try:
            slot = datetime.strptime(body["roundId"], "round-%Y%m%dT%H%M").replace(tzinfo=KST)
        except ValueError:
            raise ApiError(422, "invalid_request", field="roundId") from None
        if slot.strftime("round-%Y%m%dT%H%M") != body["roundId"] or slot > datetime.fromtimestamp(self.clock(), KST):
            raise ApiError(422, "invalid_request", field="roundId")
        ordinary = 9 <= slot.hour < 18 and slot.minute in {5, 35}
        carry_only = slot.hour == 18 and slot.minute == 5 and not body.get("planId")
        if family == "handoff" and not (ordinary or carry_only):
            raise ApiError(422, "invalid_request", field="roundId")
        return slot

    def _run_context(self, body):
        slot = self._slot("run", body)
        if not 9 <= slot.hour < 18:
            return {"noWork": "outside_operating_window"}
        if slot.minute not in {5, 35}:
            return {"noWork": "not_due"}
        tick = {"schemaVersion": "zoop-ingestion-s2-1", "sourceId": self.profile.source_id, "scopeId": self.profile.scope_id,
                "now": slot.isoformat()}
        return {"tick": tick, "asOf": stamp(self.clock()), "descriptor": self.profile.descriptor}

    @staticmethod
    def _failure(row, code):
        return {"schemaVersion": row["result"]["schemaVersion"], "roundId": row["round_id"], "state": "failed", "code": code}

    def _outcome(self, row, outcome, seen, command):
        seen.runtime.append({"command": command, "kind": outcome.kind, "exit": outcome.exit_code, "code": outcome.code})
        if outcome.kind not in {"result", "error"}:
            self.store.save(row, self._failure(row, "runtime_unavailable" if outcome.kind == "unavailable" and not outcome.started else "round_outcome_unknown"))
            return None
        return outcome.result

    def _inventory(self, row, seen, *, limit, after=None, revision=None):
        request = {"schemaVersion": "zoop-ingestion-round-inventory-1", "sourceId": self.profile.source_id,
                   "scopeId": self.profile.scope_id, "asOf": row["context"]["asOf"],
                   "maxAgeSeconds": self.profile.max_age_seconds, "limit": limit, "after": after, "checkpointRevision": revision}
        outcome = self.process.inventory(request)
        native = self._outcome(row, outcome, seen, "round-inventory")
        if native is None:
            return None
        if outcome.kind == "error":
            self.store.save(row, self._failure(row, outcome.code))
            return None
        if any(native.get(key) != request[key] for key in ("schemaVersion", "sourceId", "scopeId", "asOf", "maxAgeSeconds")) \
                or set(native) != {"schemaVersion", "sourceId", "scopeId", "asOf", "maxAgeSeconds", "checkpoint", "observations", "next"} \
                or set(native["checkpoint"]) != {"revision", "through"} \
                or type(native["checkpoint"]["revision"]) is not int or native["checkpoint"]["revision"] < 0 \
                or revision is not None and native["checkpoint"]["revision"] != revision \
                or not isinstance(native["observations"], list) or len(native["observations"]) > limit:
            raise ApiError(500, "runtime_binding_mismatch")
        if native["checkpoint"]["through"] is not None:
            if datetime.fromisoformat(native["checkpoint"]["through"]).tzinfo is None:
                raise ApiError(500, "runtime_binding_mismatch")
        return native

    def _working_selection(self, row, seen):
        """Page durable native candidates; permanent claims are queried, never serialized as lifetime history."""
        from .observation_wire import ObservationExportRequest
        selected, after, revision = [], None, None
        snapshot = {member["observation"]["documentVersion"] for event in self.profile.descriptor["snapshot"]["events"]
                    for member in event["members"]}
        previous = None
        while True:
            native = self._inventory(row, seen, limit=64, after=after, revision=revision)
            if native is None:
                return None
            revision = native["checkpoint"]["revision"]
            refs = []
            for item in native["observations"]:
                if set(item) != {"slot", "observation"}:
                    raise ApiError(500, "runtime_binding_mismatch")
                ref = item["observation"]
                parsed = ObservationExportRequest.model_validate({"schemaVersion": "zoop-ingestion-s2-1", **ref})
                when = datetime.fromisoformat(item["slot"])
                order = (when, parsed.round_id, parsed.page, parsed.ordinal)
                age = (datetime.fromisoformat(row["context"]["asOf"]) - when).total_seconds()
                if parsed.source_id != self.profile.source_id or previous is not None and order <= previous \
                        or age < 0 or age > self.profile.max_age_seconds:
                    raise ApiError(500, "runtime_binding_mismatch")
                previous = order
                refs.append(ref)
            following = native["next"]
            if following is not None:
                if not refs or following != {"slot": native["observations"][-1]["slot"], "roundId": refs[-1]["roundId"],
                                             "page": refs[-1]["page"], "ordinal": refs[-1]["ordinal"]}:
                    raise ApiError(500, "runtime_binding_mismatch")
            claimed = self.store.claimed(refs)
            exhausted = following is None
            for index, ref in enumerate(refs):
                if canonical(ref) not in claimed and ref["documentVersion"] not in snapshot:
                    selected.append(ref)
                    if len(selected) == self.profile.limit:
                        exhausted = exhausted and index == len(refs) - 1
                        break
            if len(selected) == self.profile.limit or following is None:
                row["context"]["inventory"] = {"checkpoint": native["checkpoint"], "exhausted": exhausted}
                return {"schemaVersion": "zoop-extraction-round-selection-2", "asOf": row["context"]["asOf"],
                        "maxAgeSeconds": self.profile.max_age_seconds, "limit": self.profile.limit,
                        "cadenceMinutes": 30, "observations": selected}
            after = following

    def _plan(self, row, seen):
        if "noWork" in row["context"]:
            self.store.save(row, {"schemaVersion": "zoop-ai-round-run-1", "roundId": row["round_id"],
                                  "state": "no_new_material", "code": row["context"]["noWork"]})
            return
        checkpoint = self._inventory(row, seen, limit=0)
        if checkpoint is None:
            return
        row["context"]["checkpointBeforeTick"] = checkpoint["checkpoint"]
        if checkpoint["checkpoint"]["through"] is None:
            row["context"]["tick"]["initialFrom"] = self.profile.initial_from
        self.store.save(row, row["result"])
        directory = self._directory(row["owner"], row["round_id"])
        fixture = directory / "ingestion-manifest.json"
        save_private(fixture, plan_verify.read_file(self.profile.fixture_manifest, 2_000_000))
        outcome = self.process.tick(row["context"]["tick"], fixture)
        native = self._outcome(row, outcome, seen, "tick")
        if native is None:
            return
        if outcome.kind == "error":
            self.store.save(row, self._failure(row, outcome.code))
            return
        tick, ingestion = native["tick"], native["round"]
        if ingestion is None or ingestion["state"] != "complete" or not tick["roundId"]:
            self.store.save(row, self._failure(row, "ingestion_incomplete"))
            return
        ingestion_id = tick["roundId"]
        row["context"].update(ingestionRoundId=ingestion_id, tickComplete=True)
        self.store.save(row, row["result"])
        selection = self._working_selection(row, seen)
        if selection is None:
            return
        row["context"]["selection"] = selection
        self.store.save(row, row["result"])
        save_private(directory / "selection.json", canonical(selection).encode())
        descriptor = {**row["context"]["descriptor"], "enqueueId": row["round_id"], "roundId": ingestion_id, "sourceId": self.profile.source_id}
        stage = self.config.plan_root / (".round-stage-" + hashlib.sha256(
            (row["owner"] + "\0" + row["round_id"]).encode()).hexdigest())
        outcome = self.process.plan(row["owner"], descriptor, directory / "selection.json", stage)
        native = self._outcome(row, outcome, seen, "plan-round")
        if native is None:
            return
        if outcome.kind == "error":
            if outcome.code == "plan_has_no_units":
                detail = native["error"].get("detail", {})
                row["context"]["carryover"] = detail.get("carryover", [])
                self.store.save(row, {"schemaVersion": "zoop-ai-round-run-1", "roundId": row["round_id"], "state": "no_new_material",
                                      "ingestionRoundId": ingestion_id, "code": "plan_has_no_units"})
            else:
                self.store.save(row, self._failure(row, outcome.code))
            return
        plan_id, plan_digest = native["planId"], native["planDigest"]
        status = RunStatus.model_validate({"roundId": row["round_id"], "state": "ready", "ingestionRoundId": ingestion_id,
                                          "planId": plan_id, "planDigest": plan_digest, "observedAt": stamp(self.clock())}).wire()
        target = self.config.plan_root / plan_id
        if os.path.lexists(target):
            raise ApiError(409, "round_plan_conflict")
        files, manifest, receipt = plan_verify.plan_files(stage, settings(self.config))
        if (receipt["planId"], receipt["planDigest"], manifest["round"]["roundId"], manifest["principal"]) != (
                plan_id, plan_digest, ingestion_id, row["owner"]):
            raise ApiError(500, "runtime_binding_mismatch")
        plan_verify.verify_plan(stage, settings(self.config), files, manifest, receipt)
        approvals = plan_verify.decode(files["approvals.json"])["approvals"]
        self.store.claim_observations(row, [item["request"]["incoming"] for item in approvals], manifest["carryover"])
        os.rename(stage, target)
        fd = os.open(self.config.plan_root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        self.store.save(row, status)

    def _check_handoff_binding(self, owner, body):
        run = self.store.get(owner, "run", body["roundId"])
        if run is None:
            if body.get("ingestionRoundId") is not None or body.get("planId") is not None:
                raise ApiError(409, "round_binding_mismatch")
            return
        status = run["result"]
        if status["state"] not in {"ready", "no_new_material"}:
            raise ApiError(409, "analysis_incomplete", retry_after=1)
        if (body.get("ingestionRoundId"), body.get("planId")) != (status.get("ingestionRoundId"), status.get("planId")):
            raise ApiError(409, "round_binding_mismatch")

    def _analysis_registered(self, owner, body):
        if not body.get("planId"):
            return True
        run = self.store.get(owner, "run", body["roundId"])["result"]
        admitted = self.authority.find(owner, body["planId"], run["planDigest"])
        if admitted is None:
            return False
        for unit in admitted["manifest"]["units"]:
            submission = unit["relationSubmit"]
            job = self.relation_ledger.job(submission["jobId"])
            if job is None:
                return False
            upstream = submission["upstream"]
            if (job.owner, job.authority_ref, job.upstream_job_id, job.upstream_input_digest) != (
                    owner, admitted["admissionId"], upstream["jobId"], upstream["inputDigest"]):
                raise ApiError(500, "runtime_binding_mismatch")
            if job.state != "accepted":
                return False
            dispatch = self.relation_ledger.dispatch(job.job_id)
            if dispatch is None:
                raise ApiError(500, "runtime_binding_mismatch")
            if dispatch.state != "idle":
                return False
        return True

    def _analysis_complete(self, owner, body, seen):
        if not self._analysis_registered(owner, body):
            return False
        outcome = self.process.completion(body)
        seen.runtime.append({"command": "check-round", "kind": outcome.kind, "exit": outcome.exit_code, "code": outcome.code})
        if outcome.kind == "error" and outcome.code == "analysis_incomplete":
            return False
        if outcome.kind == "error":
            raise ApiError(409, outcome.code)
        if outcome.kind != "result":
            raise ApiError(503, "runtime_unavailable")
        if outcome.result != {"schemaVersion": "zoop-ai-handoff-1", "roundId": body.get("ingestionRoundId") or body["roundId"], "state": "complete"}:
            raise ApiError(500, "runtime_binding_mismatch")
        return True

    def _freeze(self, row, seen):
        body = plan_verify.decode(row["body"])
        if not self._analysis_complete(row["owner"], body, seen):
            self.store.save(row, {"schemaVersion": "zoop-ai-round-handoff-1", "roundId": row["round_id"],
                                 "state": "analysis_incomplete", "code": "analysis_incomplete"})
            return
        directory = self._directory(row["owner"], row["round_id"])
        save_private(directory / "bindings.json", canonical(body["bindings"]).encode())
        outcome = self.process.freeze(body, directory)
        native = self._outcome(row, outcome, seen, "freeze-round")
        if native is None:
            return
        if outcome.kind == "error":
            code = outcome.code
            state = "analysis_incomplete" if code == "analysis_incomplete" else "no_public_material" if code == "window_empty" else "failed"
            result = {"schemaVersion": "zoop-ai-round-handoff-1", "roundId": row["round_id"], "state": state, "code": code}
            if code == "window_empty":
                result["selection"] = native["error"]["detail"]["selection"]
            self.store.save(row, self._bounded_result(row, result))
            return
        if native["roundId"] != (body.get("ingestionRoundId") or body["roundId"]):
            raise ApiError(500, "runtime_binding_mismatch")
        frozen = native["freeze"]
        if frozen["state"] != "ready":
            self.store.save(row, self._failure(row, "handoff_not_ready"))
            return
        receipt = frozen["receipt"]
        result = {"schemaVersion": "zoop-ai-round-handoff-1", "roundId": row["round_id"], "state": "ready", "handoffId": native["handoffId"],
                  "manifestDigest": receipt["manifestDigest"], "bundleDigest": receipt["bundleDigest"], "selection": native["selection"]}
        HandoffStatus.model_validate({**result, "observedAt": stamp(self.clock())})
        if receipt["handoffId"] != result["handoffId"] or not result["handoffId"].startswith("hr-"):
            raise ApiError(500, "runtime_binding_mismatch")
        result = self._bounded_result(row, result)
        self.store.save(row, result, grant=result["state"] == "ready")

    @staticmethod
    def _bounded_result(row, result):
        if len(canonical(result).encode()) > 2_000_000:
            row["context"]["selection"] = result.get("selection")
            return RoundService._failure(row, "round_response_too_large")
        return result

    def _execute(self, row, seen):
        try:
            with self.gate.hold(0):
                context = self._run_context(plan_verify.decode(row["body"])) if row["family"] == "run" else None
                claimed = self.store.claim(row, context)
                if claimed is None:
                    return False
                row = claimed
                (self._plan if row["family"] == "run" else self._freeze)(row, seen)
                return True
        except GateBusy:
            return False
        except ApiError as error:
            if row["result"]["state"] == "running" and row["context"].get("started"):
                self.store.save(row, self._failure(row, error.code))
                return True
            return False
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, plan_verify.InstallError):
            if row["result"]["state"] == "running":
                self.store.save(row, self._failure(row, "round_outcome_unknown"))
            return True

    def submit(self, owner, family, body, raw, seen):
        round_id = body["roundId"]
        old = self.store.get(owner, family, round_id)
        if old is not None:
            if old["body"] != raw:
                raise ApiError(409, "request_conflict")
            return self.status(owner, family, round_id, seen)
        self._slot(family, body)

        def preflight():
            if family == "handoff":
                self._check_handoff_binding(owner, body)
                try:
                    with self.gate.hold(0):
                        if not self._analysis_complete(owner, body, seen):
                            raise ApiError(409, "analysis_incomplete", retry_after=1)
                except GateBusy:
                    raise ApiError(409, "round_busy", retry_after=1) from None

        created, row = self.store.reserve(owner, family, round_id, raw, {"started": False}, preflight=preflight)
        if created:
            self._wake.set()
        reply = self.status(owner, family, round_id, seen)
        return Reply(202 if created else 200, reply.body, reply.headers)

    def status(self, owner, family, round_id, seen):
        row = self.store.get(owner, family, round_id)
        if row is None:
            raise ApiError(404, "round_not_found")
        result = row["result"]
        if result["state"] == "ready":
            if family == "handoff":
                reader = self._reader(owner, result["handoffId"])
                current = reader.status(owner, result["handoffId"], seen).body
                if current.delivery.state != "current":
                    result = self._failure(row, current.delivery.reason or "handoff_not_ready")
            else:
                target = self.config.plan_root / result["planId"]
                try:
                    files, manifest, receipt = plan_verify.plan_files(target, settings(self.config))
                    if (receipt["planId"], receipt["planDigest"], manifest["principal"], manifest["round"]["roundId"]) != (
                            result["planId"], result["planDigest"], owner, result["ingestionRoundId"]):
                        raise ApiError(500, "runtime_binding_mismatch")
                    plan_verify.verify_plan(target, settings(self.config), files, manifest, receipt)
                except plan_verify.InstallError:
                    raise ApiError(503, "plan_verifier_unavailable") from None
        model = RunStatus if family == "run" else HandoffStatus
        return Reply(200, model.model_validate({**result, "observedAt": stamp(self.clock())}),
                     {"Location": f"/internal/v1/round-{'runs' if family == 'run' else 'handoffs'}/{round_id}"})


class HandoffRouter:
    """Keep static archive delivery separate from grants created by the round profile."""
    def __init__(self, static, rounds):
        self.static, self.rounds = static, rounds

    def status(self, owner, handoff_id, seen):
        reader = self.rounds._reader(owner, handoff_id) if self.rounds.store.owns(handoff_id) else self.static
        return reader.status(owner, handoff_id, seen)

    def bundle(self, owner, handoff_id, seen):
        reader = self.rounds._reader(owner, handoff_id) if self.rounds.store.owns(handoff_id) else self.static
        return reader.bundle(owner, handoff_id, seen)
