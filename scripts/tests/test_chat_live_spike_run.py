from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("chat_live_spike_run", ROOT / "scripts" / "chat_live_spike_run.py")
assert SPEC and SPEC.loader
spike = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = spike
SPEC.loader.exec_module(spike)

BASE = {"schemaVersion": "zoop-chat-live-spike-manifest-1", "candidateCommit": "a" * 40, "approvedBy": "role",
        "approvalRef": "AI-1", "environment": "stage", "policyVersion": "p", "pricing": {}}
SET = {"schemaVersion": "x", "scenarios": {
    "a": {"question": "질문 A", "inGraph": ["삼성전자"]},
    "b": {"question": "질문 B", "notInGraph": ["카카오"]}}}


class Server:
    """The chat API as the runner uses it: one scripted job status list per submitted question."""

    def __init__(self, submit: list[tuple[int, str | None]] | None = None) -> None:
        self.submit = submit or []
        self.jobs: list[str] = []
        self.questions: list[str] = []
        self.statuses: dict[str, list[str]] = {}

    def client(self) -> spike.Client:
        client = spike.Client("https://server.example", "https://web.example")
        client.call = self.call
        return client

    def call(self, method, path, body=None, headers=None):
        if method == "PUT":
            return 200, {"id": path.rsplit("/", 1)[1]}
        if method == "POST":
            status, state = self.submit.pop(0) if self.submit else (202, "queued")
            if status == 0:
                raise OSError("connection reset")
            self.jobs.append(body["jobId"])
            self.questions.append(body["question"])
            assert headers["Idempotency-Key"] == body["jobId"]
            self.statuses[body["jobId"]] = ["running", "completed"]
            return status, {"status": state}
        return 200, {"status": self.statuses[path.rsplit("/", 1)[1]].pop(0)}


class Clock:
    def __init__(self) -> None:
        self.at = 0.0

    def now(self) -> float:
        return self.at

    def sleep(self, seconds: float) -> None:
        self.at += seconds


class RunTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)
        self.manifest = self.dir / "manifest.json"
        self.set = self.dir / "scenarios.json"
        self.set.write_text(json.dumps(SET, ensure_ascii=False), encoding="utf-8")
        self.clock = Clock()

    def run_spike(self, server: Server, names: list[str], repeat: int, max_runs: int):
        return spike.run(server.client(), self.manifest, BASE, names, repeat, max_runs, sleep=self.clock.sleep,
                         now=self.clock.now, path=self.set)

    def test_every_scenario_runs_its_count_and_the_manifest_names_each_job(self) -> None:
        server = Server()
        manifest = self.run_spike(server, ["a", "b"], 2, 4)
        self.assertEqual(["a", "a", "b", "b"], [r["scenario"] for r in manifest["runs"]])
        self.assertEqual(server.jobs, [r["jobId"] for r in manifest["runs"]])
        self.assertEqual(["질문 A", "질문 A", "질문 B", "질문 B"], server.questions)
        self.assertEqual(manifest, json.loads(self.manifest.read_text(encoding="utf-8")))
        self.assertEqual(BASE["candidateCommit"], manifest["candidateCommit"])

    def test_the_cap_stops_before_a_question_is_sent_and_counts_earlier_runs(self) -> None:
        self.run_spike(Server(), ["a"], 2, 2)
        server = Server()
        with self.assertRaisesRegex(spike.SpikeError, "max-runs"):
            self.run_spike(server, ["a", "b"], 2, 2)
        self.assertEqual([], server.jobs)

    def test_a_resumed_run_sends_only_what_is_missing(self) -> None:
        self.run_spike(Server(), ["a"], 1, 5)
        server = Server()
        self.run_spike(server, ["a"], 2, 5)
        self.assertEqual(1, len(server.jobs))

    def test_a_failed_job_stays_a_run_and_is_not_sent_again(self) -> None:
        server = Server([(202, "failed")])
        manifest = self.run_spike(server, ["a"], 1, 5)
        self.assertEqual(1, len(server.jobs))
        self.assertEqual(1, len(manifest["runs"]))

    def test_a_submission_of_unknown_fate_stops_everything(self) -> None:
        for fate in [(0, None), (503, None)]:
            server = Server([fate])
            with self.assertRaises(spike.Unsure):
                self.run_spike(server, ["a", "b"], 1, 5)
            self.assertEqual(1 if fate[0] else 0, len(server.jobs), "nothing more is sent")

    def test_a_job_that_never_ends_stops_instead_of_waiting_on(self) -> None:
        server = Server()
        client = server.client()
        original = client.call
        client.call = lambda m, p, b=None, h=None: (200, {"status": "running"}) if m == "GET" else original(m, p, b, h)
        with self.assertRaises(spike.Unsure):
            spike.run(client, self.manifest, BASE, ["a"], 1, 5, wait=3, sleep=self.clock.sleep, now=self.clock.now, path=self.set)

    def test_an_unknown_scenario_sends_nothing(self) -> None:
        server = Server()
        with self.assertRaisesRegex(spike.SpikeError, "unknown"):
            self.run_spike(server, ["z"], 1, 5)
        self.assertEqual([], server.jobs)

    def test_a_run_needs_the_approval_flag_before_anything_is_sent(self) -> None:
        base = self.dir / "base.json"
        base.write_text(json.dumps(BASE), encoding="utf-8")
        out = io.StringIO()
        sys.stdout, saved = out, sys.stdout
        try:
            code = spike.main(["--base-url", "http://127.0.0.1:1", "--origin", "https://w", "run", "--base-manifest", str(base),
                               "--manifest", str(self.manifest), "--max-runs", "20"])
        finally:
            sys.stdout = saved
        self.assertEqual(2, code)
        self.assertIn("paid", out.getvalue())
        self.assertFalse(self.manifest.exists())


class PreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.set = Path(folder.name) / "scenarios.json"
        self.set.write_text(json.dumps(SET, ensure_ascii=False), encoding="utf-8")
        self.env = {"ZOOP_SPIKE_EMAIL": "m@example.com", "ZOOP_SPIKE_PASSWORD": "pw"}

    @staticmethod
    def bearer(request, timeout=0):
        headers = Message()
        headers["WWW-Authenticate"] = "Bearer"
        raise urllib.error.HTTPError(request.full_url, 401, "no", headers, io.BytesIO())

    def client(self, companies: list[str], completed: bool = True) -> spike.Client:
        nodes = [{"kind": "company", "label": c} for c in companies] + [{"kind": "issue", "label": "사건"}]

        def call(method, path, body=None, headers=None):
            if method == "GET":
                return 200, {"nodes": nodes, "metadata": {"graphVersion": "gv"}}
            return 200, {"csrfToken": "c", "setup": {"completed": completed}}

        client = spike.Client("https://server.example", "https://web.example")
        client.call = call
        return client

    def problems(self, client: spike.Client, opener=None) -> list[str]:
        out = io.StringIO()
        sys.stdout, saved = out, sys.stdout
        try:
            return spike.preflight(client, self.env, "https://server.example/mcp", opener or self.bearer, self.set)
        finally:
            sys.stdout = saved

    def test_a_ready_environment_has_no_problems(self) -> None:
        self.assertEqual([], self.problems(self.client(["삼성전자"])))

    def test_it_names_a_missing_company_and_one_that_must_be_absent(self) -> None:
        problems = self.problems(self.client(["카카오"]))
        self.assertEqual(2, len(problems), problems)
        self.assertIn("삼성전자", problems[0])
        self.assertIn("카카오", problems[1])

    def test_an_mcp_without_the_challenge_and_an_unfinished_member_are_problems(self) -> None:
        def open_answer(request, timeout=0):
            raise OSError("refused")

        problems = self.problems(self.client(["삼성전자"], completed=False), open_answer)
        self.assertEqual(2, len(problems), problems)

    def test_nothing_prints_a_credential(self) -> None:
        out = io.StringIO()
        sys.stdout, saved = out, sys.stdout
        try:
            spike.preflight(self.client(["삼성전자"]), self.env, "https://server.example/mcp", self.bearer, self.set)
        finally:
            sys.stdout = saved
        self.assertNotIn("pw", out.getvalue())
        self.assertNotIn("m@example.com", out.getvalue())


if __name__ == "__main__":
    unittest.main()
