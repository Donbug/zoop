import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).parents[1]))
import prepare_briefing_read_bindings as B


def fixture():
    profile=dict(member_id='private-synthetic-member',preference_id='synthetic-pref',revision=2,
        choice=dict(companyIds=['synthetic-company']),created_at='2026-10-30T06:00:00Z',effective_from='2026-10-30T08:30:00Z')
    grant=dict(grantId='synthetic-grant',revision='r1',sourceId='synthetic-source',enabled=False,rights='unknown',allowedOperations=[],purposes=[],recipients=[])
    registry=dict(sources=[dict(sourceId='synthetic-source',grant=grant)])
    cutoff='2026-10-28T00:20:00Z';tables={t:[] for t in B.TABLES};candidates=[]
    for n in (1,2):
        sid='e'+str(n);did='d'+str(n);aid='a'+str(n);iid='i'+str(n);digest=str(n)*64
        tables['articles'].append(dict(id=did,provider='synthetic-source'))
        tables['article_versions'].append(dict(article_id=did,version='v1',published_at='2026-10-27T00:00:00Z',text_artifact_id=aid))
        tables['artifacts'].append(dict(id=aid,sha256=digest))
        tables['evidence'].append(dict(id=sid,article_id=did,article_version='v1',quote='synthetic fact '+str(n)))
        source=dict(evidenceId=sid,documentId=did,documentVersion='v1',quote='synthetic fact '+str(n),bodySha256=digest,publishedAt='2026-10-27T00:00:00Z')
        candidates.append(dict(issueId=iid,sources=[source],companies=[dict(companyId='synthetic-company',evidenceIds=[sid])]))
    pool=dict(roundId='r1',cutoff=cutoff,candidateCount=2,candidates=candidates)
    digest=B.sha(B.canonical(pool));pool['inputSha256']=digest
    common=dict(roundId='r1',cutoff=cutoff,items=[dict(issueId='i1',sources=candidates[0]['sources'])])
    personal=dict(roundId='r1',cutoff=cutoff,companyIds=['synthetic-company'],items=[dict(issueId='i2',sources=candidates[1]['sources'])])
    tables['briefing_rounds']=[dict(id='r1',window_to=cutoff,scheduled_at=cutoff,published_payload=dict(references=dict(evidenceIds=['e1'])),public_snapshot=dict(commonPriority=common))]
    tables['briefing_personal_pools']=[dict(round_id='r1',input_sha256=digest,snapshot=pool)]
    tables['briefing_personal_deliveries']=[dict(round_id='r1',result_snapshot=dict(presentation=dict(personalPriority=personal)))]
    return tables,profile,registry


class BindingPreparationTest(unittest.TestCase):
    def test_two_independent_issues_same_company_and_personal_only_issue_are_retained(self):
        t,p,r=fixture();result=B.plan(t,p,r)
        self.assertEqual([i['issueId'] for i in result['basis'][0]['issues']],['i1','i2'])
        self.assertEqual(len(result['basis'][0]['companyReferences']),2)
        self.assertIsNone(result['basis'][0]['graphVersion'])
        self.assertFalse(result['basis'][0]['mapUiIncluded'])
        self.assertFalse(result['basis'][0]['sourceRightsApproved'])
        self.assertNotIn(p['member_id'],json.dumps(result['basis']))

    def test_existing_disabled_grant_and_member_mapping_are_not_approved(self):
        t,p,r=fixture();before=copy.deepcopy((t,p,r));result=B.plan(t,p,r,'explicit-target')
        self.assertEqual((t,p,r),before)
        self.assertFalse(result['member']['mappingVerified'])
        self.assertEqual(result['member']['mode'],'demo')
        self.assertEqual(result['member']['roundsBeforeSourcePreference'],['r1'])
        for request in result['documents']['requests']:
            self.assertFalse(request['observedGrant']['enabled'])
            self.assertEqual(request['approvalStatus'],'pending')
            self.assertIsNone(request['proposedGrantId'])
            self.assertFalse(request['newModelCallsAuthorized'])

    def test_forged_pool_seal_is_rejected(self):
        t,p,r=fixture();t['briefing_personal_pools'][0]['snapshot']['candidates'][0]['issueId']='changed'
        with self.assertRaisesRegex(ValueError,'digest mismatch'):B.plan(t,p,r)

    def test_unregistered_evidence_and_source_identity_are_rejected(self):
        t,p,r=fixture();t['evidence'].pop()
        with self.assertRaises(KeyError):B.plan(t,p,r)
        t,p,r=fixture();r['sources'][0]['grant']['sourceId']='different-provider'
        with self.assertRaisesRegex(ValueError,'source/grant mismatch'):B.plan(t,p,r)

    def test_future_reference_and_foreign_personal_round_are_rejected(self):
        t,p,r=fixture();t['article_versions'][0]['published_at']='2026-10-29T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'publication time'):B.plan(t,p,r)
        t,p,r=fixture();t['briefing_personal_deliveries'][0]['result_snapshot']['presentation']['personalPriority']['roundId']='other'
        with self.assertRaisesRegex(ValueError,'foreign priority'):B.plan(t,p,r)

    def test_different_member_scope_is_rejected(self):
        t,p,r=fixture();p['choice']['companyIds']=['other-company']
        with self.assertRaisesRegex(ValueError,'personal scope mismatch'):B.plan(t,p,r)

    def test_common_longer_quote_requires_same_frozen_document_and_keeps_pool_unchanged(self):
        t,p,r=fixture();source=copy.deepcopy(t['briefing_personal_pools'][0]['snapshot']['candidates'][0]['sources'][0])
        source.update(evidenceId='e3',quote='longer exact synthetic fact')
        t['evidence'].append(dict(id='e3',article_id='d1',article_version='v1',quote=source['quote']))
        t['briefing_rounds'][0]['public_snapshot']['commonPriority']['items'][0]['sources']=[source]
        pool=copy.deepcopy(t['briefing_personal_pools'])
        result=B.plan(t,p,r)
        self.assertEqual(t['briefing_personal_pools'],pool)
        self.assertEqual(result['basis'][0]['supplementalReferences'][0]['evidenceId'],'e3')
        t['evidence'][-1].update(article_id='d2')
        with self.assertRaisesRegex(ValueError,'frozen document'):B.plan(t,p,r)

    def test_preflight_is_read_only_and_treats_member_as_value(self):
        t,p,r=fixture();result=B.plan(t,p,r,"member'; SELECT 1; --");sql=B.preflight(result)
        self.assertIn("id IN ('member''; SELECT 1; --'",sql)
        self.assertIn('BEGIN READ ONLY;',sql);self.assertIn('ROLLBACK;',sql)
        for statement in ('INSERT INTO','UPDATE ','DELETE FROM','CREATE '):self.assertNotIn(statement,sql)

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'keep').write_text('saved')
            with self.assertRaisesRegex(ValueError,'output exists'):B.prepare(root,root,root,root)
            self.assertEqual((root/'keep').read_text(),'saved')


if __name__=='__main__':unittest.main()
