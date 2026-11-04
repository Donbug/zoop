import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime

sys.path.insert(0,str(Path(__file__).parents[1]))
import finalize_briefing_server_bundle as F
from test_prepare_briefing_read_bindings import fixture as bindings_fixture


def fixture(root):
    tables,profile,_=bindings_fixture()
    row=tables['briefing_rounds'][0];row['public_snapshot']['sourceBindings']=[dict(documentId='d1',documentVersion='v1')]
    row['published_payload']['metadata']={}
    d=tables['briefing_personal_deliveries'][0]
    d['result_snapshot'].update(choice=profile['choice'],selectionVersion='saved-analysis-v1')
    d['selection_snapshot']=copy.deepcopy(d['result_snapshot']);d['id']='original-delivery'
    tables['briefing_personal_preferences']=[dict(id='source-pref',member_id=None,choice=profile['choice'])]
    bundle=root/'bundle';(bundle/'tables').mkdir(parents=True);files={}
    for table,data in tables.items():
        raw=b''.join(F.canonical(r)+b'\n' for r in data);name=f'tables/{table}.jsonl';(bundle/name).write_bytes(raw)
        files[name]=dict(bytes=len(raw),sha256=F.sha(raw))
    (bundle/'manifest.json').write_bytes(F.canonical(dict(publicationReady=False,noAutomaticPublish=True,memberBindingRef='source-ref',files=files)))
    grant=dict(grantId='read-only',revision='r1',sourceId='synthetic-source',enabled=True,rights='known',
        allowedOperations=['read','quote-display'],purposes=['briefing-outlook'],recipients=['service-read'],evidence=['authored synthetic source'],expiresAt=None)
    registry=root/'grants.json';registry.write_bytes(F.canonical(dict(schemaVersion='zoop-ai-s1-1',grants=[grant])))
    request=dict(schemaVersion='briefing-finalization-request-v1',sourceManifestSha256=F.sha((bundle/'manifest.json').read_bytes()),
        memberId='explicit-target',preferenceRevision=1,importedAt='2026-11-04T00:00:00Z',
        documents=[dict(documentId='d'+str(n),documentVersion='v1',bodySha256=str(n)*64,grantId='read-only',grantRevision='r1',recipients=['service-read']) for n in (1,2)],
        rounds=[dict(roundId='r1',graphVersion='gv-'+'a'*64,snapshotSha256='b'*64)])
    path=root/'request.json';path.write_bytes(F.canonical(request))
    return bundle,path,registry,tables


