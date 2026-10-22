"""A completed filename is visible only after all bytes are durable; no paid calls."""
import importlib.util
from pathlib import Path
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('atomic_replay',Path(__file__).parents[1]/'briefing_replay.py')
r=importlib.util.module_from_spec(spec); spec.loader.exec_module(r)

class AtomicRecordingTest(unittest.TestCase):
    def test_readers_cannot_see_partial_complete_or_pending_json(self):
        for suffix in ['complete','pending']:
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as d:
                target=Path(d)/('example.'+suffix+'.json'); data=r.canonical({'large':'가'*100000})
                flushed,release=threading.Event(),threading.Event(); original=r.os.fsync
                def pause(fd):
                    original(fd);flushed.set()
                    if not release.wait(5): raise AssertionError('writer was never released')
                with patch.object(r.os,'fsync',pause),ThreadPoolExecutor(max_workers=1) as pool:
                    writing=pool.submit(r.write_once,target,data)
                    try:
                        self.assertTrue(flushed.wait(5));self.assertFalse(target.exists())
                        self.assertEqual([],list(Path(d).glob('*.json')))
                    finally: release.set()
                    writing.result(5)
                self.assertEqual(data,r.regular(target));self.assertEqual(0o600,target.stat().st_mode&0o777)
                self.assertEqual([target],list(Path(d).iterdir()))
    def test_parallel_same_content_converges_and_conflict_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'immutable.json';data=r.canonical({'same':True})
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(lambda _:r.write_once(path,data),range(32)))
            with self.assertRaisesRegex(r.ReplayError,'immutable_private_file_conflict'):r.write_once(path,b'{}')
            self.assertEqual(data,path.read_bytes());self.assertEqual([path],list(Path(d).iterdir()))
