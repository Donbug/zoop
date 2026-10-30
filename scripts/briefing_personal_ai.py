"""Private, receipt-bound generation after deterministic personal selection; no online reads here."""
import copy
import json
from pathlib import Path
from datetime import datetime, timezone
import briefing_replay as b

VERSION='personal-briefing-v1'
PROMPTS=Path(__file__).resolve().parents[1]/'docs/prompts'/VERSION


def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


def statement(ids,limit=500):
    return obj({'text':{'type':'string','minLength':1,'maxLength':limit},
        'evidenceIds':{'type':'array','items':{'type':'string','enum':sorted(ids)},'minItems':1,'maxItems':len(ids)}})


def selection_basis(selection):
    return {'roundId':selection['roundId'],'poolVersion':selection['poolVersion'],
        'basis':{k:sorted(set(selection['basis'][k])) for k in ('holdings','watchlist')},
        'issues':[{'issueId':i['issueId'],'companyIds':sorted(m['companyId'] for m in i['matches'])} for i in selection['items']]}


def freeze(selection, frozen_candidates, previous=None):
    if selection['status']!='available' or not 1<=len(selection['items'])<=3:raise ValueError('personal_selection_unavailable')
    if frozen_candidates['roundId'] != selection['roundId'] or datetime.fromisoformat(frozen_candidates['cutoff']) != datetime.fromisoformat(selection['dataAsOf'].replace('Z','+00:00')):raise ValueError('personal_round_changed')
    unsigned={k:v for k,v in frozen_candidates.items() if k!='inputSha256'}
    if b.digest(b.canonical(unsigned)) != frozen_candidates.get('inputSha256'):raise ValueError('personal_candidate_seal_changed')
    previous=previous or {};issues=[]
    for item in selection['items']:
        candidate=next((c for c in frozen_candidates['candidates'] if c['issueId']==item['issueId']),None)
        if candidate is None:raise ValueError('personal_candidate_missing')
        sources={s['evidenceId']:{k:s[k] for k in ('evidenceId','documentId','quote','publishedAt','url')} for s in item['sources']}
        for sid,source in sources.items():
            original=candidate['sources'].get(sid)
            if not original or any(original[k]!=source[k] for k in ('documentId','quote','publishedAt','url')):raise ValueError('personal_source_changed')
        targets=[]
        for match in item['matches']:
            link=next(c for c in candidate['companies'] if c['companyId']==match['companyId'])
            prior=previous.get((item['issueId'],match['companyId']),{'status':'unavailable','reason':'same_issue_company_previous_missing'})
            cutoff=datetime.fromisoformat(selection['dataAsOf'].replace('Z','+00:00'))
            if prior['status']=='available':
                if prior.get('issueId')!=item['issueId'] or prior.get('companyId')!=match['companyId'] or prior.get('roundId')!=selection.get('previousRoundId') or datetime.fromisoformat(prior['cutoff'].replace('Z','+00:00'))>=cutoff:raise ValueError('personal_previous_basis_changed')
            price=link['observedMovement']
            if price['status']=='available':
                if datetime.fromisoformat(price['cutoff'].replace('Z','+00:00'))!=cutoff or datetime.fromisoformat(price['latest']['observedAt'].replace('Z','+00:00'))>cutoff:raise ValueError('personal_future_price')
            targets.append({'companyId':match['companyId'],'name':match['name'],'kinds':match['kinds'],
                'connectionReason':match['reason'],'evidenceIds':link['evidenceIds'],
                'frozenPrice':copy.deepcopy(link['observedMovement']),'previous':copy.deepcopy(prior)})
        issues.append({'issueId':item['issueId'],'title':item['title'],'whyImportant':item['whyImportant'],
            'whyNow':item['whyNow'],'sources':sources,'targets':targets})
    result={'version':VERSION,'roundId':selection['roundId'],'cutoff':selection['dataAsOf'],
        'scope':selection.get('scope','stored_round'),'edition':frozen_candidates['edition'],'holdingsKind':selection['basis'].get('holdingsKind','connected_mock_portfolio'),'selectionBasis':selection_basis(selection),'issues':issues}
    result['inputSha256']=b.digest(b.canonical(result));return result


