"""Opt-in fresh-round producer; depends on the fenced server runtime, never a demo importer.

No deployment activation here. The common queue invokes this command once per frozen slot.
"""
import argparse
import copy
import json
from datetime import datetime
from pathlib import Path
import briefing_priority_generation as priority
import briefing_issue_intelligence as m
import briefing_issue_intelligence_view as view
import briefing_selected_generation as selected_view
from briefing_usage import CommandPipe, recorded, write_once
b = m.base


def priority_selection(frozen, assessed, checked, core):
    # The original core call keeps its threshold of 2. Relative cards admit 1,
    # with the same deduplication/ranking and the actual score left unchanged.
    ranked = m.select(frozen, assessed, checked, frozen.get('previousSelected', []), minimum_importance=1)
    return {**core, 'selected': ranked['selected']}


def attach(payload, snapshot, pool, common, personal, summary, records, calls, *, shared_personal=False):
    # Private proofs/records remain in the immutable snapshot, not the read DTO.
    common_proof = priority.prove(common, calls)
    personal_proof = priority.prove(personal, calls)
    summary_proof = priority.prove_summary(summary[0], calls)
    snapshot['commonPriority'] = priority.common_view(common, pool['candidateCount'])
    snapshot['prioritySummary'] = summary[1]
    snapshot['serverGeneration']['priority'] = {'version': priority.VERSION,
        'common': common, 'personal': personal, 'summary': summary[0],
        'proofs': {'common': common_proof, 'personal': personal_proof, 'summary': summary_proof}}
    if shared_personal:
        snapshot['serverGeneration']['priority']['personalReuse'] = {
            'version': 'literal-common-personal-projection-v1', 'sourceResultVersion': common['resultVersion'],
            'generationRequestDigest': common_proof['generationRequestDigest'],
            'verificationRequestDigest': common_proof['verificationRequestDigest']}
    by_id = {r['issueId']: r for r in records}
    for candidate in pool['candidates']:
        candidate['priorityAnalysisInput'] = priority.priority_input(candidate['analysisInput'])
        record = by_id.get(candidate['issueId'])
        if record is not None:
            candidate['sharedView'] = selected_view.materialize(record, payload['metadata'], payload['generatedAt'])
            candidate['sharedView']['priorityPersonal'] = (priority.shared_personal_item(common, candidate['issueId'], calls)
                if shared_personal else priority.item(personal, candidate['issueId']))
    pool['priorityContract'] = priority.VERSION
    pool['inputSha256'] = b.digest(b.canonical({k: v for k, v in pool.items() if k != 'inputSha256'}))
    cards = snapshot['commonPriority']['items']
    for key, values in [('eventIds', [i['issueId'] for i in cards]),
                        ('evidenceIds', [s['evidenceId'] for i in cards for s in i['sources']]),
                        ('companyIds', [c['companyId'] for i in cards for c in i['companies']])]:
        payload['references'][key] = sorted(set(payload['references'][key]) | set(values))
    return payload, snapshot, pool


