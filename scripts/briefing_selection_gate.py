"""Pre-cutoff importance/freshness gate. Exact completed requests are reused at publication.

This gate never publishes, lowers an evidence threshold or upgrades a withheld relation.
The Java preview boundary verifies the queued slot, source clocks and current authority.
"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import briefing_call_limits as limits
import briefing_server_runtime as runtime
import briefing_issue_intelligence as intelligence
from briefing_usage import CommandPipe, recorded, write_once

VERSION = 'briefing-selection-gate-v1'


def same_round(left, right):
    return (all(left.get(k) == right.get(k) for k in ('id', 'date', 'edition'))
            and all(datetime.fromisoformat(left[k]) == datetime.fromisoformat(right[k])
                    for k in ('scheduledAt', 'windowFrom', 'windowTo')))


def dispatch_window(round_):
    # Leave a full transport timeout plus a margin to record an honest pre-cutoff notice.
    runtime.require(datetime.now(timezone.utc) + timedelta(seconds=190)
                    < datetime.fromisoformat(round_['windowTo']), 'selection_dispatch_deadline')


def qualify(cfg, round_, candidate_root, graph_version):
    root = Path(candidate_root) / 'selection'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (root / 'qualification.json').is_file():
        proof=json.loads((root / 'qualification.json').read_bytes())
        prepared=json.loads((root / 'prepared.json').read_bytes())
        runtime.require(proof['schemaVersion']==VERSION and proof['roundId']==round_['id']
                        and same_round(prepared['round'], round_) and prepared['graphVersion']==graph_version
                        and proof['preparedSha256']==runtime.b.digest((root/'prepared.json').read_bytes())
                        and proof['frozenInputSha256']==runtime.frozen_input(prepared)['inputSha256'],
                        'saved_qualification_changed')
        runtime.java(cfg,'check',{'prepared':prepared},root/'check.request.json')
        return {'status':'ready' if proof['selectedIssueIds'] else 'withheld',
                'reason':None if proof['selectedIssueIds'] else 'selection_no_fresh_priority_issue',
                'preparedFile':str(root/'prepared.json'),'producerWork':str(root),
                'qualificationSha256':runtime.b.digest((root/'qualification.json').read_bytes())}
    dispatch_window(round_)
    prepared = runtime.java(cfg, 'prepare-selection', {'round': round_}, root / 'prepare.request.json')
    runtime.require(prepared.get('selectionPreview') is True and prepared['graphVersion'] == graph_version,
                    'selection_preview_binding')
    write_once(root / 'prepared.json', prepared)
    frozen = runtime.frozen_input(prepared)
    write_once(root / 'frozen.json', frozen)
    def save_decision(eligible, attempts):
        value = {'schemaVersion': VERSION, 'roundId': round_['id'],
                 'preparedSha256': runtime.b.digest((root / 'prepared.json').read_bytes()),
                 'frozenInputSha256': frozen['inputSha256'],
                 'selectedIssueIds': [r['issueId'] for r in eligible['selected']],
                 'rejected': eligible['rejected'], 'attempts': attempts}
        write_once(root / 'qualification.json', value)
        return {'status': 'ready' if value['selectedIssueIds'] else 'withheld',
                'reason': None if value['selectedIssueIds'] else 'selection_no_fresh_priority_issue',
                'preparedFile': str(root / 'prepared.json'), 'producerWork': str(root),
                'qualificationSha256': runtime.b.digest((root / 'qualification.json').read_bytes())}
    if not frozen['candidates']:
        return save_decision({'selected': [], 'rejected': []}, [])
    claim = {'round': round_, 'requestKey': VERSION + '-' + prepared['inputSha256'], 'purpose': 'generation',
             'trigger': 'scheduler', 'adminId': None, 'inputArtifactId': None, 'inputDigest': prepared['inputSha256']}
    pipe = CommandPipe(cfg['ledgerCommand'])
    session = runtime.ServerUsageSession(pipe, claim, root / 'model' / 'qualification-usage')
    def current():
        runtime.java(cfg, 'check', {'prepared': prepared}, root / 'check.request.json')
        dispatch_window(round_)
    session.budget = runtime.Budget(cfg, round_['id'], current,
                                  runtime.b.authenticated_transport(Path(cfg['keyFile'])))
    client = runtime.RecordedClient(root / 'model', session.budget.transport, limits.round_limit(cfg),
                                    prompt_root=intelligence.PROMPTS)
    try:
        with recorded(client, session):
            runtime.require(not session.terminal, 'completed_selection_requires_saved_qualification')
            assessed, checked, attempts = intelligence.assess_candidates(client, frozen)
            eligible = intelligence.select(frozen, assessed, checked, frozen.get('previousSelected', []),
                                            minimum_importance=1)
            session.outcome = 'available' if eligible['selected'] else 'withheld'
        # A qualification checkpoint is reusable only after its ledger owner completed.
        return save_decision(eligible, attempts)
    finally:
        pipe.close()


def prepared_for_publication(cfg, round_):
    """No second assessment input: pin the exact preview that passed both requests."""
    requested = Path(cfg['qualifiedProducerWork'])
    root = requested.resolve()
    owned = (Path(cfg['work']) / 'native' / round_['id'] / 'candidates-v3').resolve()
    runtime.require(root.is_relative_to(owned) and not requested.is_symlink(), 'qualified_work_path')
    path = root / 'prepared.json'
    prepared = json.loads(path.read_bytes())
    proof = json.loads((root / 'qualification.json').read_bytes())
    runtime.require(proof['schemaVersion'] == VERSION and proof['roundId'] == round_['id']
                    and proof['preparedSha256'] == runtime.b.digest(path.read_bytes())
                    and proof['selectedIssueIds'] and same_round(prepared['round'], round_)
                    and prepared.get('selectionPreview') is True
                    and proof['frozenInputSha256'] == runtime.frozen_input(prepared)['inputSha256'],
                    'qualified_input_changed')
    runtime.java(cfg, 'check', {'prepared': prepared}, root / 'check.request.json')
    return root, prepared


def check_replayed_selection(root, selection):
    proof=json.loads((Path(root)/'qualification.json').read_bytes())
    runtime.require(proof['selectedIssueIds']==[r['issueId'] for r in selection['selected']],
                    'qualified_selection_changed')
