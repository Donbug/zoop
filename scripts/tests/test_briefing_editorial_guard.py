"""Regression: a repeated announcement cannot become a fresh headline; linked companies cannot disappear."""
import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import briefing_editorial_guard as guard
from test_briefing_grouped_rounds import archive,document,mention,selection
G=guard.grouped

class EditorialTests(unittest.TestCase):
    def candidate(self,status='DISTINCT_EVENT'):
        quote='합성 기업이 기술 적용 계약을 체결했습니다. 계약의 범위는 관리 기술 도입이며 실제 뉴스가 아닌 시험용 원문입니다. 합성 기업은 별도 기업과 공급 계약의 실행 일정을 확정했습니다.'
        d=document('doc','2026-10-07T12:00:00+09:00',quote);m=mention(d,'mention',quote)
        a=archive(('issue-test',[(d,m)]))
        c=G.build_grouped_candidates(a,{'window':{'from':'2026-10-07T09:20:00+09:00','to':'2026-10-07T17:30:00+09:00','openStart':False}})[0]
        c['freshnessReview']={'decision':status,'deltaEvidenceIds':[],'reason':'authored','reviewRequestDigest':None}
        c['asOfSnapshotSha256']=G.base.digest(G.base.canonical({k:v for k,v in c.items() if k!='asOfSnapshotSha256'}))
        return a,c
    def test_reprint_not_selectable_even_with_new_article_clock(self):
        _,c=self.candidate('REPEAT')
        self.assertNotIn(c['issueId'],G.selection_schema([c])['properties']['selected']['items'].get('properties',{}).get('issueId',{}).get('enum',[]))
        with self.assertRaises(G.ReplayError):G.freeze_grouped_selection(selection([c]),[c],'a'*64)
    def test_dropping_known_company_is_rejected(self):
        _,c=self.candidate();v=selection([c]);v['selected'][0]['companyIds']=[]
        with self.assertRaisesRegex(G.ReplayError,'company_link_omitted'):G.freeze_grouped_selection(v,[c],'a'*64)
    def test_exact_grounded_company_projection_ignores_search_tags_and_future(self):
        a,c=self.candidate();m=a['issues'][0]['mentions'][0];m['grounding']={'verdict':'SUPPORTED'}
        self.assertEqual(guard.company_names(a,'doc',G.sim.aware('2026-10-07T13:00:00+09:00')),['합성 기업'])
        self.assertEqual(guard.company_names(a,'doc',G.sim.aware('2026-10-07T09:00:00+09:00')),[])
        m['companyProjection']={'briefingEligible':False}
        self.assertEqual(guard.company_names(a,'doc',G.sim.aware('2026-10-07T13:00:00+09:00')),[])
    def test_duplicate_choice_is_audited_without_duplicating_a_valid_issue(self):
        _,candidate=self.candidate();other=copy.deepcopy(candidate);other['issueId']='issue-other'
        other['asOfSnapshotSha256']=G.base.digest(G.base.canonical({k:v for k,v in other.items() if k!='asOfSnapshotSha256'}))
        value=selection([candidate,other]);value['selected']=[value['selected'][0],copy.deepcopy(value['selected'][0])]
        selected=G.freeze_grouped_selection(value,[candidate,other],'a'*64)
        self.assertEqual(len(selected),1)
        self.assertEqual(G.rejected_duplicates(value)[0]['index'],1)
    def test_material_update_needs_reviewed_delta(self):
        _,c=self.candidate('MATERIAL_UPDATE');v=selection([c]);v['selected'][0]['novelty']='MATERIAL_UPDATE';v['selected'][0]['deltaEvidenceIds']=c['newEvidenceIds']
        with self.assertRaisesRegex(G.ReplayError,'editorial_delta_missing'):G.freeze_grouped_selection(v,[c],'a'*64)

if __name__=='__main__':unittest.main()