class FinalizationTest(unittest.TestCase):
    def test_current_read_only_grant_binds_new_pool_without_rewriting_analysis_or_source(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle,request,registry,tables=fixture(root);old={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
            out=root/'bound';result=F.finalize(bundle,request,registry,out,now=datetime.fromisoformat('2026-11-04T01:00:00+00:00'))
            self.assertTrue(result['bound']);self.assertFalse(result['publicationReady']);self.assertEqual(result['newAiCalls'],0)
            row=json.loads((out/'tables/briefing_rounds.jsonl').read_text())
            self.assertEqual(row['public_snapshot']['sourceBindings'][0]['grantId'],'read-only')
            pool=json.loads((out/'tables/briefing_personal_pools.jsonl').read_text())
            self.assertNotEqual(pool['input_sha256'],tables['briefing_personal_pools'][0]['input_sha256'])
            personal=json.loads((out/'tables/briefing_personal_deliveries.jsonl').read_text())
            self.assertEqual(personal['result_snapshot']['presentation']['personalPriority'],tables['briefing_personal_deliveries'][0]['result_snapshot']['presentation']['personalPriority'])
            self.assertEqual(personal['result_snapshot']['poolVersion'],pool['input_sha256'])
            self.assertEqual(old,{p:p.read_bytes() for p in old})

    def test_unknown_disabled_expired_or_missing_quote_permission_never_produces_publishable_bundle(self):
        for changed in (dict(rights='unknown'),dict(enabled=False),dict(expiresAt='2026-01-01T00:00:00Z'),dict(allowedOperations=['read'])):
            with self.subTest(changed=changed),tempfile.TemporaryDirectory() as d:
                root=Path(d);bundle,request,registry,_=fixture(root);r=json.loads(registry.read_text());r['grants'][0].update(changed);registry.write_bytes(F.canonical(r))
                out=root/'blocked.json';result=F.finalize(bundle,request,registry,out)
                self.assertFalse(result['bound']);self.assertEqual(len(result['blockers']),2);self.assertTrue(out.is_file())

    def test_unregistered_graph_stays_pending_even_with_current_read_authority(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle,request,registry,_=fixture(root);r=json.loads(request.read_text());r['rounds'][0]['graphVersion']=None;request.write_bytes(F.canonical(r))
            result=F.finalize(bundle,request,registry,root/'pending.json')
            self.assertEqual(result['blockers'][0]['code'],'registered_internal_basis_required')

    def test_body_and_scope_substitution_are_rejected(self):
        for change in ('body','scope'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d:
                root=Path(d);bundle,request,registry,_=fixture(root);r=json.loads(request.read_text())
                if change=='body':r['documents'][0]['bodySha256']='f'*64
                else:r['documents'].pop()
                request.write_bytes(F.canonical(r))
                with self.assertRaises(ValueError):F.finalize(bundle,request,registry,root/'rejected')

    def test_conflicting_revision_and_duplicate_json_key_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate JSON key'):F.strict('{"x":1,"x":2}')
        with tempfile.TemporaryDirectory() as d:
            _,_,registry,_=fixture(Path(d));raw=json.loads(registry.read_text());grant=copy.deepcopy(raw['grants'][0]);grant['rights']='denied';raw['grants'].append(grant)
            with self.assertRaisesRegex(ValueError,'revision conflict'):F.grants(F.canonical(raw))
            raw['grants'].pop();raw['grants'][0]['allowedOperations']='read quote-display'
            with self.assertRaisesRegex(ValueError,'registry schema'):F.grants(F.canonical(raw))

    def test_prior_summary_and_context_digest_must_match_the_retained_series(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,_,tables=fixture(Path(d));snapshot=tables['briefing_rounds'][0]['public_snapshot']
            old=dict(status='available',roundId='foreign',cutoff='2026-10-27T00:00:00Z',resultVersion='wrong')
            snapshot['priorityContext']=dict(roundId='r1',cutoff='2026-10-28T00:20:00Z',contexts={'context:previous':dict(value=old,sha256=F.sha(F.canonical(old)))})
            with self.assertRaisesRegex(ValueError,'previous summary binding'):F.bind_tables(tables,{},dict(r1=dict(graphVersion='gv-'+'a'*64)))

    def test_archives_exact_prior_input_when_it_differs_from_current_previous_result(self):
        with tempfile.TemporaryDirectory() as d:
            _,_,_,tables=fixture(Path(d));row=tables['briefing_rounds'][0]
            row['public_snapshot']['prioritySummary']=dict(resultVersion='current-prior-version')
            later=copy.deepcopy(row);later.update(id='r2',window_to='2026-10-28T08:30:00Z')
            old=dict(status='available',roundId='r1',cutoff=row['window_to'],resultVersion='old-prior-version',
                draft=dict(text='preserved comparison basis',evidenceIds=['e2','context:market']))
            later['public_snapshot']['priorityContext']=dict(roundId='r2',cutoff=later['window_to'],
                contexts={'context:previous':dict(value=old,sha256=F.sha(F.canonical(old)))})
            tables['briefing_rounds'].append(later)
            pool=copy.deepcopy(tables['briefing_personal_pools'][0]);pool['round_id']='r2';tables['briefing_personal_pools'].append(pool)
            before=copy.deepcopy(tables);artifacts={};bindings={('d'+str(n),'v1'):dict(documentId='d'+str(n),documentVersion='v1',grantId='g',grantRevision='r',recipients=['service']) for n in (1,2)}
            graphs={rid:dict(graphVersion='gv-'+'a'*64) for rid in ('r1','r2')}
            bound=F.bind_tables(tables,bindings,graphs,artifacts)
            snapshot=bound['briefing_rounds'][1]['public_snapshot'];ref=snapshot['savedResultContext']['archivedPrevious'][0]
            self.assertEqual(tables,before);self.assertEqual(ref['resultVersion'],'old-prior-version')
            self.assertEqual(ref['evidenceIds'],['e2']);self.assertEqual(len(artifacts),1)
            self.assertEqual(json.loads(next(iter(artifacts.values())))['context'],old)
            self.assertEqual(snapshot['priorityContext'],later['public_snapshot']['priorityContext'])
            self.assertEqual({x['documentId'] for x in snapshot['sourceBindings']},{'d1','d2'})
            self.assertEqual(bound['briefing_rounds'][1]['published_payload']['metadata']['failures'][0]['code'],'archived_prior_input_version')

            # An unretained/future basis is never silently replaced by the latest previous summary.
            tables['article_versions'][1]['published_at']='2026-10-28T01:00:00Z'
            with self.assertRaisesRegex(ValueError,'future evidence'):F.bind_tables(tables,bindings,graphs)

    def test_prior_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);bundle,request,registry,_=fixture(root);out=root/'keep';out.write_text('retained')
            with self.assertRaisesRegex(ValueError,'output exists'):F.finalize(bundle,request,registry,out)
            self.assertEqual(out.read_text(),'retained')


if __name__=='__main__':unittest.main()
