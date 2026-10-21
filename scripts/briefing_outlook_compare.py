#!/usr/bin/env python3
"""Private review artifact for D-BRF-01/02; compare saved runs without model calls or DB writes."""
import argparse
import hashlib
import json
from pathlib import Path


def load(path):
    raw=path.read_bytes()
    return json.loads(raw),hashlib.sha256(raw).hexdigest()


def compare(baseline,current):
    old,old_sha=load(baseline);new,new_sha=load(current)
    def rows(bundle):
        return {r['roundId']:r['marketEnrichment'] for r in bundle['presentationEnrichment']['rounds']
                if r.get('marketEnrichment',{}).get('marketContext')}
    before,after=rows(old),rows(new);result=[]
    for ident,row in after.items():
        previous=before.get(ident)
        if previous is None:continue
        def project(value,bundle_path):
            summary=value['summaryResult']
            rejected = []
            for check in summary['verification'].get('checks',[]):
                if check.get('verdict') != 'SUPPORTED' or any(check.get(k) is False for k in ['atomicClaim','evidenceClauseCoverage','qualifiersPreserved','observableConditionsOnly']):
                    rejected.append(check.get('reason','검증 보류'))
            if summary['verification'].get('reason'):
                reasons={'market_outlook_forecast_required':'보완 초안에서 필수인 오늘/다음 거래일 전망 문장이 빠졌습니다.',
                         'market_quality_fact_anchor':'하나의 사실 문장에 서로 다른 원문/지표를 함께 연결했습니다.'}
                rejected.append(reasons.get(summary['verification']['reason'],summary['verification']['reason']))
            draft=[]
            if summary['verification']['status']!='PASS' and not summary['claims']:
                digest=summary.get('generationRequestDigest')
                response_path=bundle_path.parent/'calls'/ (digest+'.response.json') if digest else None
                if response_path and response_path.is_file():
                    response=json.loads(response_path.read_text())
                    text=next(t['text'] for m in response['output'] if m['type']=='message' for t in m['content'] if t['type']=='output_text')
                    draft=json.loads(text).get('claims',[])
            return {'rejectionReasons':rejected,'rejectedDraft':draft,'version':value['context']['summaryPromptVersion'],'status':summary['verification']['status'],
                    'resultVersion':summary['resultVersion'],'text':summary['text'],'claims':summary['claims'],
                    'forecasts':summary['forecasts'],'evaluations':summary['forecastEvaluations'],
                    'documents':value['marketContext']['coverage']['documents'],
                    'previous':value['marketContext']['previousPublication']['status']}
        result.append({'roundId':ident,'date':row['date'],'edition':row['edition'],
                       'old':project(previous,baseline),'new':project(row,current)})
    result.sort(key=lambda r:(r['date'],r['edition']=='evening'))
    return {'schemaVersion':'zoop-outlook-comparison-v1','oldBundleSha256':old_sha,'newBundleSha256':new_sha,'rounds':result,'newModelCalls':0}


