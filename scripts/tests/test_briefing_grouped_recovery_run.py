import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("recovery_run", Path(__file__).parents[1] / "briefing_grouped_recovery_run.py")
run = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(run)


class ItemIsolationTest(unittest.TestCase):
    def entry(self, issue, status):
        return {"issueId": issue, "status": status, "originalRank": 2,
            "selection": {"issueId": issue, "rank": 1},
            "draft": {"issueId": issue, "rank": 1, "title": "유지할 제목", "claims": [{"text": "유지할 문장"}]},
            "draftOrigin": "base", "draftSourceRequestDigest": "old-generation",
            "verificationOrigin": "base", "verificationRequestDigest": "old-verification",
            "verification": {"status": "PASS", "checks": [{"targetId": issue + ":title", "verdict": "SUPPORTED"}]},
            "errors": []}

    def test_repair_input_excludes_successful_sibling(self):
        good = self.entry("good", "NEEDS_VERIFICATION")
        bad = self.entry("bad", "NEEDS_DRAFT"); bad["draft"] = None
        calls = []
        def generate(client, selections, context, prior_failures=None):
            calls.append(("generate", [s["issueId"] for s in selections]))
            self.assertIn("codes", prior_failures["bad"])
            if len(calls) > 1:
                self.assertEqual(prior_failures["bad"]["codes"], ["insufficient_support"])
            return {"requestDigest": "gen", "items": [self.entry("bad", "PASS")["draft"]], "failures": {}}
        def verify(client, selections, drafts, context):
            ids = [s["issueId"] for s in selections]; calls.append(("verify", ids))
            return {"requestDigest": "verify" + str(len(calls)), "checks": [],
                "perIssueStatuses": {i: "PASS" if i == "good" else "WITHHELD" for i in ids},
                "failures": {"bad": "insufficient_support"}}
        record = {"date": "2026-10-08", "edition": "evening", "window": {}, "identitySha256": "sha",
                  "selectionStatus": "HELD_VALIDATION"}
        layer = {k: "sha" for k in ("runId", "sourceFileSha256", "clockFileSha256", "groupArchiveSha256", "baseBundleSha256")}
        with tempfile.TemporaryDirectory() as directory, patch.object(run.recovery, "generate_items", generate), \
                patch.object(run.recovery, "verify_items", verify):
            items = run.stage_facts(None, Path(directory), layer, record, [good, bad], 1)
        self.assertEqual(calls, [("generate", ["bad"]), ("verify", ["good", "bad"]),
                                 ("generate", ["bad"]), ("verify", ["bad"])])
        self.assertEqual(items[0]["status"], "FACT_PASS")
        self.assertEqual(items[0]["draft"], good["draft"])
        self.assertEqual(good["status"], "NEEDS_VERIFICATION")

    def test_existing_pass_never_enters_generation_or_verification(self):
        good = self.entry("good", "FACT_PASS")
        with tempfile.TemporaryDirectory() as directory, patch.object(run.recovery, "generate_items") as gen, \
                patch.object(run.recovery, "verify_items") as verify:
            actual = run.stage_facts(None, Path(directory), {}, {"selectionStatus": "SELECTED"}, [good], 1)
            self.assertEqual(actual, [good]); gen.assert_not_called(); verify.assert_not_called()

    def test_projection_publishes_only_pass_and_preserves_original_rank(self):
        good, bad = self.entry("good", "PASS"), self.entry("bad", "WITHHELD")
        good["verification"]["checks"][0]["flags"] = {"typeAppropriate": True}
        receipts = [{"requestDigest": k, "finishedAt": "2026-10-20T00:00:00Z"}
                    for k in ("old-generation", "old-verification")]
        selected, result = run.result_projection([bad, good], receipts)
        self.assertEqual([s["issueId"] for s in selected], ["good"])
        self.assertEqual(selected[0]["rank"], 1)
        self.assertEqual(good["originalRank"], 2)
        self.assertTrue(result["verification"]["checks"][0]["typeAppropriate"])
        self.assertIn("flags", good["verification"]["checks"][0])
        self.assertEqual({r["requestDigest"] for r in result["usage"]}, {"old-generation", "old-verification"})

    def test_zero_pass_stays_held_without_empty_success(self):
        selected, result = run.result_projection([self.entry("bad", "WITHHELD")], [])
        self.assertEqual(selected, []); self.assertIsNone(result)

    def test_stage_summary_is_recomputed_from_provider_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stage.json"
            first = run.cached_stage(path, lambda: {"completed": True})
            second = run.cached_stage(path, lambda: {"completed": True})
            self.assertEqual(first, second)
            with self.assertRaisesRegex(run.sim.ReplayError, "recovery_stage_summary_changed"):
                run.cached_stage(path, lambda: {"completed": False})

    def test_cache_only_miss_does_not_reserve_or_transmit(self):
        with tempfile.TemporaryDirectory() as directory:
            client = run.CacheOnlyRecoveryClient(Path(directory), lambda _: self.fail("network was used"), 400)
            with self.assertRaisesRegex(run.sim.ReplayError, "recovery_cache_only_miss"):
                client.call(run.recovery.STAGES["generation"], {"promptArtifacts": run.recovery.prompt_artifacts()},
                            "generation.md", "generation.schema.json")
            self.assertEqual(list(client.calls.glob("*.pending.json")), [])


