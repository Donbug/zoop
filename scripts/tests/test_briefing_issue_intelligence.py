"""Synthetic policy/contract tests, no paid transport or real news fixtures."""
import copy
import unittest
from pathlib import Path
import tempfile
import json
import briefing_issue_intelligence_view as view

import briefing_issue_intelligence as m


def statement(text='합성 계약의 이행 조건을 확인합니다.', evidence='e0'):
    return {'text': text, 'evidenceIds': [evidence]}


def candidate(index, cid='C', importance=2):
    sid = f'e{index}'
    return {'issueId': f'i{index}', 'title': f'합성 독립 사건 {index}',
        'freshnessReview': {'decision': 'DISTINCT_EVENT', 'deltaEvidenceIds': []},
        'sources': {sid: {'evidenceId': sid, 'documentId': f'd{index}', 'bodySha256': str(index) * 64,
            'quote': f'합성 기업은 서로 다른 사건 {index}의 계약을 발표했다.',
            'publishedAt': '2026-10-22T08:00:00+09:00', 'url': 'https://example.invalid/source'}},
        'companies': [{'companyId': cid, 'name': '합성 기업', 'role': '당사자',
            'evidenceIds': [sid], 'observedMovement': {'status': 'unavailable', 'reason': 'not_observed'}}],
        'snapshotSha256': str(index) * 64}


def frozen(n=4):
    return m.seal({'schemaVersion': m.VERSION, 'policyVersion': m.POLICY, 'roundId': 'r',
        'date': '2026-10-22', 'edition': 'morning', 'cutoff': '2026-10-22T09:20:00+09:00',
        'candidates': [candidate(i) for i in range(n)], 'marketReference': {'status': 'unavailable', 'indicators': []}})


def assess(f):
    return {'assessments': {c['issueId']: {'businessImportance': 2, 'informationChange': 'new_event',
        'whyImportant': statement(evidence=next(iter(c['sources']))), 'whyNow': statement(evidence=next(iter(c['sources']))),
        'relations': [{'companyId': x['companyId'], 'directness': 'direct',
            'basis': statement(evidence=x['evidenceIds'][0])} for x in c['companies']]}
        for c in f['candidates']}}


def checks(f):
    return {'checks': {c['issueId']: {'supported': True, 'reason': '합성 사건의 근거 일치'} for c in f['candidates']}}


def add_price(c, rate, start='2026-10-22T08:00:00+09:00'):
    c['companies'][0]['observedMovement'] = {'status': 'available', 'currency': 'KRW',
        'latest': {'observedAt': '2026-10-22T09:15:00+09:00', 'value': '100'},
        'news': [{'evidenceId': next(iter(c['sources'])), 'status': 'observed',
            'before': {'observedAt': start, 'value': '98'}, 'changeRatePercent': str(rate)}]}


