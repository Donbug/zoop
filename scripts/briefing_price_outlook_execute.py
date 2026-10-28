#!/usr/bin/env python3
"""Execute prepared v5 inputs with immutable receipts and sequential verified history.

Transport is injected by a separately bounded credential/budget launcher. There is
no implicit retry of a pending request, no baseline mutation, and no publication of
an unverified draft.
"""
import copy
from pathlib import Path
import briefing_price_aware_prompt as prompt

company, base = prompt.company, prompt.base
SCHEMA = 'zoop-ai-price-outlooks-v1'


def sequential(frozen, history):
    f = copy.deepcopy(frozen)
    for t in f['targets']:
        previous = company.previous_for(t['companyId'], f['date'], f['edition'], history, strict=True)
        if previous['status'] == 'available': previous['kind'] = 'verified_ai_price_outlook'
        # The first round can retain an explicitly identified editorial previous
        # judgment. Subsequent rounds use only the newly verified matching round.
        if history or previous['status'] == 'available': t['previous'] = previous
    f.pop('inputSha256', None)
    f['inputSha256'] = base.digest(base.canonical(f))
    return f


def run(prepared, output, transport, maximum_calls=16):
    prepared, output = Path(prepared).resolve(), Path(output).resolve()
    prompt.require(output != prepared and prepared not in output.parents and output not in prepared.parents, 'separate_execution')
    prompt.require(8 <= maximum_calls <= 16, 'execution_limit')
    paths = list(prepared.glob('*.input.json'))
    inputs = [base.strict_load(base.regular(p)) for p in paths]
    inputs.sort(key=lambda f: company.context.legacy._aware(f['cutoff']))
    prompt.require(len(inputs) == 4 and len({f['roundId'] for f in inputs}) == 4, 'four_rounds')
    for f in inputs:
        original = copy.deepcopy(f); sha = original.pop('inputSha256')
        prompt.require(sha == base.digest(base.canonical(original)) and f['promptVersion'] == prompt.VERSION, 'prepared_input_hash')
    identity = {'schemaVersion': SCHEMA, 'model': base.MODEL, 'maximumNewCalls': maximum_calls,
                'inputs': [f['inputSha256'] for f in inputs],
                'prompts': {name: base.digest(base.regular(prepared/name)) for name in ('generation.md', 'verification.md')}}
    for name in identity['prompts']:
        prompt.require(base.regular(prepared/name) == base.regular(prompt.PROMPTS/name), 'prompt_changed')
    base.private_dir(output); base.private_dir(output/'rounds')
    lock = output/'.execution.lock'
    import os
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
    try:
        base.write_once(output/'execution.json', base.canonical(identity))
        client = company.context.legacy.MarketSummaryClient(output, transport, maximum_calls, prompt_root=prepared)
        history = []
        for original in inputs:
            frozen = sequential(original, history)
            path = output/'rounds'/(frozen['date']+'-'+frozen['edition']+'.json')
            if path.exists():
                result = base.strict_load(base.regular(path))
                prompt.require(result['frozen'] == frozen, 'resume_changed_input')
            else:
                result = company.assess(client, frozen)
                result.update(roundId=frozen['roundId'], date=frozen['date'], edition=frozen['edition'], cutoff=frozen['cutoff'],
                              frozen=frozen, generatedAt=base.now())
                result['resultVersion'] = 'ai-price-v1-'+base.digest(base.canonical(result))
                base.write_once(path, base.canonical(result))
            history.append(result)
            print(base.canonical({'round': frozen['date']+'-'+frozen['edition'], 'status': result['status'],
                                 'companies': len(frozen['targets']), 'newCalls': len(client.new_calls)}).decode(), flush=True)
        layer = {'schemaVersion': SCHEMA, 'model': base.MODEL, 'promptVersion': prompt.VERSION,
                 'rounds': history, 'receipts': client.receipts()}
        base.write_once(output/'ai-price-layer.json', base.canonical(layer))
        receipts = layer['receipts']
        proof = {'status': 'COMPLETE', 'pass': sum(r['status']=='PASS' for r in history), 'rounds': len(history),
                 'newPaidCalls': len(client.new_calls), 'reservations': len(receipts),
                 'inputTokens': sum(r['inputTokens'] for r in receipts if r['usageKnown']),
                 'outputTokens': sum(r['outputTokens'] for r in receipts if r['usageKnown']),
                 'layerSha256': base.digest(base.canonical(layer)), 'model': base.MODEL, 'promptVersion': prompt.VERSION}
        base.write_once(output/'proof.json', base.canonical(proof)); return proof
    finally: lock.unlink()
