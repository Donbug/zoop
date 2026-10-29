"""PR394 regression boundaries. Authored synthetic responses; no external transport."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import briefing_issue_intelligence as m
import briefing_issue_intelligence_view as view
import briefing_grouped_recovery_run as recovery
import briefing_issue_policy_replay as replay
from test_briefing_issue_intelligence import frozen, assess, checks, statement, candidate
from test_briefing_issue_policy import IssuePolicyTests, IssueCompanyComparisonTests, company
import test_briefing_grouped_rounds as fixtures


def draft_for(inputs):
    issues = {}
    for f in inputs:
        rows = []
        for t in f['targets']:
            s = statement(evidence=t['sourceIds'][0])
            rows.append({'companyId': t['companyId'], 'assessment': 'watch',
                **{k: copy.deepcopy(s) for k in ('takeaway','positive','negative','newInformation','impact','outlook')},
                'conditions': [s], 'risks': [s],
                'comparison': {**s,'status':'unavailable','previousResultVersion':None}})
        issues[f['issueId']] = {'headline': statement(evidence=next(iter(f['sources']))), 'companies': rows}
    return {'issues': issues}


class ReviewRegressions(unittest.TestCase):
    def test_projection_authenticates_selection_copy_input_and_original_archive(self):
        baseline = {'id':'r','date':'2026-10-22','edition':'morning', 'dataAsOf':'2026-10-22T09:20:00+09:00',
                    'items':[{'eventId':'old','title':'원래 사건'}],
                    'editionReview':{'sources':{},'companies':[{'companyId':'OLD'}]},
                    'metadata':{'selection':{}}, 'graphVersion':'old-graph'}
        f = m.seal({**frozen(1),'baselineResponseSha256':m.base.digest(m.base.canonical(baseline))})
        def transport(raw):
            request=json.loads(raw);data=json.loads(request['input']);stage=request['text']['format']['name']
            if stage=='selection': answer=assess(data['frozen'])
            elif stage=='selection-verification': answer=checks(data['frozen'])
            elif stage=='analysis': answer=draft_for(data['issues'])
            else: answer={'checks':{i['issueId']:{'supported':True,'reason':'합성 검증'} for i in data['issues']}}
            return 200,m.base.canonical({'id':'synthetic-'+stage,'status':'completed','usage':{'input_tokens':1,'output_tokens':1},
                'output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(answer)}]}]})
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);prepared=root/'in';prepared.mkdir();(prepared/'r.input.json').write_bytes(m.base.canonical(f))
            row=m.run(prepared,root/'out',transport,8,'synthetic')['rounds'][0]
            calls=view.verified_calls(root/'out');before=copy.deepcopy(baseline)
            result=view.project(baseline,f,row,calls)
            self.assertEqual(result['response']['preservedPublication']['response'],baseline)
            self.assertEqual(baseline,before)
            self.assertNotEqual(result['response']['items'],baseline['items'])
            for field in ('whyImportant','whyNow'):
                altered=copy.deepcopy(row);altered['selection']['selected'][0]['assessment'][field]['text']='인증되지 않은 선정 이유'
                with self.assertRaisesRegex(ValueError,'selected_assessment_binding'):
                    view.project(baseline,f,altered,calls)
            altered=copy.deepcopy(row);altered['selection']['selected'][0]['rank']=3
            with self.assertRaisesRegex(ValueError,'analysis_input_binding'):
                view.project(baseline,f,altered,calls)
            altered=copy.deepcopy(row);altered['analysisInputs']=[]
            with self.assertRaisesRegex(ValueError,'analysis_input_binding'):
                view.project(baseline,f,altered,calls)

    def test_one_company_evidence_error_cannot_withhold_valid_sibling(self):
        f=frozen(2);c=f['candidates'][1]
        c['sources']['e2']=candidate(2)['sources']['e2']
        c['companies'].append({**copy.deepcopy(c['companies'][0]),'companyId':'OTHER','evidenceIds':['e2']})
        f=m.seal(f);targets=m.analysis_inputs(f,m.select(f,assess(f),checks(f)),[])
        class Client:
            def __init__(self):self.calls=[]
            def call(self,stage,data,*args):
                self.calls.append((stage,copy.deepcopy(data)))
                if stage=='analysis-verification':
                    return {'checks':{i['issueId']:{'supported':True,'reason':'정상 근거'} for i in data['issues']}}
                draft=draft_for(data['issues'])
                draft['issues']['i1']['companies'][0]['impact']['evidenceIds']=['e2']
                return draft
        client=Client();draft,verified,attempts=m.analyze(client,targets)
        self.assertEqual(list(draft['issues']),['i0'])
        self.assertTrue(verified['checks']['i0']['supported']);self.assertFalse(verified['checks']['i1']['supported'])
        self.assertEqual([(s,[i['issueId'] for i in d['issues']]) for s,d in client.calls],
                         [('analysis',['i1','i0']),('analysis-verification',['i0']),('analysis',['i1'])])
        self.assertEqual(list(client.calls[-1][1]['repair']['draft']['issues']),['i1'])
        self.assertEqual(draft['issues']['i0'],attempts[0]['draft']['issues']['i0'])

    def test_withheld_corresponding_round_never_falls_back_to_older_pass(self):
        case=IssueCompanyComparisonTests();older=case.row(day='2026-10-22');latest=case.row()
        latest.update(status='WITHHELD',draft=None)
        self.assertEqual(case.before([older,latest])['status'],'unavailable')
        self.assertEqual(case.before([older,case.row()])['status'],'available')

    def test_background_alias_of_another_selected_issue_is_excluded(self):
        helper=IssuePolicyTests();selected=helper.select(helper.candidates(2))
        a,b=selected;alias=copy.deepcopy(b['sources'][0]);alias['evidenceId']='market-alias';alias['publishedAt']='2026-10-07T08:00:00+09:00'
        metadata={s['documentId']:{'title':'합성','url':'https://example.invalid'} for r in selected for s in r['sources']}
        effective={'selected':selected,'resultSha256':'a'*64,'result':{'items':[{'issueId':v['issueId'],
            'claims':[{'text':'사실','evidenceIds':[v['sources'][0]['evidenceId']]}]} for v in selected]}}
        row={'roundId':'r','date':'2026-10-07','edition':'morning','marketEnrichment':{'marketContext':{
            'window':{'to':'2026-10-07T09:20:00+09:00'},'documents':[{'documentId':alias['documentId'],
            'companyNames':[a['companyLinks'][0]['name']],'sources':[alias]}]}}}
        result=company.freeze_issue_inputs(row,effective,metadata,[])
        self.assertNotIn('market-alias',result[0]['sources'])
        self.assertIn(a['sources'][0]['evidenceId'],result[0]['sources'])
        self.assertEqual(len(result),2)

    def test_recovery_uses_policy_top_three_and_same_document_independent_events(self):
        helper=IssuePolicyTests();candidates=helper.candidates(4)
        choices=fixtures.selection(candidates,[0,1,2,3])
        record={'selectionStatus':'HELD_VALIDATION','groupedSelectionRequestDigest':'key',
                'identity':{'issueSelectionPolicy':helper.select(candidates)[0]['selectionPolicy']['version']},
                'identitySha256':'a'*64,'receipts':[]}
        with tempfile.TemporaryDirectory() as tmp:
            calls=Path(tmp);(calls/'key.complete.json').touch()
            with patch.object(recovery,'reply',return_value=(choices,{})),patch.object(recovery.grouped,'build_grouped_candidates',return_value=candidates):
                actual=recovery.prepare_round(record,{},calls,[])
        self.assertEqual([v['issueId'] for v in actual],['issue-0','issue-1','issue-2'])
        self.assertTrue(all(v['status']=='NEEDS_DRAFT' for v in actual))
        self.assertEqual([v['originalRank'] for v in actual],[1,2,3])
        self.assertTrue(all(v['selection']['rank']==1 for v in actual))
        first='합성 기업은 공급 계약을 체결했습니다.';second='합성 기업은 공장 투자계획을 확대했습니다.'
        doc=fixtures.document('same','2026-10-07T08:00:00+09:00',first+' '+second)
        arc=fixtures.archive(('a',[(doc,fixtures.mention(doc,'a',first))]),('b',[(doc,fixtures.mention(doc,'b',second))]));arc['documents']=[doc]
        candidates=recovery.grouped.build_grouped_candidates(arc,fixtures.round_spec());choices=fixtures.selection(candidates)
        with tempfile.TemporaryDirectory() as tmp:
            calls=Path(tmp);(calls/'key.complete.json').touch()
            with patch.object(recovery,'reply',return_value=(choices,{})):
                actual=recovery.prepare_round({**fixtures.round_spec(),**record},arc,calls,[])
        self.assertEqual(len(actual),2);self.assertTrue(all(v['selection'] for v in actual))

    def test_replay_missing_presentation_preserves_tracking_at_fixed_cutoff(self):
        h=IssueCompanyComparisonTests().row(day='2026-10-06');h['draft']['companies'][0]['conditions']=[statement()]
        row={'roundId':'r','date':'2026-10-07','edition':'morning','selected':[],
             'identity':{'window':{'to':'2026-10-07T09:20:00+09:00'}},'identitySha256':'a'*64}
        bundle={'rounds':[row],'presentationEnrichment':{'rounds':[],'companyOutlookLayer':{'rounds':[h]}}}
        before=copy.deepcopy(bundle);result=replay.replay(bundle,{})['rounds'][0]
        self.assertEqual(result['preparationStatus'],'presentation_missing')
        self.assertEqual(len(result['preservedTracking']),1);self.assertEqual(bundle,before)
