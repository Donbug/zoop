"""Offline revision-root and untouched-admission proof; no provider transport."""
from __future__ import annotations

import copy
import json
import os
import signal
import subprocess
from datetime import datetime, timezone
import sys
from pathlib import Path

import pytest

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE / 'scripts'))
import collection_revision as revision
from zoop_ai_pipeline import live_budget
from zoop_ai_pipeline.live_funding import run_policy


@pytest.fixture
def day(tmp_path, monkeypatch):
    root = tmp_path / 'day'
    previous = root / 'collection'
    previous.mkdir(parents=True)
    control = {'schemaVersion': 'zoop-private-run-4', 'funding': {'totalMaxUsd': '4', 'sharedMaxUsd': '3.5', 'personalMaxUsd': '0.5'}, 'runId': 'synthetic-revision', 'root': str(root),
               'admitFrom': '2026-10-28T00:00:00Z', 'admitUntil': '2026-10-28T08:30:00Z', 'finishBy': '2026-10-28T09:30:00Z',
               'graphPort': 32820, 'maxCalls': 100000,
               'processingActor': {'kind': 'user-private-experiment', 'acceptedBy': 'Main',
                                   'decidedAt': '2026-10-28T00:00:00Z', 'statement': 'Synthetic offline scope'}}
    path = root / 'run-config.json'
    revision.base.atomic(path, control)
    monkeypatch.setattr(live_budget, '_now', lambda: '2026-10-28T04:00:00+00:00')
    budget = live_budget.Budget(root / 'modelbudget', 4 * live_budget.NANO, 100000,
                               funding=run_policy(control), bucket_caps={'shared': 3_500_000_000, 'personal': 500_000_000},
                               finish_by=control['finishBy'])
    budget.admit_set('acquisition:old', 'a' * 64, {'fetch': 2, 'search': 0})
    budget.reserve('unresolved-old-fetch', 'fetch', 'deepseek-fetch', 'b' * 64, 750000,
                   account_role='personal-deepseek', set_id='acquisition:old')
    budget.finish_set('acquisition:old', 'unknown')
    return root, previous, control, revision.pinned(path), budget


def test_revision_root_keeps_original_funding_configuration(day):
    root, previous, control, pin, _ = day
    target = root / 'collection-revisions' / 'r2'
    selected_previous, selected_target, selected_control = revision.scope(previous, target, pin, control['admitUntil'])
    assert selected_previous == previous and selected_target == target
    assert selected_control == control
    with pytest.raises(ValueError, match='revision_namespace'):
        revision.scope(previous, root.parent / 'another-run', pin, control['admitUntil'])


def test_budget_snapshot_preserves_unknown_reservation_and_original_file(day):
    _, _, control, _, budget = day
    before = revision.base.sha(budget.path)
    observed = revision.budget_snapshot(control)
    assert observed['sets']['acquisition:old']['state'] == 'unknown'
    assert observed['reservations'] == [{'attemptId': 'unresolved-old-fetch', 'setId': 'acquisition:old',
                                        'state': 'reserved', 'chargedNano': 750000}]
    assert observed['admissionStop'] is None
    assert revision.base.sha(budget.path) == before


def test_only_unstarted_unmaterialized_unadmitted_plan_is_eligible(day):
    root, previous, control, _, _ = day
    plan = {'id': 'new', 'configTemplate': {'stateDir': str(previous / 'state/new')},
            'funding': {'setId': 'acquisition:new'}}
    record = {'status': 'not_started', 'reasonCode': 'controller_failure_drain'}
    monetary = revision.budget_snapshot(control)
    assert revision.untouched(previous, plan, record, monetary)
    assert not revision.untouched(previous, plan, record | {'startedAt': 'known-start'}, monetary)
    assert not revision.untouched(previous, plan, record | {'status': 'unknown'}, monetary)
    admitted = copy.deepcopy(plan)
    admitted['funding']['setId'] = 'acquisition:old'
    assert not revision.untouched(previous, admitted, record, monetary)
    revision.base.atomic(previous / 'configs/new.exclusions.json', {})
    assert not revision.untouched(previous, plan, record, monetary)


