from pathlib import Path
import copy
import sys
import unittest
sys.path.insert(0, str(Path(__file__).parents[1]))
import briefing_judgment_update as u


def row(cid, date, edition, cutoff, body):
    source = {'evidenceId': cid, 'documentId': cid, 'bodySha256': u.base.digest(body.encode()), 'quote': body.split('\n')[0],
              'publishedAt': cutoff, 'documentVersion': 'sha', 'title': '합성 원문', 'url': 'https://example.com/' + cid}
    return {'status': 'PASS', 'date': date, 'edition': edition, 'cutoff': cutoff, 'roundId': date + edition,
            'resultVersion': cid + '-version', 'draft': {'companies': [{'companyId': cid, 'outlook': {'text': '실제 이전 판단', 'evidenceIds': [cid]}, 'conditions': []}]},
            'frozen': {'targets': [{'companyId': cid, 'companyName': cid, 'sourceIds': [cid]}], 'sources': {cid: source}}}


class JudgmentUpdateTest(unittest.TestCase):
    def setUp(self):
        self.body = '계획 발표\n14MW Blackwell Q4 2026 예정\n70MW 2027년 중반 계획\n최종 계약 조건이 남아 있습니다.'
        self.current = row('A', '2026-10-23', 'morning', '2026-10-23T09:20:00+09:00', self.body)
        self.previous = row('B', '2026-10-22', 'evening', '2026-10-22T17:30:00+09:00', '이전 투자 계획')
        self.metadata = {cid: {'body': body, 'bodySha256': u.base.digest(body.encode())} for cid, body in [('A', self.body), ('B', '이전 투자 계획')]}
        self.frozen = u.freeze(self.current, self.previous, self.metadata)

    def draft(self):
        s = lambda text, ids: {'text': text, 'evidenceIds': ids}
        return {'conclusion': s('계획의 실행이 판단 조건입니다.', ['A', 'B']), 'industryChange': s('서로 다른 회사의 산업 자료 연결입니다.', ['A', 'B']),
            'limits': s('직접 공급관계는 입증하지 않습니다.', ['A', 'B']), 'companies': [
                {'companyId': t['companyId'], 'decision': 'initial' if t['role'] == 'selected' else 'maintained',
                 **{k: s(k, t['sourceIds']) for k in ('newEvidence', 'reason', 'strengthenIf', 'weakenIf', 'topic', 'title', 'description')}} for t in self.frozen['targets']]}

    def test_full_body_conditions_survive_short_quote_and_previous_watch_is_separate(self):
        self.assertNotIn('70MW', self.current['frozen']['sources']['A']['quote'])
        self.assertIn('70MW', self.frozen['sources']['A']['fullBody'])
        self.assertIn('최종 계약', self.frozen['sources']['A']['fullBody'])
        self.assertIsNone(self.frozen['targets'][0]['previousJudgment'])
        self.assertEqual(self.frozen['targets'][1]['previousJudgment']['outlook']['text'], '실제 이전 판단')
        self.assertEqual(self.frozen['targets'][1]['role'], 'watch')

    def test_tampered_body_and_future_evidence_and_wrong_previous_edition_rejected(self):
        self.metadata['A']['body'] += 'changed'
        with self.assertRaisesRegex(ValueError, 'full_body_digest'): u.freeze(self.current, self.previous, self.metadata)
        self.metadata['A']['body'] = self.body
        self.current['frozen']['sources']['A']['publishedAt'] = '2026-10-23T10:00:00+09:00'
        with self.assertRaisesRegex(ValueError, 'future_source'): u.freeze(self.current, self.previous, self.metadata)
        self.current['frozen']['sources']['A']['publishedAt'] = self.current['cutoff']
        self.previous['edition'] = 'morning'
        with self.assertRaisesRegex(ValueError, 'previous_edition'): u.freeze(self.current, self.previous, self.metadata)

    def test_no_invented_same_company_comparison_or_watch_upgrade_or_foreign_evidence(self):
        for kind in ('invented', 'watch', 'foreign'):
            d = self.draft()
            if kind == 'invented': d['companies'][0]['decision'] = 'strengthened'
            if kind == 'watch': d['companies'][1]['decision'] = 'strengthened'
            if kind == 'foreign': d['companies'][0]['reason']['evidenceIds'] = ['B']
            with self.assertRaises(ValueError): u.validate(d, self.frozen)

    def test_material_completeness_failure_withholds_even_when_facts_are_supported(self):
        draft = self.draft()
        class Client:
            def request_digest(self, *a): return 'a' * 64
            def call(self, stage, *args):
                return draft if stage.endswith('generation') else {**{k: k != 'materialConditionsPreserved' for k in u.QUALITY}, 'reason': '최종 계약 조건 누락'}
        result = u.assess(Client(), self.frozen)
        self.assertEqual(result['status'], 'WITHHELD'); self.assertIsNone(result['draft'])
        self.assertEqual(len(result['attempts']), 1)

    def test_editorial_preserves_model_draft_and_explicit_review_scope(self):
        draft = self.draft(); original = copy.deepcopy(draft)
        r = {'status': 'PASS', 'frozen': self.frozen, 'draft': draft, 'generatedAt': '2026-10-24T01:00:00Z'}
        review = {'reviewer': 'codex', 'reviewedAt': '2026-10-24T02:00:00Z', 'reason': '원문 대조 편집',
                  'modelVerificationAppliesTo': 'pre_edit_draft', 'frozenSha256': u.base.digest(u.base.canonical(self.frozen)),
                  'changes': [{'companyId': 'A', 'field': 'description', 'before': draft['companies'][0]['description'], 'after': {'text': '실제 도입·최종 계약 확인', 'evidenceIds': ['A']}}]}
        edited = u.apply_editorial(r, review)
        self.assertEqual(draft, original); self.assertNotEqual(edited, draft)
        review['changes'][0]['after']['evidenceIds'] = ['B']
        with self.assertRaises(ValueError): u.apply_editorial(r, review)

if __name__ == '__main__': unittest.main()
