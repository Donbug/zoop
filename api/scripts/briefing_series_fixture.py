#!/usr/bin/env python3
"""Authored three-round sequence with one published and two source-empty controls."""
import importlib.util
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('series_fixture_tests',ROOT/'scripts/tests/test_briefing_local_round.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
f=m.fixture_module.GroupedRunTest();f.setUp()
try:
 args,_=m.prepare(f,Path(sys.argv[1]));args.round_spec=None
 value={'schemaVersion':'zoop-briefing-round-series-v1','sourceFileSha256':m.base.digest(f.clock.sources.read_bytes()),
     'retrospectiveBodies':True,'productionAuthorized':False,'rounds':m.run.sim.windows()[:3]}
 path=f.root/'series.json';path.write_bytes(m.base.canonical(value));args.round_series=str(path)
 result=m.run.run(args,m.fixture_module.fixtures.AuthoredTransport())
 assert result['selectedRounds']==1 and len(f.bundle()['rounds'])==3
 print(result)
finally:f.tearDown()
