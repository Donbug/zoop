"""Authored controls only. No provider transport, personal account or real news."""
import copy
import json
import unittest
import briefing_personal_ai as p
from test_briefing_issue_intelligence import frozen as candidates


def authored():
    f=candidates(1);c=f['candidates'][0];source=next(iter(c['sources'].values()))
    selection={'roundId':'r','poolVersion':'p','status':'available','dataAsOf':f['cutoff'],'basis':{'holdings':['C'],'watchlist':[]},
        'items':[{'issueId':'i0','title':c['title'],'whyImportant':'합성 계약 변경','whyNow':'합성 계약 확인','matches':[{'companyId':'C','name':'합성기업','reason':'합성 직접 당사자','kinds':['holding']}],'sources':[source]}]}
    frozen=p.freeze(selection,f);s={'text':'합성 계약의 실행 여부를 확인합니다.','evidenceIds':['e0']}
    company={k:copy.deepcopy(s) for k in ['keyPoint','confirmedFact','businessImpact','forMyStocks','previousChange','nextCheck']}
    company.update(direction='watch',priceObservation=None);company['previousChange']['status']='unavailable'
    draft={'overview':copy.deepcopy(s),'issues':{'i0':{'companies':{'C':company}}}}
    check={'overviewSupported':True,'overviewReason':'합성 근거 일치','issues':{'i0':{'C':{'supported':True,'reason':'합성 조건 일치'}}}}
    return selection,f,frozen,draft,check

class PersonalAiTests(unittest.TestCase):
    def test_bound_complete_personal_company_coverage_and_new_result_preserve_selection(self):
        selection,_,f,d,v=authored();original=copy.deepcopy(selection);r=p.record(f,d,v,'2026-10-30T00:00:00Z')
        self.assertEqual(original,selection);self.assertEqual('PASS',r['status']);self.assertEqual('personal-briefing-v1',r['promptVersion'])
    def test_foreign_evidence_wrong_company_and_unavailable_price_do_not_pass(self):
        _,_,f,d,_=authored()
        for field in ['foreign','company','price']:
            bad=copy.deepcopy(d)
            if field=='foreign':bad['issues']['i0']['companies']['C']['businessImpact']['evidenceIds']=['other']
            elif field=='company':bad['issues']['i0']['companies']['OTHER']=bad['issues']['i0']['companies'].pop('C')
            else:bad['issues']['i0']['companies']['C']['priceObservation']={'text':'합성 1%','evidenceIds':['e0']}
            with self.assertRaises((ValueError,p.b.ReplayError)):p.validate(bad,f)
    def test_different_round_or_source_cannot_be_frozen(self):
        s,c,_,_,_=authored();bad=copy.deepcopy(s);bad['roundId']='other'
        with self.assertRaises(ValueError):p.freeze(bad,c)
        bad=copy.deepcopy(s);bad['items'][0]['sources'][0]['quote']='바꾼 문장'
        with self.assertRaises(ValueError):p.freeze(bad,c)
    def test_tampered_input_future_price_and_wrong_previous_identity_are_rejected(self):
        selection,candidates_input,_,_,_=authored()
        tampered=copy.deepcopy(candidates_input);tampered['inputSha256']='0'*64
        with self.assertRaises(ValueError):p.freeze(selection,tampered)
        future=copy.deepcopy(candidates_input)
        from datetime import datetime,timedelta
        future['candidates'][0]['companies'][0]['observedMovement']={'status':'available','cutoff':future['cutoff'],
            'latest':{'observedAt':(datetime.fromisoformat(future['cutoff'])+timedelta(hours=1)).isoformat()}}
        future['inputSha256']=p.b.digest(p.b.canonical({k:v for k,v in future.items() if k!='inputSha256'}))
        with self.assertRaises(ValueError):p.freeze(selection,future)
        previous={('i0','C'):{'status':'available','issueId':'other','companyId':'C','roundId':'prior','cutoff':candidates_input['cutoff']}}
        with self.assertRaises(ValueError):p.freeze(selection,candidates_input,previous)

    def test_unsupported_or_receipt_missing_result_is_not_importable(self):
        _,_,f,d,v=authored();bad=copy.deepcopy(v);bad['overviewSupported']=False
        with self.assertRaises(ValueError):p.record(f,d,bad,'2026-10-30T00:00:00Z')
        r=p.record(f,d,v,'2026-10-30T00:00:00Z')
        with self.assertRaises(ValueError):p.prove_record({'frozen':f,'result':r},[])
    def test_revision_version_is_explicit_and_previous_unavailable_stays_unavailable(self):
        _,_,f,d,v=authored();r=p.record(f,d,v,'2026-10-30T00:00:00Z','personal-briefing-v1.1')
        self.assertEqual('personal-briefing-v1.1',r['promptVersion'])
        d['issues']['i0']['companies']['C']['previousChange']['status']='strengthened'
        with self.assertRaises((ValueError,p.b.ReplayError)):p.validate(d,f)
