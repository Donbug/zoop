#!/usr/bin/env python3
"""Authored single local round fixture. No key, network or real provider."""
import importlib.util
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
spec=importlib.util.spec_from_file_location('local_fixture_tests',ROOT/'scripts/tests/test_briefing_local_round.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
f=m.fixture_module.GroupedRunTest();f.setUp()
try:
 args,_=m.prepare(f,Path(sys.argv[1]))
 result=m.run.run(args,m.fixture_module.fixtures.AuthoredTransport())
 assert result['selectedRounds']==1
 print(result)
finally:f.tearDown()
