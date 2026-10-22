import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import briefing_round_series as series


class SeriesBoundaryTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'series.json'
        self.value={'schemaVersion':series.SCHEMA,'retrospectiveBodies':True,'productionAuthorized':False,
            'sourceFileSha256':'a'*64,'rounds':[]}
        for day,edition,start,end in [('2026-10-21','evening','2026-10-21T09:20:00+09:00','2026-10-21T17:30:00+09:00'),
            ('2026-10-22','morning','2026-10-21T17:30:00+09:00','2026-10-22T09:20:00+09:00'),
            ('2026-10-22','evening','2026-10-22T09:20:00+09:00','2026-10-22T17:30:00+09:00')]:
            self.value['rounds'].append({'date':day,'edition':edition,'window':{'from':start,'to':end,'openStart':False}})
    def load(self,v):
        self.path.write_text(json.dumps(v));return series.load(self.path,'a'*64)
    def test_three_contiguous_editions_and_source_binding(self):
        self.assertEqual(len(self.load(self.value)['rounds']),3)
        changed=copy.deepcopy(self.value);changed['sourceFileSha256']='b'*64
        with self.assertRaises(series.base.ReplayError):self.load(changed)
    def test_gap_overlap_nonstandard_time_and_backdated_live_claim_rejected(self):
        for field,value in [('from','2026-10-22T08:00:00+09:00'),('to','2026-10-22T09:25:00+09:00')]:
            changed=copy.deepcopy(self.value);changed['rounds'][1]['window'][field]=value
            with self.assertRaises(series.base.ReplayError):self.load(changed)
        changed=copy.deepcopy(self.value);changed['retrospectiveBodies']=False
        with self.assertRaises(series.base.ReplayError):self.load(changed)
    def test_old_default_stays_fourteen_rounds(self):
        import briefing_round_simulation as simulation
        self.assertEqual(len(simulation.windows()),14)

class SeriesGenerationControlTest(unittest.TestCase):
    def test_one_available_and_two_empty_rounds_keep_order_and_reuse(self):
        import contextlib
        import io
        sys.path.insert(0,str(Path(__file__).parent))
        import test_briefing_local_round as controls
        fixture=controls.fixture_module.GroupedRunTest();fixture.setUp()
        try:
            args,_=controls.prepare(fixture);args.round_spec=None
            spec={'schemaVersion':series.SCHEMA,'retrospectiveBodies':True,'productionAuthorized':False,
                'sourceFileSha256':controls.base.digest(fixture.clock.sources.read_bytes()),'rounds':controls.run.sim.windows()[:3]}
            path=fixture.root/'series.json';path.write_bytes(controls.base.canonical(spec));args.round_series=str(path)
            with contextlib.redirect_stdout(io.StringIO()):
                result=controls.run.run(args,controls.fixture_module.fixtures.AuthoredTransport())
            bundle=fixture.bundle();self.assertEqual(len(bundle['rounds']),3)
            self.assertEqual([r['edition'] for r in bundle['rounds']],['morning','evening','morning'])
            self.assertEqual(result['selectedRounds'],1);self.assertTrue(bundle['retrospectiveBodies'])
            self.assertEqual(bundle['rounds'][0]['identity']['baseline']['from'],spec['rounds'][0]['window']['from'])
            with contextlib.redirect_stdout(io.StringIO()):
                again=controls.run.run(args,lambda _:self.fail('completed request sent twice'))
            self.assertEqual(again['newPaidCalls'],0)
        finally:fixture.tearDown()