class RecoveryProcessBudgetTest(unittest.TestCase):
    def test_two_processes_cannot_both_reserve_the_last_shared_slot(self):
        import multiprocessing
        import os
        from types import SimpleNamespace
        ctx = multiprocessing.get_context('fork')
        ready, release, results = ctx.Event(), ctx.Event(), ctx.Queue()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'out'
            args = SimpleNamespace(output=str(output), base_bundle=str(Path(directory)/'base/bundle.json'), execute_authorized=True)
            class Client(run.base.ResponsesClient):
                def request(self, stage, data, prompt_name, schema_name, max_output=8, schema_override=None):
                    schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
                    raw=run.base.canonical({'model':run.base.MODEL,'store':False,'instructions':'authored budget test','input':run.base.canonical(data).decode(),
                        'max_output_tokens':8,'text':{'format':{'name':stage,'type':'json_schema','strict':True,'schema':schema}}})
                    return raw,schema,run.base.digest(b'authored budget test')
            def work(*_):
                original=run.base.write_once
                def boundary(path, data):
                    if path.name.endswith('.pending.json'):
                        ready.set()
                        if not release.wait(5):raise AssertionError('authored boundary release timeout')
                    return original(path,data)
                def transport(raw):
                    results.put('provider')
                    return 200,run.base.canonical({'id':'authored-response','status':'completed','usage':{'input_tokens':1,'output_tokens':1},
                        'output':[{'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}]})
                with patch.object(run.base,'write_once',boundary):
                    client=Client(output,transport,max_calls=1)
                    return client.call('authored_budget',{'process':os.getpid()},'unused','unused',max_output=8)
            def worker():
                try:run.run(args);results.put('completed')
                except Exception as error:results.put(str(error))
            with patch.object(run,'_run',work):
                first=ctx.Process(target=worker);second=ctx.Process(target=worker)
                try:
                    first.start();self.assertTrue(ready.wait(5))
                    self.assertEqual([],list((output/'calls').glob('*.pending.json')))
                    second.start();self.assertEqual('recovery_execution_locked',results.get(timeout=3))
                    self.assertTrue((output/'.recovery-execution.lock').exists())
                    release.set();first.join(5);second.join(5)
                    self.assertEqual(0,first.exitcode);self.assertEqual(0,second.exitcode)
                    self.assertEqual({'provider','completed'},{results.get(timeout=2),results.get(timeout=2)})
                    self.assertEqual(1,len(list((output/'calls').glob('*.pending.json'))))
                    self.assertFalse((output/'.recovery-execution.lock').exists())
                finally:
                    release.set()
                    for child in (first,second):
                        if child.pid and child.is_alive():child.terminate();child.join()


if __name__ == "__main__":
    unittest.main()
