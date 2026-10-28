"""Exercise the actual archive reader against hostile targets and interrupted writes."""
import concurrent.futures
import errno
import gzip
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'briefing_data_archive.py'
spec = importlib.util.spec_from_file_location('data_archive', SOURCE)
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def fixture(root, logical='nested/victim.txt', raw=b'complete archive payload\n'):
    root.mkdir()
    digest = reader.sha(raw)
    row = {'path': logical, 'sha256': digest, 'bytes': len(raw), 'group': 'fixture'}
    manifest = {'schemaVersion': 'zoop-collected-data-archive-v1', 'files': 1, 'uniqueObjects': 1, 'shards': []}
    for name, value in [('files.jsonl', json.dumps(row).encode()+b'\n'), ('excluded.jsonl', b''), ('redactions.jsonl', b'')]:
        compressed = gzip.compress(value, mtime=0)
        (root/(name+'.gz')).write_bytes(compressed)
        manifest[name] = {'path': name+'.gz', 'encoding': 'gzip', 'bytes': len(compressed), 'sha256': reader.sha(compressed)}
    shard = root/'objects-001.tar.gz'
    with tarfile.open(shard, 'w:gz') as tar:
        info = tarfile.TarInfo('objects/'+digest)
        info.size = len(raw)
        tar.addfile(info, io.BytesIO(raw))
    data = shard.read_bytes()
    manifest['shards'].append({'path': shard.name, 'bytes': len(data), 'sha256': reader.sha(data), 'objects': 1})
    (root/'manifest.json').write_text(json.dumps(manifest))
    return reader.Archive(root)


@unittest.skipUnless(os.name == 'posix', 'descriptor-relative extraction requires POSIX/WSL')
class AtomicExtractionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.raw = b'complete archive payload\n'
        self.archive = fixture(self.root/'archive', raw=self.raw)
        self.output = self.root/'output'
        self.target = self.output/'nested/victim.txt'

    def assertNoStaging(self):
        self.assertEqual([], list(self.output.rglob('.zoop-archive-*')))

    def test_normal_and_matching_file_reuse_preserve_bytes_and_existing_permissions(self):
        self.assertEqual('VERIFIED', self.archive.verify()['status'])
        self.assertEqual('EXTRACTED', self.archive.extract(self.output)['status'])
        self.assertEqual(self.raw, self.target.read_bytes())
        self.assertEqual(0o600, stat.S_IMODE(self.target.stat().st_mode))
        self.target.chmod(0o640)
        self.archive.extract(self.output)
        self.assertEqual(0o640, stat.S_IMODE(self.target.stat().st_mode))
        self.assertNoStaging()

    def test_different_existing_file_is_preserved(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b'user data')
        with self.assertRaises(ValueError): self.archive.extract(self.output)
        self.assertEqual(b'user data', self.target.read_bytes())

    def test_all_target_symlinks_are_rejected_without_following(self):
        for dangling in (True, False):
            for outside in (True, False):
                with self.subTest(dangling=dangling, outside=outside):
                    self.target.parent.mkdir(parents=True, exist_ok=True)
                    other = (self.root if outside else self.output)/'other'
                    if not dangling: other.write_bytes(self.raw)
                    self.target.symlink_to(other)
                    with self.assertRaises((ValueError, OSError)): self.archive.extract(self.output)
                    self.assertTrue(self.target.is_symlink())
                    self.assertEqual(not dangling, other.exists())
                    self.target.unlink()
                    if other.exists(): other.unlink()

    def test_parent_symlink_is_rejected(self):
        self.output.mkdir()
        outside = self.root/'outside';outside.mkdir()
        (self.output/'nested').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError): self.archive.extract(self.output)
        self.assertFalse((outside/'victim.txt').exists())

    def test_file_created_at_commit_is_not_overwritten(self):
        link = os.link
        def competing(source, destination, **kwargs):
            self.target.write_bytes(b'competing writer')
            return link(source, destination, **kwargs)
        with patch.object(reader.os, 'link', competing):
            with self.assertRaises(ValueError): self.archive.extract(self.output)
        self.assertEqual(b'competing writer', self.target.read_bytes())
        self.assertNoStaging()

    def test_symlink_created_at_commit_is_not_followed(self):
        link = os.link
        other = self.root/'outside'
        def competing(source, destination, **kwargs):
            self.target.symlink_to(other)
            return link(source, destination, **kwargs)
        with patch.object(reader.os, 'link', competing):
            with self.assertRaises(ValueError): self.archive.extract(self.output)
        self.assertFalse(other.exists()); self.assertTrue(self.target.is_symlink())
        self.assertNoStaging()

    def test_parent_swapped_at_commit_cannot_redirect_write(self):
        link = os.link
        outside = self.root/'outside';outside.mkdir()
        def swapping(source, destination, **kwargs):
            self.target.parent.rename(self.output/'moved')
            (self.output/'nested').symlink_to(outside, target_is_directory=True)
            return link(source, destination, **kwargs)
        with patch.object(reader.os, 'link', swapping):
            with self.assertRaises(ValueError): self.archive.extract(self.output)
        self.assertFalse((outside/'victim.txt').exists())
        self.assertNoStaging()

    def test_disk_full_after_partial_staging_leaves_no_final_and_retry_succeeds(self):
        write = os.write; calls = 0
        def interrupted(fd, data):
            nonlocal calls
            calls += 1
            if calls == 1: return write(fd, data[:5])
            raise OSError(errno.ENOSPC, 'simulated disk full')
        with patch.object(reader.os, 'write', interrupted):
            with self.assertRaises(OSError): self.archive.extract(self.output)
        self.assertFalse(self.target.exists());self.assertNoStaging()
        self.archive.extract(self.output)
        self.assertEqual(self.raw, self.target.read_bytes())

    def test_interrupt_after_commit_keeps_complete_file_and_retry_reuses_it(self):
        link = os.link
        def interrupted(*args, **kwargs):
            link(*args, **kwargs)
            raise KeyboardInterrupt()
        with patch.object(reader.os, 'link', interrupted):
            with self.assertRaises(KeyboardInterrupt): self.archive.extract(self.output)
        self.assertEqual(self.raw, self.target.read_bytes());self.assertNoStaging()
        self.archive.extract(self.output)
        self.assertEqual(self.raw, self.target.read_bytes())

    def test_two_concurrent_extractors_publish_or_reuse_the_same_complete_file(self):
        barrier = threading.Barrier(2)
        link = os.link
        def simultaneous(*args, **kwargs):
            barrier.wait(timeout=10)
            return link(*args, **kwargs)
        with patch.object(reader.os, 'link', simultaneous):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(self.archive.extract, self.output) for _ in range(2)]
                self.assertTrue(all(f.result()['status']=='EXTRACTED' for f in futures))
        self.assertEqual(self.raw, self.target.read_bytes());self.assertNoStaging()

    def test_unsupported_platform_fails_before_creating_output(self):
        with patch.object(reader.os, 'supports_dir_fd', set()):
            with self.assertRaisesRegex(OSError, 'POSIX'): self.archive.extract(self.output)
        self.assertFalse(self.output.exists())

    def test_unsafe_and_alias_paths_are_rejected(self):
        for value in ('', '.', '../x', '/absolute', 'a/../x', 'a\\x', 'a//x', './x', 'x/', 'a\x00b'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError): reader.safe_path(value)


if __name__ == '__main__': unittest.main()