PAGE='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>시장 요약 수정 전·후 비교</title><style>
body{font-family:system-ui,sans-serif;color:#202b37;background:#f6f8fa;margin:0}main{max-width:1360px;margin:auto;padding:30px 20px}h1{font-size:28px;margin:0 0 10px}p{line-height:1.7}nav{display:flex;gap:10px;flex-wrap:wrap;margin:24px 0}button,a{font:inherit}button{padding:12px 18px;border:1px solid #c6d0db;border-radius:10px;background:white;cursor:pointer}button[aria-pressed=true]{background:#183d65;color:white}.columns{display:grid;grid-template-columns:1fr 1fr;gap:22px}article{background:white;border:1px solid #dce2e8;padding:24px;border-radius:14px}article.new{border-top:5px solid #277c65}h2{font-size:21px}.meta{font-size:14px;color:#576b80}.claim{border-top:1px solid #e8edf2;padding:16px 0}.kind{font-size:13px;color:#276c9e;font-weight:700}.claim p{margin:7px 0;white-space:pre-wrap}.basis{font-size:13px;color:#6c7b89}.warning{color:#8b4b13}a{color:#165a9a}.links{display:flex;gap:22px;margin:10px 0 20px}summary{cursor:pointer}details{font-size:13px;color:#687c8c;margin-top:24px}@media(max-width:760px){.columns{grid-template-columns:1fr}main{padding:20px 12px}article{padding:18px}}
</style><main><h1>시장 요약 수정 전·후</h1><p>같은 회차의 기존 생성본과 새 생성본을 비교합니다. 핵심 이슈와 수집 자료를 재사용하고 시장 요약을 다시 작성했습니다.</p><nav id="rounds" aria-label="비교 회차"></nav><h2 id="heading"></h2><p id="changes"></p><div class="links" id="links"></div><div class="columns" id="content"></div><details><summary>기록 식별 정보</summary><p id="identity"></p></details></main><script>
const data=__DATA__;const urls=__URLS__;const labels={fact:'확인된 정보',interpretation:'시장 해석',forecast:'전망',forecast_update:'이전 전망 갱신',result_comparison:'아침 예상과 관측 비교'};
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n}
function draw(i){const r=data.rounds[i];document.querySelectorAll('nav button').forEach((b,k)=>b.setAttribute('aria-pressed',String(i===k)));document.querySelector('#heading').textContent=r.date+' '+(r.edition==='morning'?'출근':'퇴근');
const count=v=>v.claims.length;const conditions=v=>v.forecasts.reduce((s,f)=>s+f.conditions.length,0);
document.querySelector('#changes').textContent='문장 '+count(r.old)+' → '+count(r.new)+'개 · 새 가정 조건 '+conditions(r.old)+' → '+conditions(r.new)+'개 · 입력 문서 '+r.old.documents+' → '+r.new.documents+'개';
const links=document.querySelector('#links');links.replaceChildren();for(const k of ['old','new']){const a=el('a',k==='old'?'기존 브리핑 화면 열기':'새 브리핑 화면 열기');a.href=urls[k]+'/briefing?date='+r.date+'&edition='+r.edition;a.target='_blank';a.rel='noopener';links.append(a)}
const main=document.querySelector('#content');main.replaceChildren();for(const key of ['old','new']){const v=r[key],card=el('article',undefined,key);card.append(el('h2',key==='old'?'기존 생성본':'새 생성본'));card.append(el('p','검증: '+v.status+' · 문장 '+v.claims.length+'개 · 검증 통과 전망 '+v.forecasts.length+'개','meta'));
if(v.status!=='PASS')card.append(el('p','검증을 통과하지 못해 이 문안은 발행하지 않았습니다. 아래 내용은 비교용 보류 기록입니다.','warning'));
if(v.rejectionReasons.length){const why=el('details');why.append(el('summary','보류 이유 보기'));for(const reason of v.rejectionReasons)why.append(el('p',reason));card.append(why)}if(v.rejectedDraft.length){card.append(el('h3','마지막 반려 초안 · 미발행'));for(const draft of v.rejectedDraft)card.append(el('p',draft.text,'warning'))}for(const c of v.claims){const block=el('div',undefined,'claim');block.append(el('div',labels[c.kind]||c.kind,'kind'));block.append(el('p',c.text));if(c.conditions.length)block.append(el('p','조건: '+c.conditions.join(' · '),'basis'));if(c.counterFactors.length)block.append(el('p','반대 요인: '+c.counterFactors.join(' · '),'basis'));block.append(el('span','근거 '+c.evidenceIds.length+'개 · 지표 '+c.indicatorIds.length+'개','basis'));card.append(block)}main.append(card)}
document.querySelector('#identity').textContent='기존 '+r.old.version+' / '+r.old.resultVersion+' | 새 '+r.new.version+' / '+r.new.resultVersion+' | 과거 회차 시뮬레이션. 문안 검증과 전망 적중 평가는 별개입니다.'}
data.rounds.forEach((r,i)=>{const b=el('button',r.date+' '+(r.edition==='morning'?'출근':'퇴근'));b.onclick=()=>draw(i);document.querySelector('#rounds').append(b)});if(data.rounds.length)draw(0);
</script></html>'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['baseline','current','output']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--old-url',default='http://localhost:13084');p.add_argument('--new-url',default='http://localhost:13088')
    a=p.parse_args();result=compare(a.baseline,a.current);a.output.mkdir(mode=0o700,parents=True,exist_ok=True)
    encoded=json.dumps(result,ensure_ascii=False,indent=2)
    (a.output/'comparison.json').write_text(encoded);(a.output/'comparison.json').chmod(0o600)
    page=PAGE.replace('__DATA__',json.dumps(result,ensure_ascii=False).replace('<','\\u003c')).replace('__URLS__',json.dumps({'old':a.old_url,'new':a.new_url}).replace('<','\\u003c'))
    (a.output/'index.html').write_text(page);(a.output/'index.html').chmod(0o600)
    print(json.dumps({'rounds':len(result['rounds']),'modelCalls':0,'output':str(a.output)},ensure_ascii=False))

if __name__=='__main__':main()
