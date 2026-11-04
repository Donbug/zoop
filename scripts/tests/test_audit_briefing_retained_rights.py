import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]))
import audit_briefing_retained_rights as A
from render_briefing_staging_sql import TABLES


def fixture(root,**use_override):
    bundle=root/'bundle';(bundle/'tables').mkdir(parents=True)
    state=root/'retained';state.mkdir();defaults,_=A.collector_default();use=defaults|use_override
    plan=dict(schemaVersion='zoop-private-news-plan-1',provenance='private-public-web',config=dict(planId='authored'),**use)
    (state/'PLAN.json').write_bytes(A.canonical(plan))
    text='[authored] test fact';body=A.sha(text.encode())
    record=dict(schemaVersion='zoop-private-news-record-1',provenance='private-public-web',source='authored-source',
        planDigest=A.sha(A.canonical(plan)),prepared=dict(text=text),textSha256=body,**use)
    path=state/'record.json';path.write_bytes(A.canonical(record));digest=A.sha(path.read_bytes())
    units_file=root/'units.json';units_file.write_bytes(A.canonical([dict(observation=dict(documentId='d',documentVersion='v1'),
        index=dict(recordPath=str(path),stateDir=str(state),recordSha256=digest,sourceId='authored-source',planId='authored'),
        rawRecordSha256=digest,bodySha256=body)]))
    rows={t:[] for t in TABLES};rows['articles']=[dict(id='d',provider='authored-source')]
    rows['article_versions']=[dict(article_id='d',version='v1',text_artifact_id='text')]
    rows['artifacts']=[dict(id='text',sha256=body)];files={}
    for table,data in rows.items():
        raw=b'\n'.join(A.canonical(row) for row in data);name=f'tables/{table}.jsonl'
        (bundle/name).write_bytes(raw);files[name]=dict(bytes=len(raw),sha256=A.sha(raw))
    manifest=dict(publicationReady=False,noAutomaticPublish=True,files=files,
        sourceFiles={str(p):A.sha(p.read_bytes()) for p in (units_file,path)})
    (bundle/'manifest.json').write_bytes(A.canonical(manifest))
    return bundle,units_file,state


class RetainedRightsAuditTest(unittest.TestCase):
    def test_local_defaults_are_neither_publisher_denial_nor_publication_permission(self):
        with tempfile.TemporaryDirectory() as d:
            bundle,units,state=fixture(Path(d));before={p:p.read_bytes() for p in Path(d).rglob('*') if p.is_file()}
            result=A.audit(bundle,units);document=result['documents'][0]
            self.assertEqual(document['restrictionOrigin'],'collector_private_default')
            self.assertEqual(document['publisherDecision'],'not_recorded')
            self.assertFalse(document['publicationAuthorized']);self.assertFalse(document['newModelCallsAuthorized'])
            self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_changed_use_is_not_mislabeled_as_a_harmless_default(self):
        with tempfile.TemporaryDirectory() as d:
            bundle,units,state=fixture(Path(d),rights='denied')
            document=A.audit(bundle,units)['documents'][0]
            self.assertEqual(document['restrictionOrigin'],'unresolved_metadata')
            self.assertEqual(document['observedUse']['rights'],'denied')
            self.assertFalse(document['publicationAuthorized'])

    def test_changed_record_and_units_are_rejected(self):
        for name in ('record','units'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
                bundle,units,state=fixture(Path(d));target=units if name=='units' else state/'record.json'
                target.write_bytes(target.read_bytes()+b' ')
                with self.assertRaisesRegex(ValueError,'not pinned or changed'):A.audit(bundle,units)

    def test_changed_collection_plan_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            bundle,units,state=fixture(Path(d));plan=json.loads((state/'PLAN.json').read_text())
            plan['usage']='changed';(state/'PLAN.json').write_bytes(A.canonical(plan))
            with self.assertRaisesRegex(ValueError,'plan mismatch'):A.audit(bundle,units)

    def test_provider_or_version_cannot_be_substituted(self):
        with tempfile.TemporaryDirectory() as d:
            bundle,units,state=fixture(Path(d));manifest=json.loads((bundle/'manifest.json').read_text())
            path=bundle/'tables/articles.jsonl';path.write_bytes(A.canonical(dict(id='d',provider='foreign')))
            manifest['files']['tables/articles.jsonl']=dict(bytes=path.stat().st_size,sha256=A.sha(path.read_bytes()))
            (bundle/'manifest.json').write_bytes(A.canonical(manifest))
            with self.assertRaisesRegex(ValueError,'identity mismatch'):A.audit(bundle,units)

    def test_private_output_is_new_and_prior_audit_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle,units,state=fixture(root);output=root/'audit.json'
            A.write_audit(bundle,units,output);before=output.read_bytes()
            self.assertEqual(output.stat().st_mode&0o777,0o600)
            with self.assertRaisesRegex(ValueError,'output exists'):A.write_audit(bundle,units,output)
            self.assertEqual(before,output.read_bytes())


if __name__=='__main__':unittest.main()