class IssueIntelligenceTests(unittest.TestCase):
    def pick(self, f, a=None, v=None, previous=()):
        return m.select(f, a or assess(f), v or checks(f), previous)

    def test_same_company_three_independent_events_survive(self):
        f = frozen(); original = copy.deepcopy(f)
        r = self.pick(f)
        self.assertEqual([s['issueId'] for s in r['selected']], ['i0', 'i1', 'i2'])
        self.assertEqual(f, original)

    def test_unsupported_top_candidate_is_replaced_by_next_verified_one(self):
        f = frozen(); v = checks(f); v['checks']['i0']['supported'] = False
        self.assertEqual([s['issueId'] for s in self.pick(f, v=v)['selected']], ['i1', 'i2', 'i3'])

    def test_business_importance_beats_large_price_and_is_not_sentiment(self):
        f = frozen(); add_price(f['candidates'][0], -90)
        a = assess(f); a['assessments']['i3']['businessImportance'] = 3
        self.assertEqual(self.pick(f, a)['selected'][0]['issueId'], 'i3')

    def test_unobserved_is_null_and_does_not_lose_price_tie(self):
        f = frozen(); add_price(f['candidates'][2], 8)
        r = self.pick(f)
        self.assertEqual(r['selected'][0]['issueId'], 'i0')
        self.assertIsNone(r['selected'][0]['priceSignal']['value'])
        self.assertFalse(any(s['priceSignal']['usedForRanking'] for s in r['selected']))

    def test_shared_company_window_not_double_counted(self):
        f = frozen(3)
        for c in f['candidates']: add_price(c, 2)
        r = self.pick(f)
        self.assertTrue(all(not s['priceSignal']['usedForRanking'] for s in r['selected']))

    def test_comparable_distinct_prices_only_break_same_importance_tie(self):
        f = frozen(3)
        for i, c in enumerate(f['candidates']):
            c['companies'][0]['companyId'] = f'C{i}'; add_price(c, i + 1)
        self.assertEqual([s['issueId'] for s in self.pick(f)['selected']], ['i2', 'i1', 'i0'])

    def test_different_windows_disable_price_comparison(self):
        f = frozen(2)
        for i, c in enumerate(f['candidates']):
            c['companies'][0]['companyId'] = f'C{i}'; add_price(c, 4, f'2026-10-22T08:0{i}:00+09:00')
        self.assertFalse(self.pick(f)['selected'][0]['priceSignal']['usedForRanking'])

    def test_no_news_window_is_not_zero_return(self):
        c = candidate(1); add_price(c, 2); c['companies'][0]['observedMovement']['news'][0]['status'] = 'no_post_news_trade'
        self.assertIsNone(m.price_signal(c)['value'])

    def test_repeat_and_low_importance_do_not_fill_three(self):
        f = frozen(); a = assess(f)
        a['assessments']['i0']['informationChange'] = 'repeat'
        for iid in ['i1', 'i2']: a['assessments'][iid]['businessImportance'] = 1
        self.assertEqual(len(self.pick(f, a)['selected']), 1)

    def test_same_quote_in_new_ids_is_not_new_event(self):
        f = frozen(2)
        f['candidates'][1]['sources']['e1'].update({k: f['candidates'][0]['sources']['e0'][k]
            for k in ('documentId', 'bodySha256', 'quote')})
        self.assertEqual(len(self.pick(f)['selected']), 1)

    def test_material_delta_and_prior_identity_are_required(self):
        f = frozen(1); a = assess(f); old = self.pick(f)['selected']
        self.assertEqual(self.pick(f, a, previous=old)['selected'], [])
        a['assessments']['i0']['informationChange'] = 'material_update'
        with self.assertRaisesRegex(ValueError, 'material_delta_missing'): self.pick(f, a)
        f['candidates'][0]['freshnessReview'] = {'decision': 'MATERIAL_UPDATE', 'deltaEvidenceIds': ['e0']}
        self.assertEqual(self.pick(f, a, previous=old)['selected'], [])
        f['candidates'][0]['sources']['e0']['quote'] = '합성 기업은 같은 계약의 이행을 완료했다.'
        self.assertEqual(len(self.pick(f, a, previous=old)['selected']), 1)

    def test_relationship_cannot_borrow_other_company_evidence(self):
        f = frozen(1); c = f['candidates'][0]
        c['sources']['e1'] = candidate(1)['sources']['e1']
        c['companies'].append({'companyId': 'OTHER', 'name': '타기업', 'evidenceIds': ['e1']})
        a = assess(f); a['assessments']['i0']['relations'][0]['basis']['evidenceIds'] = ['e1']
        with self.assertRaisesRegex(ValueError, 'foreign_relation_evidence'): m.validate_assessments(a, f)

    def test_inputs_are_per_event_not_company(self):
        f = frozen(3); targets = m.analysis_inputs(f, self.pick(f), [])
        self.assertEqual(len(targets), 3)
        self.assertEqual({t['targets'][0]['companyId'] for t in targets}, {'C'})
        for t in targets:
            self.assertEqual(t['targets'][0]['issueIds'], [t['issueId']]); m.check_seal(t)

    def test_input_tampering_and_unknown_stage_cannot_reuse_identity(self):
        f = frozen(); f['cutoff'] = '2026-10-22T17:30:00+09:00'
        with self.assertRaisesRegex(ValueError, 'input_hash'): m.check_seal(f)

    def test_recorded_clock_conflict_disqualifies_all_events_using_that_body(self):
        f = frozen(3); old = copy.deepcopy(f)
        f['candidates'][1]['sources']['e1'].update(documentId='d0', bodySha256='0'*64)
        f = m.seal(f)
        audit = {'documentId':'d0','bodySha256':'0'*64,'status':'publisher_time_disagreement',
                 'action':'quarantine','evidenceSha256':'a'*64}
        fixed = m.quarantine_documents(f,[audit])
        self.assertEqual([c['issueId'] for c in fixed['candidates']], ['i2'])
        self.assertEqual(len(f['candidates']), len(old['candidates']))
        self.assertEqual(fixed['supersedesInputSha256'], f['inputSha256'])
        self.assertEqual([e['reason'] for e in fixed['excluded']], ['publisher_time_disagreement']*2)

    def test_repair_preserves_supported_classifications(self):
        f = frozen(2); first = assess(f); v = checks(f)
        v['checks']['i1'] = {'supported': False, 'reason': '합성 중요도 과대평가'}
        amended = {'assessments': {'i1': copy.deepcopy(first['assessments']['i1'])}}
        amended['assessments']['i1']['businessImportance'] = 1
        class Client:
            def __init__(self): self.calls = []
            def call(self, stage, data, *args):
                self.calls.append((stage, copy.deepcopy(data)))
                return copy.deepcopy([first,v,amended,{'checks': {'i1': {'supported': True,'reason':'보완 확인'}}}][len(self.calls)-1])
        client = Client(); a, checked, attempts = m.assess_candidates(client, f)
        self.assertEqual(a['assessments']['i0'], first['assessments']['i0'])
        self.assertEqual(a['assessments']['i1']['businessImportance'], 1)
        self.assertEqual([c['issueId'] for c in client.calls[2][1]['frozen']['candidates']], ['i1'])
        self.assertFalse(attempts[0]['verification']['checks']['i1']['supported'])
        self.assertTrue(checked['checks']['i1']['supported'])

    def test_four_stage_execution_reuses_complete_calls_and_refuses_tampered_draft(self):
        calls = []
        def transport(raw):
            request = json.loads(raw); data = json.loads(request['input']); stage = request['text']['format']['name']
            calls.append(stage)
            if stage == 'selection': answer = assess(data['frozen'])
            elif stage == 'selection-verification': answer = checks(data['frozen'])
            elif stage == 'analysis-verification': answer = {'checks': {f['issueId']: {'supported': True, 'reason': '합성 검증'} for f in data['issues']}}
            else:
                issues = {}
                for f in data['issues']:
                    companies = []
                    for t in f['targets']:
                        s = statement(evidence=t['sourceIds'][0])
                        companies.append({'companyId': t['companyId'], 'assessment': 'watch',
                            **{k: copy.deepcopy(s) for k in ['takeaway','positive','negative','newInformation','impact','outlook']},
                            'conditions': [s], 'risks': [s], 'comparison': {**s,'status':'unavailable','previousResultVersion':None}})
                    issues[f['issueId']] = {'headline': statement(evidence=next(iter(f['sources']))), 'companies': companies}
                answer = {'issues': issues}
            return 200, m.base.canonical({'id': 'synthetic-'+str(len(calls)), 'status': 'completed',
                'usage': {'input_tokens': 100, 'output_tokens': 50},
                'output': [{'type': 'message', 'content': [{'type':'output_text','text':json.dumps(answer)}]}]})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); prepared = root/'prepared'; prepared.mkdir()
            (prepared/'round.input.json').write_bytes(m.base.canonical(frozen(1)))
            result = m.run(prepared, root/'out', transport, 8, 'synthetic-authorization')
            saved = {p.name:p.read_bytes() for p in (root/'out'/'calls').iterdir()}
            self.assertEqual(calls, ['selection','selection-verification','analysis','analysis-verification'])
            self.assertEqual(m.run(prepared, root/'out', transport, 8, 'synthetic-authorization'), result)
            self.assertEqual(len(calls), 4)
            self.assertEqual(saved, {p.name:p.read_bytes() for p in (root/'out'/'calls').iterdir()})
            receipts = view.verified_calls(root/'out'); issue = result['rounds'][0]['passed'][0]
            self.assertTrue(view.prove_issue(issue, receipts))
            row = result['rounds'][0]
            self.assertEqual(view.reuse_candidate_assessments(frozen(1), row, receipts)[0], row['assessments'])
            tampered = copy.deepcopy(row)
            tampered['assessments']['assessments']['i0']['whyImportant']['text'] = '별도로 변경한 선정 이유'
            with self.assertRaisesRegex(ValueError, 'reused_assessment_receipts'):
                view.reuse_candidate_assessments(frozen(1), tampered, receipts)
            bad = copy.deepcopy(issue); bad['draft']['headline']['text'] = '근거 없는 변경'
            with self.assertRaisesRegex(ValueError, 'view_result_hash'): view.prove_issue(bad, receipts)

    def test_no_transport_without_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'authorization_and_call_limit'):
                m.run(Path(tmp)/'in', Path(tmp)/'out', lambda _: self.fail('must not call'), 16, '')


if __name__ == '__main__': unittest.main()