def produce(cfg, job):
    # Import only on execution; unit/schema tests cannot initialize provider or DB resources.
    import briefing_server_runtime as runtime
    runtime.require(cfg.get('priorityContract') == priority.VERSION, 'priority_opt_in')
    work = Path(cfg['work']) / job['id']; work.mkdir(mode=0o700, exist_ok=True)
    r = {'id': job['id'], 'date': str(job['round_date']), 'edition': job['edition'],
         'scheduledAt': job['scheduled_at'].isoformat(), 'windowFrom': job['window_from'].isoformat(),
         'windowTo': job['scheduled_at'].isoformat()}
    request = {'round': r}
    if cfg.get('recordedRecoveryAuthorization'):
        request['recordedRecovery'] = True
    prepared = runtime.java(cfg, 'prepare', request, work / 'prepare.request.json')
    runtime.require(not cfg.get('expectedGraphVersion') or prepared['graphVersion']==cfg['expectedGraphVersion'],'admitted_graph_changed')
    write_once(work / 'prepared.json', prepared)
    frozen = runtime.frozen_input(prepared); write_once(work / 'frozen.json', frozen)
    def current():
        runtime.java(cfg, 'check', {'prepared': prepared}, work / 'check.request.json')
    # Distinct request identity from older producer revisions; terminal slots remain immutable.
    claim = {'round': r, 'requestKey': priority.VERSION + '-' + prepared['inputSha256'],
             'purpose': 'generation', 'trigger': 'scheduler', 'adminId': None,
             'inputArtifactId': None, 'inputDigest': prepared['inputSha256']}
    pipe = CommandPipe(cfg['ledgerCommand'])
    class Usage(runtime.ServerUsageSession):
        def invoke(self, stage, encoded, transport):
            if stage.startswith('priority-'): self.feature = 'briefing-outlook'; self.unit = None
            return super().invoke(stage, encoded, transport)
        def replay(self, stage, call):
            if stage.startswith('priority-'): self.feature = 'briefing-outlook'; self.unit = None
            return super().replay(stage, call)
    session = Usage(pipe, claim, work / 'model' / 'usage', estimate={
        'currency': 'USD', 'priceVersion': 'openai-luna-standard-20261103',
        'inputPerMillion': 0.10, 'outputPerMillion': 0.50})
    session.budget = runtime.Budget(cfg, r['id'], current, b.authenticated_transport(Path(cfg['keyFile'])))
    client = runtime.RecordedClient(work / 'model', session.budget.transport, 16, prompt_root=m.PROMPTS)
    try:
        with recorded(client, session):
            runtime.require(not session.terminal, 'completed_result_requires_recovery')
            if frozen['candidates']:
                assessed, checked, _ = m.assess_candidates(client, frozen)
                core = m.select(frozen, assessed, checked, prepared.get('previous', {}).get('selected', []))
                chosen = priority_selection(frozen, assessed, checked, core)
            else:
                assessed, checked = {'assessments': {}}, {'checks': {}}
                core = chosen = {'selected': [], 'rejected': [], 'ranked': [], 'policyVersion': m.POLICY, 'inputSha256': frozen['inputSha256']}
            targets = m.analysis_inputs(frozen, chosen, prepared.get('previous', {}).get('records', []))
            draft, verdict, attempts = m.analyze(client, targets) if targets else ({'issues': {}}, {'checks': {}}, [])
            write_once(work / 'analysis-attempts.json', attempts)
            records = []
            for f in targets:
                iid = f['issueId']; runtime.require(verdict['checks'][iid]['supported'], 'selected_issue_withheld')
                row = {**{k: f[k] for k in ('roundId', 'date', 'edition', 'cutoff', 'issueId')},
                    'status': 'PASS', 'frozen': f, 'draft': draft['issues'][iid], 'verification': verdict['checks'][iid]}
                row['resultVersion'] = m.VERSION + '-' + b.digest(b.canonical(row)); records.append(row)
            if targets:
                common = priority.generate(client, targets, 'common')
                personal = common if cfg.get('sharePriorityAnalysis') else priority.generate(client, targets, 'personal')
                summary = priority.summary(client, common)
            calls = priority.verified_calls(work / 'model')
            core_ids = {i['issueId'] for i in core['selected']}
            payload, snapshot, pool = runtime.make_publication(prepared, frozen, core,
                [r for r in records if r['issueId'] in core_ids], calls, assessed, checked, b.now(),cfg=cfg)
            if targets:
                attach(payload, snapshot, pool, common, personal, summary, records, calls,
                    shared_personal=cfg.get('sharePriorityAnalysis') is True)
            else:
                pool['priorityContract'] = priority.VERSION
            write_once(work / 'result.json', {'payload': payload, 'snapshot': snapshot, 'pool': pool})
            current(); session.send('heartbeat'); session.stop.set()
            if session.thread: session.thread.join(timeout=10)
            result = runtime.java(cfg, 'publish', {'prepared': prepared, 'payload': payload, 'snapshot': snapshot,
                'pool': pool, 'attemptId': session.owner['attemptId'], 'ownerToken': session.owner['ownerToken']}, work / 'publish.request.json')
            runtime.require(result['status'] == 'published' and result['roundId'] == r['id'], 'publication_proof')
            session.terminal = True; write_once(work / 'published.json', result)
            return result
    finally:
        pipe.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, required=True)
    for k in ('round-id', 'date', 'edition', 'cutoff', 'window-from'): p.add_argument('--' + k, required=True)
    args = p.parse_args()
    priority.c.require(not args.config.is_symlink() and args.config.stat().st_mode & 0o077 == 0, 'priority_private_config')
    cfg = json.loads(args.config.read_bytes())
    priority.c.require(cfg.get('enabled') is True and cfg.get('priorityContract') == priority.VERSION, 'priority_opt_in')
    root = Path(cfg['work']); root.mkdir(mode=0o700, parents=True, exist_ok=True)
    priority.c.require(not root.is_symlink() and root.stat().st_mode & 0o077 == 0, 'priority_private_work')
    job = {'id': args.round_id, 'round_date': args.date, 'edition': args.edition,
           'scheduled_at': datetime.fromisoformat(args.cutoff), 'window_from': datetime.fromisoformat(args.window_from)}
    produce(cfg, job)

if __name__ == '__main__': main()
