"""An explicit source-gap bulletin reuses an authorized prior original, without calling a model."""
import copy
import json
import re
from datetime import datetime
from pathlib import Path
import briefing_server_runtime as runtime
from briefing_usage import CommandPipe, UsageSession, write_once

VERSION = 'briefing-coverage-notice-v1'
REASONS = {'no_current_company_source', 'all_company_candidates_withheld', 'remaining_shared_call_capacity', 'preparation_deadline'}


def record(cfg, round_, reason, now, outcome_file=None):
    runtime.require(reason in REASONS, 'coverage_notice_reason')
    root = Path(cfg['work']) / 'native' / round_['id']
    pins = {'source-coverage.json': runtime.b.digest((root / 'source-coverage.json').read_bytes())}
    if reason != 'no_current_company_source':
        name = outcome_file or 'candidate-outcomes-v3.json'
        runtime.require(name == 'candidate-outcomes-v3.json' or re.fullmatch(r'candidates-v3/outcomes-[a-f0-9]{16}\.json', name), 'coverage_outcome_path')
        pins[name] = runtime.b.digest((root / name).read_bytes())
    value = {'schemaVersion': VERSION, 'round': round_, 'reason': reason,
             'recordedAt': now.isoformat(), 'files': pins}
    path = root / 'coverage-notice.json'
    if path.exists():
        old = json.loads(path.read_bytes())
        runtime.require(all(old[k] == value[k] for k in ('schemaVersion', 'round', 'reason', 'files')), 'coverage_notice_changed')
    else:
        runtime.require(datetime.fromisoformat(round_['windowFrom']) < now <= datetime.fromisoformat(round_['windowTo']), 'coverage_notice_after_cutoff')
        write_once(path, value)
    return runtime.b.digest(path.read_bytes())


def produce(cfg, job):
    r = {'id': job['id'], 'date': str(job['round_date']), 'edition': job['edition'],
         'scheduledAt': job['scheduled_at'].isoformat(), 'windowFrom': job['window_from'].isoformat(),
         'windowTo': job['scheduled_at'].isoformat()}
    work = Path(cfg['work']) / r['id'] / 'coverage-notice'
    work.mkdir(mode=0o700, parents=True, exist_ok=True)
    prepared = runtime.java(cfg, 'prepare-coverage', {'round': r, 'noticeSha256': cfg['coverageNoticeSha256']}, work / 'prepare.request.json')
    runtime.require(prepared['mode'] == VERSION and not prepared['candidates'], 'coverage_notice_binding')
    write_once(work / 'prepared.json', prepared)
    frozen = runtime.frozen_input(prepared)
    selection = {'selected': [], 'rejected': [], 'ranked': [], 'policyVersion': runtime.m.POLICY, 'inputSha256': frozen['inputSha256']}
    payload, snapshot, pool = runtime.make_publication(prepared, frozen, selection, [], [],
        {'assessments': {}}, {'checks': {}}, runtime.b.now(), cfg=cfg)
    snapshot['continuity'] = copy.deepcopy(prepared['continuity'])
    snapshot['coverageNotice'] = copy.deepcopy(prepared['coverageNotice'])
    snapshot['serverGeneration']['mode'] = VERSION
    payload['metadata']['selection'] = {'basis': 'market', 'reason': prepared['continuity']['message']}
    payload['metadata']['failures'].append({'section': 'collection', 'code': prepared['coverage']['reason'],
        'message': prepared['continuity']['message'], 'retryable': False, 'asOf': r['windowTo']})
    pool['priorityContract'] = 'priority-business-producer-v1'
    pool['inputSha256'] = runtime.b.digest(runtime.b.canonical({k: v for k, v in pool.items() if k != 'inputSha256'}))
    pipe = CommandPipe(cfg['ledgerCommand'])
    claim = {'round': r, 'requestKey': VERSION + '-' + prepared['inputSha256'], 'purpose': 'generation',
             'trigger': 'scheduler', 'adminId': None, 'inputArtifactId': None, 'inputDigest': prepared['inputSha256']}
    session = UsageSession(pipe, claim, work / 'usage')
    try:
        with session:
            runtime.require(not session.terminal, 'completed_result_requires_recovery')
            write_once(work / 'result.json', {'payload': payload, 'snapshot': snapshot, 'pool': pool})
            runtime.java(cfg, 'check', {'prepared': prepared}, work / 'check.request.json')
            session.send('heartbeat'); session.stop.set()
            if session.thread: session.thread.join(timeout=10)
            result = runtime.java(cfg, 'publish', {'prepared': prepared, 'payload': payload, 'snapshot': snapshot,
                'pool': pool, 'attemptId': session.owner['attemptId'], 'ownerToken': session.owner['ownerToken']}, work / 'publish.request.json')
            runtime.require(result['status'] == 'published' and result['roundId'] == r['id'], 'publication_proof')
            session.terminal = True
            write_once(work / 'published.json', result)
            return result
    finally:
        pipe.close()
