"""Preserve complete source paragraphs; reuse generation, independently recheck changed citations.

No direction is inferred by this adapter. Source facts remain separate from Jev quote effects.
The original publication, provider response and earlier review are immutable inputs.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path

import briefing_s3_review as base

POLICY = 'complete-source-paragraph-1'


def company_names(company):
    catalogue=json.loads((base.REPO/'api/src/main/resources/company/demo-companies.json').read_text())['companies']
    matched=next((c for c in catalogue if c['company_id']==company['id']),None)
    return list(dict.fromkeys([company['name'], *([matched['name'], *matched['aliases']] if matched else [])]))


def named_context(evidence, facts, names):
    """Carry the explicit company subject, including the adjacent complete sentence when needed."""
    pattern=re.compile('|'.join(r'(?<![A-Za-z0-9_])'+re.escape(n)+r'(?![A-Za-z0-9_])' for n in names),re.I)
    if any(pattern.search(f['quote']) for f in facts):return facts
    context=evidence['bodyContext'];text=context['text'];offset=context['start']
    anchor=facts[0]
    end=anchor['end']-offset
    # An adjoining sentence can identify a Board or an omitted subject without supplying outside knowledge.
    for match in re.finditer(r'.+?[.!?。！？](?=\s|$)',text[end:],re.S):
        if pattern.search(match.group()):
            last=end+match.end();first=anchor['start']-offset
            quote=text[first:last]
            new={**anchor,'quote':quote,'end':offset+last}
            new['id']='fact-'+base.sha(base.canonical([new['articleId'],new['articleVersion'],new['start'],new['end']]))[:32]
            return [new,*facts[1:]]
    raise RuntimeError('named_company_context_unavailable')


def paragraphs(text, base_offset=0):
    """Only whole, source-bound paragraphs; never append an ellipsis or clip to a length cap."""
    result = []
    for match in re.finditer(r'[^\n]+', text):
        start, end = match.span()
        while end > start and text[end-1].isspace():
            end -= 1
        quote = text[start:end]
        # The first/last paragraph may have been cut by the historical context window.
        if start == 0 and base_offset != 0:
            continue
        if end == len(text.rstrip()) and not re.search(r'[.!?。！？][\"\'”’)]?$', quote):
            continue
        if quote and re.search(r'[.!?。！？][\"\'”’)]?$', quote):
            result.append((start, end, quote))
    return result


def source_facts(evidence, anchors):
    context = evidence.get('bodyContext')
    if not context:
        raise RuntimeError('complete_source_context_missing')
    text = context['text']
    if len(text) != context['end'] - context['start']:
        raise RuntimeError('source_context_offsets_invalid')
    for anchor in anchors:
        if not anchor or text.count(anchor) != 1:
            raise RuntimeError('source_anchor_not_unique')
    units = paragraphs(text, context['start'])
    selected = [(a,b,q) for a,b,q in units if any(anchor in q for anchor in anchors)]
    if not selected or any(not any(anchor in q for _,_,q in selected) for anchor in anchors):
        raise RuntimeError('source_anchor_paragraph_incomplete')
    # Explicit contract qualifications are not dropped even when outside the anchor paragraph.
    for unit in units:
        if re.search(r'\bsubject to\b|최종\s*계약|조건부', unit[2], re.I) and unit not in selected:
            selected.append(unit)
    facts = []
    for start,end,quote in sorted(selected):
        absolute_start, absolute_end = context['start']+start, context['start']+end
        facts.append({'id':'fact-'+base.sha(base.canonical([evidence['documentId'],evidence['documentVersion'],absolute_start,absolute_end]))[:32],
            'quote':quote,'articleId':evidence['documentId'],'articleVersion':evidence['documentVersion'],
            'title':evidence['title'],'url':evidence['url'],'publishedAt':evidence['publishedAt'],
            'start':absolute_start,'end':absolute_end,'sourceEvidenceId':evidence['id']})
    return facts


def expanded_facts(case, generated):
    anchors = {}
    for impact in generated['impacts']:
        for quote in impact['supporting'] + impact['opposing']:
            anchors.setdefault(quote['documentId'], []).append(quote['quote'])
    facts = []
    for source in case['basis']['evidence']:
        # A directionally inconclusive producer may omit citations; the original fact still exists.
        complete = paragraphs(source['bodyContext']['text'], source['bodyContext']['start'])
        optional = [a for a in anchors.get(source['documentId'], []) if any(a in q for _,_,q in complete)]
        seed = list(dict.fromkeys([source['quote'], *optional]))
        found=source_facts(source, seed)
        facts.extend(named_context(source,found,company_names(case['basis']['companies'][0])))
    return facts


def candidate_for(case, company, generated, facts):
    _, relation, originals = base.payload(case, company)
    # Include the already maintained catalogue aliases, never an invented company relationship.
    names = company_names(company)
    relation['facts']['subject']['names'] = names
    source = generated['impacts'][0]
    wire = copy.deepcopy(generated)
    proposal = wire['impacts'][0]
    proposal['supporting'] = [{'documentId':f['articleId'],'documentVersion':base.native_version(f['articleVersion']),
        'quote':f['quote'],'start':f['start']-originals[(f['articleId'],base.native_version(f['articleVersion']))]['bodyContext']['start'],
        'end':f['end']-originals[(f['articleId'],base.native_version(f['articleVersion']))]['bodyContext']['start']} for f in facts]
    proposal['opposing'] = []
    # These are context candidates, not a new producer opinion. Only Jev assigns their effects.
    proposal['direction'] = 'undetermined'
    proposal['reason'] = 'Source paragraph context for independent reassessment; original proposal is preserved separately.'
    proposal['limitations'] = source.get('limitations')
    candidates = base.rules.evaluate_impacts(base.rules.parse_impacts(wire), relation, set(originals), lambda c:base.resolve(c, originals))
    if len(candidates)!=1 or candidates[0]['precheck']['state']!='pending':
        raise RuntimeError('complete_context_precheck_failed')
    return candidates[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--api',default='http://127.0.0.1:18162')
    parser.add_argument('--credentials',type=Path,required=True)
    parser.add_argument('--approval',type=Path,required=True)
    parser.add_argument('--budget',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args();args.previous=args.previous.resolve();args.output=args.output.resolve()
    cases=json.loads((args.previous/'inputs.json').read_text())
    plans=[]
    for case in cases:
        if len(case['basis']['companies'])!=1:raise RuntimeError('company_context_requires_separate_case')
        old=json.loads((args.previous/'completed'/f"{case['inputDigest']}.json").read_text())
        generation=next(p for p in old['proofs'] if json.loads((args.previous/p['path']).read_text())['stage']=='impact')
        receipt=json.loads((args.previous/generation['path']).read_text())
        raw=json.loads(receipt['http']['bodyText'])
        generated=json.loads(raw['choices'][0]['message']['content'])
        facts=expanded_facts(case,generated)
        candidate=candidate_for(case,case['basis']['companies'][0],generated,facts)
        plans.append((case,old,facts,candidate))
    base.once(args.output/'inputs.json',cases)
    base.once(args.output/'citation-plan.json',[{'inputDigest':c['inputDigest'],'facts':f,'recheck':o['assessments'][0]['label']!='positive'} for c,o,f,_ in plans])
    print(json.dumps({'cases':len(plans),'changedReviews':sum(o['assessments'][0]['label']!='positive' for _,o,_,_ in plans),'policy':POLICY}),flush=True)
    if not args.execute:return
    # Copy the previous immutable reservations as well: the outer 16-call and $3 guards remain cumulative.
    for name in ['attempts','receipts','requests']:
        for file in (args.previous/name).glob('*.json'):
            base.once(args.output/name/file.name,file.read_bytes())
    runtime,approval=base.configure(args)
    reviews=[]
    for case,old,facts,candidate in plans:
        path=args.output/'completed'/f"{case['inputDigest']}.json"
        if path.exists():reviews.append(json.loads(path.read_text()));continue
        current=copy.deepcopy(old);assessment=current['assessments'][0]
        assessment['facts']=facts
        current['citationRepair']={'policy':POLICY,'previousResultSha256':base.sha(base.canonical(old)),
            'generation':'reused','effects':'reused' if assessment['label']=='positive' else 'independent_recheck'}
        if assessment['label']!='positive':
            request=base.rules.impact_verifier_request(candidate,{'policyVersion':'zoop-impact-policy-1'})
            verified,proof=base.send(args,runtime,approval,'verify-impact',request,case)
            decision=base.rules.decide_impact(candidate,runtime.answer('verify-impact',verified))
            base.once(args.output/'verdicts'/f"{case['inputDigest']}.json",{'decision':decision,'audit':runtime.audit('verify-impact',verified)})
            assessment.update(status='verified' if decision['status']=='verified' else 'verifier-reject',label=decision['label'],
                              targetVerdict=decision['targetVerdict'],evidence=[])
            if assessment['status']=='verified':
                mapped={qid:side for side,ids in decision['mapped'].items() for qid in ids}
                for q in candidate['quotes']:
                    f=next(f for f in facts if f['quote']==q['text'] and f['articleId']==q['documentId'])
                    assessment['evidence'].append({**f,'id':q['quoteId'],'effect':mapped[q['quoteId']]})
            # The new verifier is bound to the new context. Retain the original generator receipt only here;
            # all original verifier receipts remain immutable in the previous execution and copied archive.
            current['proofs']=[p for p in old['proofs'] if json.loads((args.previous/p['path']).read_text())['stage']=='impact']
            current['proofs'].append({'path':str(proof.relative_to(args.output)),'sha256':base.sha(proof.read_bytes()),'bytes':proof.stat().st_size})
            current['assessedAt']=base.now()
        base.once(path,current);reviews.append(current)
        print(json.dumps({'completed':len(reviews),'label':assessment['label'],'factParagraphs':len(facts)}),flush=True)
    manifest={'schemaVersion':'zoop-briefing-impact-reviews-2','sourceKind':'actual','executionMode':'live','recordingKind':'provider',
        'inputScope':'preserved_quote_context','generationModel':'gpt-6-luna','verifierModel':'jev-1.14.0','citationPolicy':POLICY,
        'previousManifestSha256':base.sha((args.previous/'manifest.json').read_bytes()),'reviews':reviews}
    base.once(args.output/'manifest.json',manifest)


if __name__=='__main__':
    main()
