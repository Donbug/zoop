"""Single local round boundaries; all provider responses are authored, never paid."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE))
import briefing_local_window as local
spec=importlib.util.spec_from_file_location("local_grouped_fixture",Path(__file__).with_name("test_briefing_grouped_run.py"))
fixture_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture_module)
run=fixture_module.run
base=run.base

def prepare(fixture,directory=None):
    if directory is not None:
        directory=directory.resolve();base.private_dir(directory)
        fixture.root=directory;fixture.archive_path=directory/"archive.json";fixture.output=directory/"output"
        fixture.clock.root=directory;fixture.clock.sources=directory/"sources.jsonl";fixture.clock.clocks=directory/"clocks.json"
        fixture.clock.html=directory/"html";fixture.clock.html.mkdir()
    archive=fixture.prepare(1)
    doc=base.strict_load(fixture.clock.sources.read_bytes().splitlines()[0])
    registry=base.strict_load(fixture.clock.clocks.read_bytes())
    clock=registry["records"][0]
    captured="2026-10-02T09:15:00+09:00"
    doc.update(collectedAt=captured,bodyAcquiredAt=captured,capture={
        "sameResponseBodyAndClock":True,"checkedAt":captured,
        "publishedAt":clock["publishedAt"],"htmlSha256":clock["htmlSha256"]})
    raw=base.canonical(doc)+b"\n";fixture.clock.sources.write_bytes(raw)
    registry["sourceFileSha256"]=base.digest(raw)
    clock.update(sourceFileSha256=base.digest(raw),checkedAt=captured)
    fixture.clock.clocks.write_bytes(base.canonical(registry))
    rows,_,source=run.sim.load_inputs(fixture.clock.sources,fixture.clock.clocks)
    archive.update(sourceFileSha256=source["sourceFileSha256"],clockFileSha256=source["clockFileSha256"])
    archive["documents"]=[{k:v for k,v in rows[0].items() if k!="clockTime"}]
    fixture.archive_path.write_bytes(base.canonical(archive))
    local_round={"date":"2026-10-02","edition":"morning","window":{
        "from":"2026-10-01T17:30:00+09:00","to":"2026-10-02T09:25:00+09:00","openStart":False},
        "localCollection":{"schemaVersion":local.SCHEMA,"manualValidation":True,
            "discoveryTo":"2026-10-02T09:16:00+09:00","sourceFileSha256":source["sourceFileSha256"],
            "collectionPlanSha256":"a"*64,"collectedBeforeCutoff":True,"productionAuthorized":False}}
    path=fixture.root/"round-spec.json";path.write_bytes(base.canonical(local_round))
    catalog=fixture.root/"publication.json"
    catalog.write_bytes(base.canonical({"companies":[{"company_id":"company-authored","name":"합성 기업"}]}))
    args=fixture.args();args.round_spec=str(path);args.publication_catalog=str(catalog)
    return args,local_round

class LocalRoundTest(unittest.TestCase):
    def setUp(self):
        self.fixture=fixture_module.GroupedRunTest();self.fixture.setUp()
    def tearDown(self):self.fixture.tearDown()
    def test_single_local_round_and_completed_reuse(self):
        args,spec=prepare(self.fixture)
        transport=fixture_module.fixtures.AuthoredTransport()
        with contextlib.redirect_stdout(io.StringIO()):result=run.run(args,transport)
        self.assertEqual(1,result["selectedRounds"]);self.assertEqual(3,result["newPaidCalls"])
        bundle=self.fixture.bundle()
        self.assertEqual(local.MODE,bundle["mode"]);self.assertFalse(bundle["retrospectiveBodies"])
        self.assertEqual(spec["localCollection"],bundle["localCollection"])
        self.assertEqual(1,len(bundle["rounds"]))
        request=base.strict_load((self.fixture.output/"calls"/(bundle["rounds"][0]["groupedSelectionRequestDigest"]+".request.json")).read_bytes())
        self.assertFalse(base.strict_load(request["input"])["issues"][0]["historicalSimulation"])
        self.assertTrue(bundle["rounds"][0]["roundId"].startswith("local-"))
        with contextlib.redirect_stdout(io.StringIO()):again=run.run(args,lambda _:self.fail("completed request retransmitted"))
        self.assertEqual(0,again["newPaidCalls"])
    def test_capture_after_cutoff_rejected_before_any_model_call(self):
        args,spec=prepare(self.fixture)
        spec["window"]["to"]="2026-10-02T09:12:00+09:00"
        spec["localCollection"]["discoveryTo"]="2026-10-02T09:11:00+09:00"
        Path(args.round_spec).write_bytes(base.canonical(spec))
        with self.assertRaisesRegex(Exception,"after_cutoff"):
            run.run(args,lambda _:self.fail("late source reached model"))
        self.assertFalse(self.fixture.output.exists())
    def test_source_hash_and_window_bounds_are_required(self):
        args,spec=prepare(self.fixture)
        with self.assertRaisesRegex(Exception,"window_invalid"):
            local.load(args.round_spec,"b"*64)
        spec["window"]["to"]="2999-10-02T09:20:00+09:00"
        Path(args.round_spec).write_bytes(base.canonical(spec))
        with self.assertRaisesRegex(Exception,"window_invalid"):local.load(args.round_spec)

if __name__=="__main__":unittest.main()
