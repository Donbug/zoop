import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('staging',Path(__file__).parents[1]/'render_briefing_staging_sql.py')
S=importlib.util.module_from_spec(spec);spec.loader.exec_module(S)


class StagingPlanTest(unittest.TestCase):
    def bundle(self,root):
        (root/'tables').mkdir()
        files={}
        for table in S.TABLES:
            path=root/'tables'/f'{table}.jsonl';path.write_bytes(b'')
            files[str(path.relative_to(root))]={'bytes':0,'sha256':hashlib.sha256(b'').hexdigest()}
        (root/'manifest.json').write_text(json.dumps({'publicationReady':False,'noAutomaticPublish':True,
            'memberBindingRef':'test-source-reference','files':files}))

    def test_modified_input_is_rejected_instead_of_rendered(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.bundle(root)
            (root/'tables/evidence.jsonl').write_text('modified')
            with self.assertRaisesRegex(ValueError,'integrity mismatch'):
                S.render(root,'member',1,'artifact-root:artifacts')

    def test_member_and_artifact_mapping_must_be_explicit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.bundle(root)
            for member,rev,uri in [('',1,'artifact-root:artifacts'),('member',0,'artifact-root:artifacts'),('member',1,'relative/path'),('member',1,'file:///x'),('member',1,'artifact-root:../escape')]:
                with self.assertRaises(ValueError):S.render(root,member,rev,uri)

    def test_table_cannot_be_read_outside_integrity_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.bundle(root)
            path=root/'manifest.json';v=json.loads(path.read_text());v['files'].pop('tables/evidence.jsonl');path.write_text(json.dumps(v))
            with self.assertRaisesRegex(ValueError,'outside the integrity manifest'):S.verify_bundle(root)

    def test_member_mapping_is_a_sql_value_not_executable_input(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.bundle(root)
            sql=S.render(root,"member'; SELECT 1; --",1,'artifact-root:artifacts')
            self.assertIn("id='member''; SELECT 1; --'",sql)
            self.assertIn('BEGIN;',sql);self.assertIn('COMMIT;',sql)
            self.assertNotIn('UPDATE ',sql);self.assertNotIn('DELETE ',sql)


if __name__=='__main__':unittest.main()