def test_child_environment_uses_r2_pipeline_and_worker_without_extra_keys(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-must-not-forward')
    monkeypatch.setenv('OPENDART_API_KEY', 'synthetic-must-not-forward')
    env = revision.child_env()
    assert env['PYTHONPATH'].split(':') == [str(revision.SOURCE_ROOT / 'ai/pipeline/src'),
                                           str(revision.SOURCE_ROOT / 'ai/worker/src')]
    assert 'OPENAI_API_KEY' not in env and 'OPENDART_API_KEY' not in env


@pytest.fixture
def frozen_day(day):
    root, previous, control, pin, budget = day
    from zoop_ai_pipeline.news_sources import source_descriptors

    options = {'fundingConfig': pin, 'stopNewWorkAt': control['admitUntil'], 'approvalRef': 'synthetic-old',
               'finishBy': control['finishBy'],
               'freshFromDay': '2026-10-28', 'throughDay': '2026-10-28', 'fromDay': '2026-07-28',
               'setRequests': 2000, 'setBytes': 160_000_000, 'setSeconds': 1800,
               'caps': {'requests': 100000, 'bytes': 10_000_000_000}, 'minFreeBytes': 0, 'concurrency': 2}
    rows = [row for row in revision.base.source_matrix([s.wire() for s in source_descriptors()])
            if row['sourceId'] in {'fnnews-sitemaps', 'amazon-newsroom'}]
    plans = revision.base.build_plans(rows, previous, options, {}, [], {})
    for plan in plans:
        config = plan['configTemplate']
        config['policy'].pop('maxDiscoveryResponseBytes', None)
        plan['ceilings']['bytes'] = 162_000_000
        for source in config['sources']:
            if source.get('descriptor'):
                source['descriptor']['publicationMeta'] = ['article:published_time']
        revision.base.attach_fallback(plan, previous, options)
    unknown = copy.deepcopy(plans[0])
    unknown.update(id='old-unknown')
    unknown['configTemplate'].update(planId=unknown['id'], stateDir=str(previous / 'state/old-unknown'))
    unknown['configTemplate'].pop('fallback')
    unknown.pop('funding')
    plans.append(unknown)
    for name, value in {
        'PRIOR_EXCLUSIONS': revision.base.frozen_exclusions(revision.base.exclusion_sets()),
        'REUSED_CORPUS': {'nativeItems': [], 'privateItems': [], 'reusedCorpus': [], 'errors': []},
        'RIGHTS': {}, 'ROUTES': {},
    }.items():
        revision.base.atomic(previous / 'evidence' / (name + '.json'), value)
    manifest = {'runId': control['runId'], 'sourcePins': revision.base.source_pins(),
                'options': options, 'plans': plans, 'sourceMatrix': rows,
                'priorExclusions': revision.pinned(previous / 'evidence/PRIOR_EXCLUSIONS.json'),
                'reusedCorpus': revision.pinned(previous / 'evidence/REUSED_CORPUS.json'),
                'rightsEvidence': revision.pinned(previous / 'evidence/RIGHTS.json'),
                'routeResearch': revision.pinned(previous / 'evidence/ROUTES.json')}
    revision.base.atomic(previous / 'PLAN.json', manifest)
    ledger = {'planSha256': revision.base.sha(previous / 'PLAN.json'), 'startedAt': '2026-10-28T03:00:00Z',
              'endedAt': '2026-10-28T04:00:00Z', 'closedReason': 'controller_failure_drain',
              'held': {'requests': 7, 'bytes': 13}, 'spent': {'requests': 11, 'bytes': 17},
              'plans': {p['id']: {'status': 'not_started', 'reasonCode': 'controller_failure_drain'} for p in plans}}
    ledger['plans']['old-unknown'] = {'status': 'unknown', 'reasonCode': 'previous_dispatch_outcome_unknown',
                                    'startedAt': '2026-10-28T03:00:00Z', 'endedAt': '2026-10-28T04:00:00Z',
                                    'durationMs': 3_600_000}
    revision.base.atomic(previous / 'LEDGER.json', ledger)
    revision.base.publish_index(previous, manifest, ledger)
    (previous / '.controller.lock').touch()
    return root, previous, control, pin, budget


def invoke_revision(*arguments, expected=0):
    command = [sys.executable, '-B', str(PIPELINE / 'scripts/collection_revision.py'), *map(str, arguments)]
    result = subprocess.run(command, env=revision.child_env(), capture_output=True, text=True, timeout=120)
    assert result.returncode == expected, (command, result.stdout, result.stderr)
    return json.loads(result.stdout)


def simulate_drained_revision(root):
    # Synthetic controller evidence, not a way to mark any actual run as drained.
    manifest = revision.base.load(root / 'PLAN.json')
    ledger = revision.base.load(root / 'LEDGER.json')
    metadata = revision.base.load(root / 'REVISION.json')
    for identifier in metadata['eligibleUntouchedPlanIds']:
        ledger['plans'][identifier] = {'status': 'not_started', 'reasonCode': 'revision_checkpoint_drain'}
    ledger.update(startedAt='2026-10-28T04:01:00Z', endedAt='2026-10-28T04:02:00Z',
                  closedReason='revision_checkpoint_drain')
    revision.base.atomic(root / 'LEDGER.json', ledger)
    revision.base.publish_index(root, manifest, ledger)
    (root / '.controller.lock').touch()


def prepare_chain(frozen_day):
    root, previous, control, pin, budget = frozen_day
    r2, r3 = (root / 'collection-revisions' / name for name in ('r2', 'r3'))
    invoke_revision('prepare', '--previous-root', previous, '--revision-root', r2,
                    '--approval-ref', 'synthetic-r2', '--expected-new-records', 0)
    simulate_drained_revision(r2)
    invoke_revision('prepare', '--previous-root', r2, '--revision-root', r3,
                    '--approval-ref', 'synthetic-r3', '--expected-new-records', 0)
    return r2, r3


def test_actual_revision_cli_preserves_r1_r2_pins_and_shared_unknown_budget(frozen_day):
    root, previous, control, pin, budget = frozen_day
    original = {name: (previous / name).read_bytes() for name in ('PLAN.json', 'LEDGER.json', 'INDEX.json')}
    monetary = revision.budget_snapshot(control)
    r2, r3 = prepare_chain(frozen_day)
    old = {name: (r2 / name).read_bytes() for name in original}
    checked = invoke_revision('check', '--revision-root', r3)
    assert checked == {'passed': True, 'network': 'none', 'configCount': 2}
    manifest, ledger, metadata, selected_previous, selected_control = revision.validate_revision(r3)
    assert selected_previous == r2 and selected_control == control
    assert metadata['collectionChain'] == [
        {name: revision.pinned(folder / name) for name in original} for folder in (previous, r2)]
    assert metadata['budgetPath'] == str(root / 'modelbudget/live-budget.sqlite3')
    assert metadata['pacingRoot'] == str(previous / 'fetch-pacing')
    assert metadata['preservedUnknownPlanIds'] == ['old-unknown']
    assert metadata['preservedReservedAttempts'] == monetary['reservations']
    assert ledger['held'] == {'requests': 7, 'bytes': 13}
    assert ledger['spent'] == {'requests': 11, 'bytes': 17}
    assert ledger['plans']['old-unknown']['status'] == 'unknown'
    assert revision.budget_snapshot(control) == monetary
    assert {name: (previous / name).read_bytes() for name in original} == original
    assert {name: (r2 / name).read_bytes() for name in old} == old
    for plan in manifest['plans']:
        if plan['id'] not in metadata['eligibleUntouchedPlanIds']:
            assert plan['configTemplate']['stateDir'].startswith(str(previous))
            continue
        assert plan['configTemplate']['stateDir'].startswith(str(r3))
        if plan['sourceId'] == 'fnnews-sitemaps':
            assert plan['configTemplate']['policy']['maxDiscoveryResponseBytes'] == 10_000_000
            assert plan['configTemplate']['policy']['maxResponseBytes'] == 2_000_000
            assert plan['configTemplate']['policy']['maxTotalBytes'] == 160_000_000
            assert plan['configTemplate']['policy']['minIntervalSeconds'] == 2
        else:
            assert plan['configTemplate']['sources'][0]['descriptor']['publicationMeta'] == [
                'parsely-pub-date', 'article:published_time']
    # An altered original ancestor cannot be concealed by an intact immediate R2 pin.
    revision.base.atomic(previous / 'INDEX.json', {'tampered': True})
    with pytest.raises(ValueError, match='chain_mismatch|pin_changed'):
        revision.validate_revision(r3)


@pytest.mark.parametrize('case', ['running', 'busy', 'wrong-parent', 'same-root', 'outside'])
def test_revision_prepare_refuses_unproven_or_busy_predecessor_without_new_namespace(frozen_day, case):
    root, previous, control, pin, _ = frozen_day
    target = root / 'collection-revisions/r2'
    lock = None
    try:
        if case == 'running':
            ledger = revision.base.load(previous / 'LEDGER.json')
            ledger['endedAt'] = None
            revision.base.atomic(previous / 'LEDGER.json', ledger)
        elif case == 'busy':
            lock = revision.lock_existing(previous / '.controller.lock', exclusive=True)
        elif case == 'wrong-parent':
            previous = root / 'collection-revisions/unregistered'
            previous.mkdir(parents=True)
        elif case == 'same-root':
            target = previous
        else:
            target = root.parent / 'arbitrary'
        with pytest.raises((ValueError, FileNotFoundError, BlockingIOError)):
            revision.prepare(previous, target, 'synthetic-denied', 0)
        if case != 'same-root':
            assert not target.exists()
    finally:
        if lock is not None:
            os.close(lock)


@pytest.mark.parametrize('reason', ['fallback_admission_mismatch', 'resource_budget_exhausted',
                                  'fallback_budget_live_set_work_exhausted', 'previous_dispatch_outcome_unknown'])
def test_revision_never_relabels_arbitrary_failure_as_untouched(day, reason):
    _, previous, control, _, _ = day
    plan = {'id': 'new', 'configTemplate': {'stateDir': str(previous / 'state/new')}}
    assert not revision.untouched(previous, plan, {'status': 'not_started', 'reasonCode': reason},
                                  revision.budget_snapshot(control))


@pytest.mark.parametrize('sig,reason,global_stop', [
    (signal.SIGUSR1, 'revision_checkpoint_drain', False),
    (signal.SIGTERM, 'operator_soft_stop', True),
])
def test_revision_local_checkpoint_is_not_global_budget_stop(frozen_day, monkeypatch, sig, reason, global_stop):
    _, _, control, _, _ = frozen_day
    r2, r3 = prepare_chain(frozen_day)
    revision.check(r3)
    original_execute = revision.base.execute

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 28, 4, 5, tzinfo=timezone.utc)

    def signalled(*args, **kwargs):
        os.kill(os.getpid(), sig)
        # A later checkpoint signal must not erase an explicit global stop.
        if global_stop:
            os.kill(os.getpid(), signal.SIGUSR1)
        return original_execute(*args, **kwargs, now=Clock.now)

    monkeypatch.setattr(revision, 'datetime', Clock)
    monkeypatch.setattr(revision.base, 'execute', signalled)
    before = revision.budget_snapshot(control)
    revision.run(r3, 'synthetic-no-dispatch', None, None)
    after = revision.budget_snapshot(control)
    assert after['sets'] == before['sets'] and after['reservations'] == before['reservations']
    assert (after['admissionStop'] is not None) is global_stop
    ledger = revision.base.load(r3 / 'LEDGER.json')
    assert ledger['closedReason'] == reason and ledger['endedAt'] is not None
    assert not list((r3 / 'logs').iterdir())
    if global_stop:
        assert after['admissionStop'][0] == 'operator_soft_stop'


def test_shared_admission_stop_is_never_reopened_by_successor(frozen_day, monkeypatch):
    _, _, _, _, budget = frozen_day
    _, r3 = prepare_chain(frozen_day)
    revision.check(r3)
    budget.close_admission('operator_soft_stop')

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 28, 4, 5, tzinfo=timezone.utc)

    monkeypatch.setattr(revision, 'datetime', Clock)
    with pytest.raises(ValueError, match='shared_admission_stop_preserved'):
        revision.run(r3, 'synthetic-refusal', None, None)
    assert revision.base.load(r3 / 'LEDGER.json')['startedAt'] is None
