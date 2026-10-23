"""Read-only reuse of completed event/participant grounding. Never calls a provider."""
from pathlib import Path
import re
import briefing_grouped_rounds as grouped

base = grouped.base
POLICY = 'recorded-supported-event-exact-quote-v1'


def load(archive, output):
    originals = {m['mentionId']: m for i in archive['issues'] for m in i['mentions']}
    documents = {d['documentId']: d for d in archive['documents']}
    result = {}
    for receipt in archive['receipts']:
        if receipt['stage'] != 'issue_grounding' or receipt.get('status') != 'completed' or receipt.get('usageKnown') is not True:
            continue
        key = receipt['requestDigest']
        grouped.require(re.fullmatch('[0-9a-f]{64}', key) is not None, 'semantic_receipt_identity')
        raw_request = base.regular(Path(output) / 'calls' / (key + '.request.json'))
        raw_response = base.regular(Path(output) / 'calls' / (key + '.response.json'))
        grouped.require(base.digest(raw_request) == key and base.digest(raw_response) == receipt['responseSha256'], 'semantic_receipt_digest')
        request, response = base.strict_load(raw_request), base.strict_load(raw_response)
        grouped.require(request['store'] is False and request['model'] == receipt['model'] == base.MODEL
                        and request['text']['format']['name'] == 'issue_grounding'
                        and response['status'] == 'completed' and receipt['httpStatus'] == 200
                        and response['id'] == receipt['responseId']
                        and all(response['usage'][p] == receipt[f] for f, p in [('inputTokens', 'input_tokens'), ('outputTokens', 'output_tokens')]), 'semantic_provider_binding')
        grouped.require(base.digest(request['instructions'].encode()) == archive['identity']['promptSha256']['issue_grounding'], 'semantic_prompt_binding')
        frozen, answer = base.strict_load(request['input']), base.output_of(response)
        grouped.require(frozen['authorization']['sourceSha256'] == archive['sourceFileSha256']
                        and set(answer['verdicts']) == set(frozen['mentions']), 'semantic_population')
        articles = {a['article_id']: a for a in frozen['articles']}
        for key_id, raw in frozen['mentions'].items():
            m = originals.get(key_id)
            verdict = answer['verdicts'][key_id]
            if m is None or verdict['verdict'] != 'SUPPORTED':
                continue
            article, doc = articles[m['articleId']], documents[m['articleId']]
            grouped.require(doc['body'] == article['body'] and base.digest(doc['body'].encode()) == m['bodySha256']
                            and doc['url'].startswith('https://') and doc['url'] == article['url'], 'semantic_original_source')
            grouped.require(m['grounding'] == verdict and raw['background'] is False
                            and all(m[left] == raw[right] for left, right in [('articleId', 'article_id'), ('pocArticleVersion', 'article_version'), ('title', 'title'), ('action', 'action'), ('assertionStatus', 'assertion_status')]), 'semantic_event_binding')
            grouped.require(all(any(all(e[f] == old[f] for f in ('quote', 'start', 'end')) for old in raw['evidence']) for e in m['evidence']), 'semantic_quote_binding')
            grouped.require(all(a['rawParticipant'] in raw['participants'] for a in m.get('companyProjection', {}).get('audit', [])), 'semantic_participant_binding')
            grouped.require(key_id not in result, 'semantic_duplicate_mention')
            result[key_id] = {'mention': m, 'requestDigest': key}
    return result


def matches(current, proof):
    if not proof:
        return False
    m = proof['mention']
    if m.get('grounding', {}).get('verdict') != 'SUPPORTED' or any(m[f] != current[f] for f in ('articleId', 'articleVersion', 'bodySha256')):
        return False
    accepted = {e['evidenceId']: e for e in m['evidence']}
    return bool(current['evidence']) and all(e.get('quote', '').strip() and e['evidenceId'] in accepted
        and all(e[f] == accepted[e['evidenceId']][f] for f in ('quote', 'start', 'end')) for e in current['evidence'])


def apply(candidates, proofs):
    """New frozen identity; never mutate an old request or pretend it was re-executed."""
    values = grouped.copied(candidates)
    for c in values:
        c['evidencePolicy'] = POLICY
        c['semanticSupport'] = {m['mentionId']: proofs[m['mentionId']]['requestDigest']
            for m in c['newMentions'] if matches(m, proofs.get(m['mentionId']))}
        c['asOfSnapshotSha256'] = base.digest(base.canonical({k: v for k, v in c.items() if k != 'asOfSnapshotSha256'}))
    return values


def eligible(candidate):
    grouped.require(candidate.get('evidencePolicy') == POLICY, 'semantic_evidence_policy_unknown')
    support = candidate.get('semanticSupport', {})
    return bool(candidate['newMentions']) and all(
        re.fullmatch('[0-9a-f]{64}', support.get(m['mentionId'], '')) is not None
        and m['evidence'] and all(e['quote'].strip() for e in m['evidence']) for m in candidate['newMentions'])
