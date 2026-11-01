"""Bounded native tick, plan, completion and freeze commands; S2/S3 retain model admission."""
from __future__ import annotations

import json

from .handoff_runtime import canonical, _duplicate_free, _no_constant
from .runtime import CODE, Deadlines, Outcome, WorkerProcess


def interpret(schema, code, raw):
    if code not in (0, 2, 3):
        return Outcome("abnormal", exit_code=code, started=True)
    try:
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_duplicate_free, parse_constant=_no_constant)
        expected = ({"zoop-extraction-service-plan-receipt-1": "zoop-extraction-s2-2",
                     "zoop-ingestion-round-inventory-1": "zoop-ingestion-s2-1"}.get(schema, schema) if code == 2 else schema)
        if canonical(value) != text.removesuffix("\n") or value.get("schemaVersion") != expected:
            raise ValueError("native wire")
        if "error" in value:
            name = value["error"]["code"]
            if code != 2 or not isinstance(name, str) or not CODE.fullmatch(name):
                raise ValueError("native error")
            return Outcome("error", result=value, code=name, exit_code=code, started=True)
        if code == 2:
            raise ValueError("native error missing")
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError):
        return Outcome("abnormal", exit_code=code, started=True)
    return Outcome("result", result=value, exit_code=code, started=True)


class RoundProcess:
    def __init__(self, config, deadlines=Deadlines()):
        self.config, self.deadlines = config, deadlines
        self.runner = WorkerProcess(config, deadlines, env=config.extraction.child_env)

    def call(self, argv, body, schema, *, env=None):
        return self.runner.execute(argv, body, self.deadlines.quick, env=env,
                                   interpret=lambda code, raw: interpret(schema, code, raw))

    def tick(self, body, fixture):
        cfg, extraction = self.config.rounds, self.config.extraction
        return self.call([str(cfg.ingestion_command), "tick", "--state-dir", str(extraction.ingestion_state_dir),
                          "--sources", str(extraction.sources_path), "--fixture-manifest", str(fixture)], body, "zoop-ingestion-s2-1")

    def inventory(self, body):
        cfg, extraction = self.config.rounds, self.config.extraction
        return self.call([str(cfg.ingestion_command), "round-inventory", "--state-dir", str(extraction.ingestion_state_dir),
                          "--sources", str(extraction.sources_path)], body, "zoop-ingestion-round-inventory-1")

    def plan(self, owner, body, selection, output):
        e = self.config.extraction
        argv = [str(e.command), "plan-round", "--ingestion-state-dir", str(e.ingestion_state_dir), "--sources", str(e.sources_path),
                "--principal", owner, "--selection", str(selection), "--output", str(output)]
        env = dict(e.child_env)
        if body["provenance"]["executionMode"] == "replay":
            argv += ["--replay", str(e.producer_replay)]
            if body["topic"] is not None:
                argv += ["--topic-replay", str(e.topic_replay)]
        elif self.config.pipeline_live is not None:
            env.update(self.config.pipeline_live.public)
            env.update(self.config.pipeline_live.budget)
        return self.call(argv, body, "zoop-extraction-service-plan-receipt-1", env=env)

    def _handoff_args(self, command, body):
        h = self.config.handoff
        argv = [str(h.command), command, "--state-dir", str(h.state_dir), "--relation-state-dir", str(h.relation_state_dir),
                "--extraction-state-dir", str(h.extraction_state_dir), "--ingestion-state-dir", str(h.ingestion_state_dir),
                "--sources", str(h.sources_path), "--canonical", str(h.canonical_path),
                "--round-id", body.get("ingestionRoundId") or body["roundId"]]
        if body.get("planId"):
            argv += ["--plan-root", str(self.config.plan_root), "--plan-id", body["planId"]]
        return argv

    def completion(self, body):
        return self.call(self._handoff_args("check-round", body), {}, "zoop-ai-handoff-1")

    def freeze(self, body, files):
        argv = self._handoff_args("freeze-round", body)
        argv += ["--decisions", str(self.config.handoff.decisions_path), "--bindings", str(files / "bindings.json"), "--files-dir", str(files)]
        return self.call(argv, {}, "zoop-ai-handoff-1")