def generation_schema(frozen):
    issues={};all_ids=set()
    for issue in frozen['issues']:
        companies={};all_ids.update(issue['sources'])
        for t in issue['targets']:
            s=statement(t['evidenceIds']);comparison=copy.deepcopy(s)
            comparison['properties']['status']={'type':'string','enum':['unavailable'] if t['previous']['status']!='available' else ['maintained','strengthened','weakened','unavailable']}
            comparison['required'].append('status')
            companies[t['companyId']]=obj({'direction':{'type':'string','enum':['positive','negative','mixed','watch']},
                'keyPoint':statement(t['evidenceIds'],180),'confirmedFact':s,'businessImpact':s,'forMyStocks':s,
                'priceObservation':{'anyOf':[s,{'type':'null'}]} if t['frozenPrice']['status']=='available' else {'type':'null'},
                'previousChange':comparison,'nextCheck':s})
        issues[issue['issueId']]=obj({'companies':obj(companies)})
    return obj({'overview':statement(all_ids,350),'issues':obj(issues)})


def verification_schema(frozen):
    return obj({'overviewSupported':{'type':'boolean'},'overviewReason':{'type':'string','minLength':1,'maxLength':700},
        'issues':obj({i['issueId']:obj({t['companyId']:obj({'supported':{'type':'boolean'},'reason':{'type':'string','minLength':1,'maxLength':700}}) for t in i['targets']}) for i in frozen['issues']})})


def validate(draft,frozen):
    b.validate_schema(draft,generation_schema(frozen))
    for i in frozen['issues']:
        for t in i['targets']:
            row=draft['issues'][i['issueId']]['companies'][t['companyId']]
            for key,value in row.items():
                if isinstance(value,dict) and 'evidenceIds' in value:
                    if not set(value['evidenceIds'])<=set(t['evidenceIds']) or len(set(value['evidenceIds']))!=len(value['evidenceIds']):raise ValueError('personal_foreign_evidence')
            if t['previous']['status']!='available' and row['previousChange']['status']!='unavailable':raise ValueError('personal_invented_comparison')


def supported(check,frozen):
    b.validate_schema(check,verification_schema(frozen))
    return check['overviewSupported'] and all(check['issues'][i['issueId']][t['companyId']]['supported'] for i in frozen['issues'] for t in i['targets'])


def record(frozen,draft,verification,generated_at,prompt_version=None):
    validate(draft,frozen)
    if not supported(verification,frozen):raise ValueError('personal_verification_failed')
    result={'schemaVersion':VERSION,'status':'PASS','model':b.MODEL,'promptVersion':prompt_version or PROMPTS.name,
        'roundId':frozen['roundId'],'cutoff':frozen['cutoff'],'inputSha256':frozen['inputSha256'],
        'selectionBasis':copy.deepcopy(frozen['selectionBasis']),'verificationMode':'separate_request_same_model',
        'generatedAt':generated_at,'draft':copy.deepcopy(draft),'verification':copy.deepcopy(verification)}
    result['resultVersion']=VERSION+'-'+b.digest(b.canonical(result));return result


def prove_record(recorded,calls):
    """Require exact input/draft/check request and response receipts before a DB import."""
    frozen=recorded['frozen'];saved=recorded['result'];expected=record(frozen,saved['draft'],saved['verification'],saved['generatedAt'],saved['promptVersion'])
    if saved!=expected:raise ValueError('personal_result_changed')
    generation=[c for c in calls if c['stage']=='personal-analysis' and c['input'].get('frozen')==frozen and c['answer']==saved['draft']]
    checked=[c for c in calls if c['stage']=='personal-verification' and c['input'].get('frozen')==frozen
        and c['input'].get('draft')==saved['draft'] and c['answer']==saved['verification']]
    if not generation or not checked:raise ValueError('personal_receipts_missing')
    return generation[-1]['key'],checked[-1]['key']
