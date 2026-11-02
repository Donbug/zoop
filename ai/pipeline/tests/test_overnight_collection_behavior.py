"""Full-roster collection admission/receipt behavior; no paid calls or public HTTP.

The process-boundary doubles below control completion, never the dispatcher or
index implementation. The final test invokes the actual private collector CLI
with every origin pre-denied. Main runs this file after the shared source freeze.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading

import pytest

PIPELINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE))
from scripts import overnight_collect as collect


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 28, 8, 0, tzinfo=timezone.utc)
        self.ticks = 0
        self.on_sleep = None

    def now(self):
        return self.value

    def sleep(self, _):
        self.ticks += 1
        self.value += timedelta(seconds=1)
        if self.on_sleep:
            self.on_sleep(self)
        assert self.ticks < 50, 'dispatcher failed to drain finite synthetic work'


class ProcessBoundary:
    def __init__(self, clock, *, finishes=None, summaries=None, codes=None):
        self.clock = clock
        self.finishes = finishes or {}
        self.summaries = summaries or {}
        self.codes = codes or {}
        self.launched = []
        self.finished = []
        self.exclusions = {}
        self.start_ticks = {}
        self.environments = {}
        self.terminated = []

    def __call__(self, plan, root, config, exclusions, *, env=None):
        identifier = plan['id']
        self.launched.append(identifier)
        self.start_ticks[identifier] = self.clock.ticks
        self.exclusions[identifier] = collect.load(exclusions)
        self.environments[identifier] = env
        boundary = self
        terminal = self.clock.ticks + self.finishes.get(identifier, 1)

        class Child:
            pid = 50000 + len(boundary.launched)
            terminated = False

            def poll(self):
                if self.terminated:
                    return -15
                if boundary.clock.ticks < terminal:
                    return None
                return boundary.codes.get(identifier, 0)

            def terminate(self):
                self.terminated = True
                boundary.terminated.append(identifier)

            def result(self):
                boundary.finished.append(identifier)
                return boundary.summaries.get(identifier, complete_empty())

        return Child()


def complete_empty():
    return {'state': 'completed', 'coverage': 'all', 'sourceRequests': 1, 'sourceBytes': 10,
            'unknownRequests': 0, 'candidates': 0, 'retainedInWindow': 0, 'pendingCandidates': 0,
            'pendingPartitions': 0, 'saturatedPartitions': 0, 'partitionDispositions': {'done': 1}}


@pytest.fixture
def frozen(tmp_path):
    def create(hosts=('one.test', 'two.test', 'three.test'), concurrency=2):
        root = tmp_path / ('run-' + str(len(list(tmp_path.iterdir()))))
        for name in ('configs', 'state', 'logs', 'evidence'):
            (root / name).mkdir(parents=True)
        reused = {'nativeItems': [], 'privateItems': [], 'reusedCorpus': [], 'priorStates': [], 'errors': []}
        collect.atomic(root / 'evidence/REUSED_CORPUS.json', reused)
        collect.atomic(root / 'evidence/PRIOR_EXCLUSIONS.json', collect.frozen_exclusions(collect.exclusion_sets()))
        plans = [{'id': 'set-' + str(n), 'sourceId': 'source-' + str(n), 'rowId': 'source-' + str(n),
                  'kind': 'private', 'freshness': 'fresh', 'hosts': [host],
                  'configTemplate': {'planId': 'set-' + str(n), 'stateDir': str(root / 'state' / ('set-' + str(n)))},
                  'ceilings': {'requests': 10, 'bytes': 1000, 'seconds': 30}}
                 for n, host in enumerate(hosts)]
        manifest = {'runId': 'synthetic-full-source', 'plans': plans,
                    'sourceMatrix': [{'sourceId': p['sourceId'], 'kind': 'private', 'status': 'supported',
                                      'hosts': p['hosts'], 'reasonCode': None} for p in plans],
                    'sourcePins': {}, 'priorExclusions': collect.ref(root / 'evidence/PRIOR_EXCLUSIONS.json'),
                    'reusedCorpus': collect.ref(root / 'evidence/REUSED_CORPUS.json'),
                    'options': {'concurrency': concurrency, 'caps': {'requests': 1000, 'bytes': 100000},
                                'minFreeBytes': 0, 'stopNewWorkAt': '2026-10-28T17:30:00+09:00'}}
        collect.atomic(root / 'PLAN.json', manifest)
        ledger = {'planSha256': collect.sha(root / 'PLAN.json'), 'plans': {}, 'startedAt': None, 'endedAt': None,
                  'held': {'requests': 0, 'bytes': 0}, 'spent': {'requests': 0, 'bytes': 0},
                  'originReadyAt': {}, 'closedReason': None}
        collect.atomic(root / 'LEDGER.json', ledger)
        return root, manifest, ledger
    return create


def dispatch(fixture, clock, boundary):
    root, manifest, ledger = fixture
    return collect.execute(root, manifest, ledger, launch=boundary, now=clock.now,
                           sleep=clock.sleep, disk_free=lambda: 10**12)


def test_parallel_sources_start_before_either_finishes(frozen):
    fixture = frozen(concurrency=3)
    clock = Clock()
    boundary = ProcessBoundary(clock, finishes={'set-0': 4, 'set-1': 4, 'set-2': 4})
    dispatch(fixture, clock, boundary)
    assert boundary.start_ticks == {'set-0': 0, 'set-1': 0, 'set-2': 0}
    assert set(boundary.finished) == {'set-0', 'set-1', 'set-2'}
    index = collect.load(fixture[0] / 'INDEX.json')
    assert len(index['sourceMatrix']) == 3
    assert len(index['observations']) == 3
    assert all(row['status'] == 'empty' for row in index['sourceMatrix'])
    assert not (fixture[0] / 'events.jsonl').exists()


def test_shared_origin_serializes_without_blocking_other_origins(frozen):
    fixture = frozen(('same.test', 'same.test', 'independent.test'), concurrency=3)
    clock = Clock()
    boundary = ProcessBoundary(clock, finishes={'set-0': 3})
    dispatch(fixture, clock, boundary)
    assert boundary.start_ticks['set-0'] == boundary.start_ticks['set-2'] == 0
    assert boundary.start_ticks['set-1'] >= 5  # completion plus per-origin pacing


@pytest.mark.parametrize('soft_stop', [False, True])
def test_admission_stop_drains_finite_inflight_without_starting_next(frozen, soft_stop):
    fixture = frozen(concurrency=2)
    root, manifest, ledger = fixture
    clock = Clock()
    if soft_stop:
        clock.on_sleep = lambda _: (root / 'STOP').touch()
    else:
        manifest['options']['stopNewWorkAt'] = (clock.now() + timedelta(seconds=1)).isoformat()
    boundary = ProcessBoundary(clock, finishes={'set-0': 5, 'set-1': 6})
    dispatch(fixture, clock, boundary)
    assert boundary.launched == ['set-0', 'set-1']
    assert boundary.finished == ['set-0', 'set-1']
    assert clock.ticks == 6
    assert ledger['plans']['set-2']['status'] == 'not_started'
    assert ledger['plans']['set-2']['reasonCode'] == ('operator_soft_stop' if soft_stop else 'stop_new_deadline')
    assert ledger['plans']['set-0']['status'] == ledger['plans']['set-1']['status'] == 'finished'


def test_source_failure_isolated_and_unknown_reservation_not_reclaimed(frozen):
    fixture = frozen(concurrency=2)
    clock = Clock()
    boundary = ProcessBoundary(clock, summaries={'set-0': None}, codes={'set-0': -9})
    dispatch(fixture, clock, boundary)
    ledger = fixture[2]
    assert boundary.launched == ['set-0', 'set-1', 'set-2']
    assert ledger['plans']['set-0']['status'] == 'unknown'
    assert ledger['held'] == {'requests': 10, 'bytes': 1000}
    assert ledger['spent'] == {'requests': 2, 'bytes': 20}
    assert ledger['plans']['set-1']['status'] == ledger['plans']['set-2']['status'] == 'finished'


def test_unknown_source_never_retries_another_set_on_same_origin(frozen):
    fixture = frozen(('same.test', 'same.test', 'other.test'), concurrency=2)
    clock = Clock()
    boundary = ProcessBoundary(clock, summaries={'set-0': None}, codes={'set-0': -9})
    dispatch(fixture, clock, boundary)
    assert boundary.launched == ['set-0', 'set-2']
    assert fixture[2]['plans']['set-1']['reasonCode'] == 'origin_has_unsettled_dispatch_no_retry'


def test_exhausted_empty_and_zero_at_pagecap_are_not_conflated():
    plan = {'kind': 'private'}
    empty = collect.outcome(plan, {'status': 'finished', 'summary': complete_empty()})
    capped_summary = complete_empty() | {'state': 'partial', 'coverage': 'some', 'stopCode': 'listing_page_cap',
                                         'pendingPartitions': 1, 'saturatedPartitions': 1}
    capped = collect.outcome(plan, {'status': 'finished', 'summary': capped_summary})
    assert (empty['status'], empty['exhausted'], empty['limited']) == ('empty', True, False)
    assert (capped['status'], capped['exhausted'], capped['limited']) == ('partial', False, True)


def test_empty_fresh_pass_does_not_disable_backfill(frozen):
    fixture = frozen(('same.test', 'same.test'), concurrency=2)
    fixture[1]['plans'][1]['freshness'] = 'backfill'
    clock = Clock()
    boundary = ProcessBoundary(clock)
    dispatch(fixture, clock, boundary)
    assert boundary.launched == ['set-0', 'set-1']


def test_completed_restart_does_not_duplicate_dispatch_or_observations(frozen):
    fixture = frozen()
    clock = Clock()
    first = ProcessBoundary(clock)
    dispatch(fixture, clock, first)
    before = collect.load(fixture[0] / 'INDEX.json')
    restarted = ProcessBoundary(clock)
    dispatch(fixture, clock, restarted)
    after = collect.load(fixture[0] / 'INDEX.json')
    assert restarted.launched == []
    assert after['observations'] == before['observations']
    assert fixture[2]['spent'] == {'requests': 3, 'bytes': 30}


def test_reserved_restart_never_resends_and_holds_original_ceiling(frozen):
    fixture = frozen(('same.test', 'other.test'))
    root, manifest, ledger = fixture
    clock = Clock()
    ledger['plans']['set-0'] = {'status': 'reserved', 'startedAt': clock.now().isoformat(),
                              'ceilings': manifest['plans'][0]['ceilings']}
    ledger['held'] = {'requests': 10, 'bytes': 1000}
    boundary = ProcessBoundary(clock)
    dispatch(fixture, clock, boundary)
    assert boundary.launched == ['set-1']
    assert ledger['held'] == {'requests': 10, 'bytes': 1000}
    assert ledger['plans']['set-0']['status'] == 'unknown'
    assert collect.load(root / 'INDEX.json')['observations'][0]['status'] == 'unknown'


def test_usage_missing_is_not_a_zero_cost_receipt():
    ledger = {'held': {'requests': 10, 'bytes': 1000}, 'spent': {'requests': 0, 'bytes': 0}}
    plan = {'kind': 'private', 'ceilings': {'requests': 10, 'bytes': 1000}}
    record = {'status': 'finished', 'summary': {'state': 'refused', 'error': {'code': 'late_internal_error'}}}
    collect.settle(ledger, plan, record)
    assert ledger['held'] == {'requests': 10, 'bytes': 1000}
    assert 'reservationSettled' not in record


def test_atomic_index_reader_only_sees_complete_old_or_new_snapshot(tmp_path):
    path = tmp_path / 'INDEX.json'
    old = {'generation': 1, 'nativeItems': [], 'privateItems': [{'privateId': 'old'}]}
    new = {'generation': 2, 'nativeItems': [], 'privateItems': [{'privateId': str(i)} for i in range(3000)]}
    collect.atomic(path, old)
    failures = []
    done = threading.Event()

    def reader():
        while not done.is_set():
            try:
                value = json.loads(path.read_bytes())
                assert value in (old, new)
            except BaseException as exc:
                failures.append(exc)
                break

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        for _ in range(3):
            collect.atomic(path, new)
            collect.atomic(path, old)
        collect.atomic(path, new)
    finally:
        done.set()
        thread.join()
    assert not failures
    assert collect.load(path) == new
    assert not list(tmp_path.glob('*.stage-*'))


def test_atomic_publication_failure_preserves_previous_index(tmp_path, monkeypatch):
    path = tmp_path / 'INDEX.json'
    collect.atomic(path, {'generation': 'before'})
    original = path.read_bytes()

    def refuse_replace(source, destination):
        assert Path(destination) == path
        assert json.loads(Path(source).read_bytes()) == {'generation': 'after'}
        raise OSError('injected rename failure')

    monkeypatch.setattr(os, 'replace', refuse_replace)
    with pytest.raises(OSError, match='injected rename'):
        collect.atomic(path, {'generation': 'after'})
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_private_refs_pin_exact_record_bytes_and_do_not_rewrite_history(tmp_path):
    state = tmp_path / 'retained'
    state.mkdir()
    binding = {'config': {'planId': 'old-plan', 'sources': [{'name': 'hankyung-daily'}]}}
    collect.atomic(state / 'PLAN.json', binding)
    raw = b'<article>Preserved literal text</article>'
    identifier = 'private-news-' + 'a' * 64
    record = {'schemaVersion': 'zoop-private-news-record-1', 'privateId': identifier, 'source': 'hankyung-daily',
              'planDigest': hashlib.sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True,
                                                      separators=(',', ':')).encode()).hexdigest(),
              'rawSha256': hashlib.sha256(raw).hexdigest(), 'rawBytes': len(raw),
              'prepared': {'text': 'Preserved literal text'},
              'textSha256': hashlib.sha256(b'Preserved literal text').hexdigest(),
              'rights': 'unconfirmed', 'modelSend': False, 'publicUse': False}
    (state / (identifier + '.raw')).write_bytes(raw)
    path = state / (identifier + '.json')
    path.write_bytes(json.dumps(record, ensure_ascii=False, indent=3).encode() + b'\n\n')
    original = {p.name: p.read_bytes() for p in state.iterdir()}
    items = collect.private_items(state)
    assert items == [{'sourceId': 'hankyung-daily', 'stateDir': str(state), 'recordPath': str(path),
                      'recordSha256': hashlib.sha256(original[path.name]).hexdigest(), 'privateId': identifier, 'planId': 'old-plan'}]
    assert {p.name: p.read_bytes() for p in state.iterdir()} == original
    assert set(items[0]) == {'sourceId', 'stateDir', 'recordPath', 'recordSha256', 'privateId', 'planId'}


def test_disk_queue_exclusions_preserve_attempted_unknown_and_host_delay(tmp_path):
    state = tmp_path / 'retained'
    state.mkdir()
    collect.atomic(state / 'PLAN.json', {'config': {'planId': 'old-plan'}})
    data = {'candidates': 'sqlite:candidates', 'tasks': 'sqlite:tasks', 'attempts': 'sqlite:attempts',
            'blocked': ['denied.test'], 'delays': {'slow.test': 35}, 'pendingRequest': None}
    collect.atomic(state / 'STATE.json', {'state': data})
    db = sqlite3.connect(state / 'QUEUE.sqlite3')
    for table in ('candidates', 'tasks', 'attempts'):
        db.execute('CREATE TABLE ' + table + '(value TEXT)')
    db.executemany('INSERT INTO candidates VALUES(?)', [(json.dumps(item),) for item in (
        {'status': 'unknown', 'url': 'https://one.test/unknown'},
        {'status': 'retained', 'url': 'https://one.test/retained'},
        {'status': 'pending', 'url': 'https://one.test/unattempted'})])
    db.execute('INSERT INTO tasks VALUES(?)', (json.dumps({'status': 'refused', 'task': {'url': 'https://one.test/listing'}}),))
    db.execute('INSERT INTO attempts VALUES(?)', (json.dumps({
        'status': 'deferred', 'response': {'requestUrl': 'https://one.test/unattempted'},
        'articleMetadata': {'canonicalUrl': 'https://one.test/unattempted'}}),))
    db.commit()
    db.close()
    before = collect.sha(state / 'QUEUE.sqlite3')
    exclusion = collect.exclusion_sets()
    collect.absorb_state(state / 'STATE.json', exclusion)
    assert exclusion['urls'] == {'https://one.test/unknown', 'https://one.test/retained', 'https://one.test/listing'}
    assert exclusion['blockedHosts'] == {'denied.test'}
    assert exclusion['hostDelays'] == {'slow.test': 35}
    assert collect.sha(state / 'QUEUE.sqlite3') == before


def test_full_roster_never_drops_corporate_or_provider_blocked_rows():
    research = {'sources': [{'id': 'reuters', 'host': 'www.reuters.com', 'status': 'policy_denied'},
                             {'id': 'asml-press', 'host': 'www.asml.com', 'status': 'blocked_observed'}]}
    rows = collect.source_matrix([], research)
    by_id = {row['sourceId']: row for row in rows}
    assert set(collect.LEGACY_PRIVATE) <= by_id.keys()
    assert set(collect.INTERNATIONAL) <= by_id.keys()
    assert set(collect.COMPANIES) <= by_id.keys()
    assert len([row for row in rows if row.get('roster') == 'company_newsroom']) == 24
    assert len([row for row in rows if row.get('roster') == 'international_publisher']) == 16
    assert by_id['etnews-ai']['status'] == 'supported'
    assert by_id['nvidia-newsroom']['status'] == 'supported'
    assert by_id['openai-newsroom']['status'] == by_id['anthropic-newsroom']['status'] == 'unsupported'
    assert by_id['gdelt-doc']['status'] == by_id['reuters']['status'] == by_id['asml-newsroom']['status'] == 'blocked'
    assert by_id['gdelt-doc']['reasonCode'] == 'blocked_provider_429'
    assert 'asml-press' not in by_id
    assert all('status' in row and 'reasonCode' in row for row in rows)


def test_actual_private_cli_v2_denies_all_origins_without_http(tmp_path):
    state = tmp_path / 'actual-private-state'
    config = tmp_path / 'config.json'
    exclusions = tmp_path / 'exclusions.json'
    collect.atomic(config, {'schemaVersion': 'zoop-private-news-config-2', 'planId': 'actual-denied',
        'stateDir': str(state), 'fromDay': '2026-07-28', 'throughDay': '2026-10-28',
        'operatorApprovalRef': 'synthetic-offline-test-no-public-fetch',
        'sources': [{'name': 'hankyung-daily', 'sourceType': 'editorial', 'reliability': 'test', 'queries': []}],
        'exactArticleHosts': ['www.hankyung.com'], 'policy': collect.policy(10, 2_000_000, 20, private=True),
        'selectionMode': 'backfill', 'companyAliases': []})
    collect.atomic(exclusions, collect.frozen_exclusions(collect.exclusion_sets({'blockedHosts': ['www.hankyung.com']})))
    result = subprocess.run(collect.child_command('private', 'collect-child', config, exclusions),
                            env=collect.clean_env(), capture_output=True, text=True, check=False)
    assert result.returncode == 2, result.stderr
    summary = json.loads(result.stdout)
    assert summary['sourceRequests'] == summary['sourceBytes'] == 0
    assert summary['retainedInWindow'] == 0
    assert set(summary['partitionDispositions']) == {'prior_host_blocked'}
    assert state.exists()


def shared_budget(root, clock, monkeypatch):
    from zoop_ai_pipeline import live_budget, live_funding
    monkeypatch.setattr(live_budget, '_now', lambda: clock.now().isoformat())
    policy = live_funding.set_funding_policy('synthetic-shared-run',
        (clock.now() - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ'),
        (clock.now() + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ'))
    return live_budget.Budget(root / 'modelbudget', 20 * live_budget.NANO, 100000, funding=policy,
                             finish_by=(clock.now() + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%SZ'))


def test_funded_acquisition_admits_before_child_and_drains_after_shared_stop(frozen, monkeypatch):
    fixture = frozen(concurrency=2)
    root, manifest, ledger = fixture
    clock = Clock()
    manifest['options']['stopNewWorkAt'] = (clock.now() + timedelta(seconds=1)).isoformat()
    for plan in manifest['plans']:
        plan['funding'] = {'setId': 'acquisition:' + plan['id'], 'unitDigest': 'a' * 64,
                           'allowance': {'fetch': 10, 'search': 0}}

    budget = shared_budget(root, clock, monkeypatch)
    boundary = ProcessBoundary(clock, finishes={'set-0': 4, 'set-1': 5})

    def launch(plan, *args, **kwargs):
        assert budget.set_status(plan['funding']['setId']) == 'admitted'
        return boundary(plan, *args, **kwargs)

    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-must-not-forward')
    monkeypatch.setenv('TYPESAFE_API_KEY', 'synthetic-must-not-forward')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'synthetic-ambient-must-not-forward')
    collect.execute(root, manifest, ledger, launch=launch, now=clock.now, sleep=clock.sleep,
                    disk_free=lambda: 10**12, budget=budget, fetch_values={'DEEPSEEK_API_KEY': 'synthetic-explicit'})
    assert budget.snapshot()['stopIntent']['reason'] == 'stop_new_deadline'
    assert budget.snapshot()['sets'] == {'completed': 2}
    assert [ledger['plans'][key]['endedAt'] for key in ('set-0', 'set-1')] == [
        datetime(2026, 10, 28, 8, 0, second, tzinfo=timezone.utc).isoformat() for second in (4, 5)]
    assert boundary.launched == ['set-0', 'set-1']
    for identifier, env in boundary.environments.items():
        assert env['DEEPSEEK_API_KEY'] == 'synthetic-explicit'
        assert env['ZOOP_AI_PIPELINE_LIVE_SET_ID'] == 'acquisition:' + identifier
        assert 'OPENAI_API_KEY' not in env and 'TYPESAFE_API_KEY' not in env
    assert 'DEEPSEEK_API_KEY' not in collect.clean_env()


def test_private_v2_reference_ignores_sidecar_as_record_and_pins_it(tmp_path):
    state = tmp_path / 'retained'
    state.mkdir()
    binding = {'config': {'planId': 'extracted-plan', 'sources': [{'name': 'openai-newsroom'}]}}
    collect.atomic(state / 'PLAN.json', binding)
    identifier = 'private-news-' + 'b' * 64
    raw = b'Literal provider text; no native HTML identity claimed.'
    (state / (identifier + '.raw')).write_bytes(raw)
    sidecar = state / (identifier + '.extraction.json')
    collect.atomic(sidecar, {'backend': 'deepseek-fetch', 'retainedText': raw.decode(), 'finalUrl': None})
    record = {'schemaVersion': 'zoop-private-news-record-2', 'privateId': identifier, 'source': 'openai-newsroom',
              'planDigest': hashlib.sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True,
                                                      separators=(',', ':')).encode()).hexdigest(),
              'rawSha256': hashlib.sha256(raw).hexdigest(), 'rawBytes': len(raw),
              'textSha256': hashlib.sha256(raw).hexdigest(), 'prepared': {'text': raw.decode()},
              'extractionArtifact': {'file': sidecar.name, 'sha256': collect.sha(sidecar)},
              'provenance': 'private-public-web-extracted', 'finalUrl': None}
    path = state / (identifier + '.json')
    collect.atomic(path, record)
    items = collect.private_items(state)
    assert len(items) == 1 and items[0]['recordPath'] == str(path)
    assert items[0]['recordSha256'] == collect.sha(path)
    collect.atomic(sidecar, {'changed': True})
    with pytest.raises(ValueError, match='private_extraction_artifact_pin_invalid'):
        collect.private_items(state)


def test_offline_smoke_states_are_not_absorbed_as_historical_host_denials(tmp_path):
    root = tmp_path / 'historical'
    smoke = root / 'evidence' / 'offline-configs' / 'offline-denied-private'
    smoke.mkdir(parents=True)
    collect.atomic(smoke / 'PLAN.json', {'config': {'schemaVersion': 'zoop-private-news-config-1', 'planId': 'not-corpus'}})
    collect.atomic(smoke / 'STATE.json', {'state': {'blocked': ['www.hankyung.com']}})
    result = collect.reused_corpus((root,), tmp_path / 'missing-foreign-inventory.json')
    assert result['priorStates'] == result['privateItems'] == []


def test_private_full_window_orders_fresh_first_without_document_quotas(tmp_path):
    rows = [row for row in collect.source_matrix([]) if row['sourceId'] in ('etnews-ai', 'nvidia-newsroom')]
    options = {'freshFromDay': '2026-10-28', 'throughDay': '2026-10-28', 'fromDay': '2026-07-28',
               'setRequests': 2000, 'setBytes': 160_000_000, 'setSeconds': 1800, 'approvalRef': 'synthetic-scope'}
    plans = collect.build_plans(rows, tmp_path, options, {}, [], {})
    assert len(plans) == 2
    assert {plan['freshness'] for plan in plans} == {'unknown'}
    for plan in plans:
        config = plan['configTemplate']
        assert config['schemaVersion'] == 'zoop-private-news-config-2'
        assert not {'maxDocuments', 'maxCandidates', 'maxArticleAttempts', 'perDayCap', 'maxListingPages'} & config.keys()
        assert config['policy']['maxRequests'] == 2000
        assert config['selectionMode'] == 'fresh-first'
        assert (config['fromDay'], config['throughDay']) == ('2026-07-28', '2026-10-28')


def test_resource_concurrency_is_derived_not_fixed_at_eight(monkeypatch):
    monkeypatch.setattr(os, 'cpu_count', lambda: 32)
    monkeypatch.setattr(os, 'sysconf', lambda key: 16_777_216 if key == 'SC_PHYS_PAGES' else 4096)
    monkeypatch.setattr(collect.resource, 'getrlimit', lambda _: (1024, 1024))
    count, evidence = collect.resource_concurrency([{'status': 'supported'}] * 40, 0)
    assert count == 32
    assert evidence['resourceCeiling'] == 32 and evidence['requested'] == 'all-available-origins'
    assert collect.resource_concurrency([{'status': 'supported'}] * 40, 12)[0] == 12


def test_known_resource_stop_enqueues_new_pinned_chunk_without_starving_other_origin(frozen):
    fixture = frozen(('one.test', 'two.test'), concurrency=1)
    root, manifest, ledger = fixture
    clock = Clock()
    stopped = complete_empty() | {'state': 'partial', 'stopCode': 'request_budget',
                                  'continuationEligible': True, 'pendingCandidates': 1}
    boundary = ProcessBoundary(clock, summaries={'set-0': stopped})
    prior_pins = {}

    def launch(plan, *args, **kwargs):
        if plan['id'] == 'set-0':
            state = Path(plan['configTemplate']['stateDir'])
            state.mkdir()
            collect.atomic(state / 'PLAN.json', {'config': {'planId': plan['id']}})
            data = {'requests': 1, 'bytes': 10, 'unknownRequests': 0, 'blocked': [], 'delays': {},
                    'pendingRequest': None, 'stopCode': 'request_budget', 'tasks': 'sqlite:tasks',
                    'candidates': 'sqlite:candidates', 'attempts': 'sqlite:attempts'}
            collect.atomic(state / 'STATE.json', {'state': data})
            db = sqlite3.connect(state / 'QUEUE.sqlite3')
            for table in ('tasks', 'candidates', 'attempts'):
                db.execute('CREATE TABLE ' + table + '(value TEXT,status TEXT)')
            db.execute('INSERT INTO candidates VALUES(?,?)',
                       (json.dumps({'status': 'pending', 'url': 'https://one.test/not-yet-sent'}), 'pending'))
            db.commit()
            db.close()
            prior_pins.update({name: collect.sha(state / name) for name in ('PLAN.json', 'STATE.json', 'QUEUE.sqlite3')})
        return boundary(plan, *args, **kwargs)

    collect.execute(root, manifest, ledger, launch=launch, now=clock.now, sleep=clock.sleep, disk_free=lambda: 10**12)
    assert boundary.launched == ['set-0', 'set-1', 'set-0-c1']
    successor, = ledger['continuations']
    assert successor['predecessorId'] == 'set-0' and successor['generation'] == 1
    predecessor = successor['configTemplate']['predecessor']
    assert predecessor == {'stateDir': str(root / 'state/set-0'),
                           'planSha256': prior_pins['PLAN.json'], 'stateSha256': prior_pins['STATE.json'],
                           'queueSha256': prior_pins['QUEUE.sqlite3']}
    assert {name: collect.sha(root / 'state/set-0' / name) for name in prior_pins} == prior_pins
    assert len(collect.load(root / 'INDEX.json')['observations']) == 3
    assert 'https://one.test/not-yet-sent' not in boundary.exclusions['set-0-c1']['urls']


def test_running_set_publishes_committed_records_before_child_finishes(frozen):
    fixture = frozen(('one.test',), concurrency=1)
    root, manifest, ledger = fixture
    manifest['options']['checkpointSeconds'] = 1
    clock = Clock()
    boundary = ProcessBoundary(clock, finishes={'set-0': 4})
    captured = []

    def change(clock):
        if clock.ticks == 1:
            state = root / 'state/set-0'
            state.mkdir()
            binding = {'config': {'planId': 'set-0', 'sources': [{'name': 'source-0'}]}}
            collect.atomic(state / 'PLAN.json', binding)
            raw = b'One committed article'
            identifier = 'private-news-' + 'c' * 64
            (state / (identifier + '.raw')).write_bytes(raw)
            record = {'schemaVersion': 'zoop-private-news-record-1', 'privateId': identifier, 'source': 'source-0',
                      'planDigest': hashlib.sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True,
                                                              separators=(',', ':')).encode()).hexdigest(),
                      'rawSha256': hashlib.sha256(raw).hexdigest(), 'rawBytes': len(raw),
                      'textSha256': hashlib.sha256(raw).hexdigest(), 'prepared': {'text': raw.decode()}}
            collect.atomic(state / (identifier + '.json'), record)
            collect.atomic(state / 'STATE.json', {'state': {
                'requests': 1, 'bytes': len(raw), 'unknownRequests': 0, 'blocked': [], 'delays': {},
                'pendingRequest': None, 'stopCode': None, 'tasks': {}, 'attempts': [],
                'candidates': {identifier: {'status': 'retained', 'url': 'https://one.test/article'}}}})
        elif clock.ticks == 2:
            captured.append(collect.load(root / 'INDEX.json'))
            checkpoint = collect.load(root / 'INDEX_CHECKPOINT.json')
            assert checkpoint['checkpointId'] == captured[-1]['checkpointId']
            assert checkpoint['index']['sha256'] == collect.sha(root / 'INDEX.json')

    clock.on_sleep = change
    dispatch(fixture, clock, boundary)
    index, = captured
    assert index['status'] == 'running' and index['endedAt'] is None
    assert len(index['privateItems']) == 1 and index['observations'] == []
    assert index['sourceMatrix'][0]['counts']['newCollection'] == 1
    assert index['sourceMatrix'][0]['coverage'][0]['dispatchState'] == 'running'
    assert index['sourceMatrix'][0]['coverage'][0]['committedRecords'] == 1


def test_native_continuation_keeps_unattempted_ids_but_not_unknown_requests(tmp_path):
    state = tmp_path / 'native'
    state.mkdir()
    config = {'fromDay': '2026-10-28', 'throughDay': '2026-10-28', 'listingOrigin': 'https://www.korea.kr'}
    collect.atomic(state / 'PLAN.json', {'config': config})
    collect.atomic(state / 'STATE.json', {
        'items': {
            '148000001': {'outcome': 'pending', 'phase': 'planned', 'candidate': {'url': 'https://m.korea.kr/item?newsId=148000001'}},
            '148000002': {'outcome': 'failed', 'phase': 'collection-intent', 'reason': 'set_request_budget',
                          'candidate': {'url': 'https://m.korea.kr/item?newsId=148000002'}},
            '148000003': {'outcome': 'failed', 'phase': 'collection-intent', 'reason': 'timeout',
                          'candidate': {'url': 'https://m.korea.kr/item?newsId=148000003'}}},
        'channels': {'policy-news': {'reason': 'set_request_budget', 'page': 3}},
        'blocked': [], 'delays': {}, 'pendingRequest': None, 'pendingListing': None})
    exclusion = collect.exclusion_sets()
    collect.absorb_state(state / 'STATE.json', exclusion, keep_unattempted=True)
    assert exclusion['newsIds'] == {'148000003'}
    assert exclusion['urls'] == {'https://m.korea.kr/item?newsId=148000003'}


def test_admission_matrix_preserves_research_ids_and_three_korea_channels(frozen):
    root, manifest, ledger = frozen()
    research = {'sources': [
        {'id': 'naver-corp-press', 'roster': 'company_newsroom', 'name': 'NAVER', 'host': 'www.navercorp.com'},
        {'id': 'korea-policy-portal', 'roster': 'government_regulator', 'name': 'Korea', 'host': 'www.korea.kr'},
        {'id': 'hn-discovery', 'roster': 'discovery_provider', 'name': 'HN', 'host': 'hacker-news.firebaseio.com'}]}
    manifest['sourceMatrix'] = collect.source_matrix([], research)
    manifest['researchSources'] = research['sources']
    manifest['plans'] = []
    manifest['options'].update(fromDay='2026-07-28', throughDay='2026-10-28', freshFromDay='2026-10-28')
    collect.publish_index(root, manifest, ledger)
    matrix = collect.load(root / 'SOURCE_ADMISSION.json')
    assert [row['sourceId'] for row in matrix['sources']] == ['naver-corp-press', 'korea-policy-portal', 'hn-discovery']
    assert matrix['sources'][1]['adapterSourceIds'] == ['korea-policy-news', 'korea-press-release', 'korea-clarifications']
    assert all(row['attemptStatus'] == 'not-started' and row['fromDay'] == '2026-07-28' for row in matrix['sources'])
    assert 'korea-policy-portal' in (root / 'SOURCE_ADMISSION.md').read_text()


def test_cutoff_is_rechecked_between_individual_dispatches(frozen):
    fixture = frozen(concurrency=3)
    clock = Clock()
    fixture[1]['options']['stopNewWorkAt'] = (clock.now() + timedelta(seconds=1)).isoformat()
    boundary = ProcessBoundary(clock)

    def launch(plan, *args, **kwargs):
        child = boundary(plan, *args, **kwargs)
        clock.value += timedelta(seconds=2)
        return child

    collect.execute(*fixture, launch=launch, now=clock.now, sleep=clock.sleep, disk_free=lambda: 10**12)
    assert boundary.launched == ['set-0']
    assert fixture[2]['plans']['set-1']['reasonCode'] == 'stop_new_deadline'
    assert boundary.finished == ['set-0']


def test_empty_explicit_fetch_key_is_a_prerequisite_not_ambient_authority(tmp_path, monkeypatch):
    path = tmp_path / 'synthetic.env'
    path.write_text('DEEPSEEK_API_KEY=\n')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'synthetic-ambient-forbidden')
    assert collect.read_runtime_key(path, 'DEEPSEEK_API_KEY') == {}
    assert 'DEEPSEEK_API_KEY' not in collect.clean_env({}, 'acquisition:test')


def test_native_successor_copies_only_unattempted_work_and_cursor_into_new_state(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from zoop_ai_pipeline import korea_corpus
    previous, current = tmp_path / 'previous', tmp_path / 'next'
    previous.mkdir()
    wire = {'planId': 'new', 'stateDir': str(current), 'fromDay': '2026-10-28', 'throughDay': '2026-10-28',
            'listingOrigin': 'https://www.korea.kr', 'articleOrigin': 'https://m.korea.kr',
            'exactHosts': ['www.korea.kr', 'm.korea.kr'], 'grant': {}, 'rightsEvidence': {},
            'channels': [{'name': 'policy-news'}]}
    collect.atomic(previous / 'PLAN.json', {'config': wire | {'planId': 'old', 'stateDir': str(previous)}})
    data = {'unknownRequests': 0, 'pendingRequest': None, 'pendingListing': None, 'blocked': [],
            'delays': {'www.korea.kr': 10}, 'items': {
                '148000001': {'outcome': 'pending', 'phase': 'planned', 'candidate': {'newsId': '148000001'}},
                '148000002': {'outcome': 'failed', 'phase': 'collection-intent', 'reason': 'set_request_budget',
                              'candidate': {'newsId': '148000002'}},
                '148000003': {'outcome': 'failed', 'phase': 'collection-intent', 'reason': 'timeout',
                              'candidate': {'newsId': '148000003'}}},
            'channels': {'policy-news': {'page': 7, 'pages': 6, 'done': True, 'reason': 'channel-page-cap',
                                         'oldest': '2026-10-28', 'signatures': ['prior-page']}}}
    collect.atomic(previous / 'STATE.json', data)
    pins = {'plan': collect.ref(previous / 'PLAN.json'), 'state': collect.ref(previous / 'STATE.json')}
    config = SimpleNamespace(state_dir=str(current), channels=[SimpleNamespace(name='policy-news')], wire=lambda: wire)
    monkeypatch.setattr(korea_corpus, 'State', korea_corpus.State)
    collect.seed_native_continuation(korea_corpus, config, pins)
    state = korea_corpus.State(config, {'config': wire})
    try:
        assert set(state.data['items']) == {'148000001', '148000002'}
        assert state.data['channels']['policy-news']['page'] == 7
        assert state.data['channels']['policy-news']['pages'] == 0
        assert state.data['channels']['policy-news']['done'] is False
        assert state.data['requests'] == state.data['bytes'] == 0
        assert state.data['delays'] == {'www.korea.kr': 10}
    finally:
        state.close()
    assert pins == {'plan': collect.ref(previous / 'PLAN.json'), 'state': collect.ref(previous / 'STATE.json')}
    assert collect.load(current / 'PLAN.json')['predecessor'] == pins


@pytest.mark.parametrize('unknown', [False, True])
def test_real_shared_fetch_budget_drains_admitted_set_and_preserves_unknown_charge(frozen, monkeypatch, unknown):
    from zoop_ai_pipeline import live_budget
    from zoop_ai_pipeline.live_funding import set_funding_policy
    root, manifest, ledger = frozen(('one.test',), concurrency=1)
    clock = Clock()
    cutoff = (clock.now() + timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
    manifest['options']['stopNewWorkAt'] = cutoff
    plan = manifest['plans'][0]
    plan['funding'] = {'setId': 'acquisition:set-0', 'unitDigest': 'a' * 64, 'allowance': {'fetch': 10, 'search': 0}}
    monkeypatch.setattr(live_budget, '_now', lambda: clock.now().isoformat())
    budget = live_budget.Budget(root.parent / 'modelbudget', 20 * live_budget.NANO, 100000,
                               funding=set_funding_policy('synthetic-full-source', '2026-10-28T07:00:00Z', cutoff))

    class Child:
        pid = 50001

        def poll(self):
            return 0 if clock.ticks >= 4 else None

        def result(self):
            assert clock.now() >= datetime.fromisoformat(cutoff.replace('Z', '+00:00'))
            budget.reserve('synthetic-fetch', 'fetch', 'deepseek-fetch', 'b' * 64, 750000,
                           account_role='personal-deepseek', set_id='acquisition:set-0')
            budget.check_send('synthetic-fetch')
            # No transport exists in this boundary. An unknown outcome deliberately
            # leaves the real monetary reservation outstanding for reconciliation.
            if not unknown:
                budget.settle('synthetic-fetch', 750000)
            return complete_empty()

    def launch(plan, *args, **kwargs):
        assert budget.set_status(plan['funding']['setId']) == 'admitted'
        return Child()

    collect.execute(root, manifest, ledger, launch=launch, now=clock.now, sleep=clock.sleep,
                    disk_free=lambda: 10**12, budget=budget, fetch_values={})
    expected = 'unknown' if unknown else 'completed'
    assert budget.set_status('acquisition:set-0') == expected
    assert ledger['plans']['set-0']['fundingOutcome'] == expected
    assert ledger['plans']['set-0']['fallbackPrerequisite'] == 'deepseek_api_key_missing'
    with sqlite3.connect(budget.path) as db:
        assert db.execute('SELECT state,charged_nano FROM reservations').fetchall() == [
            ('reserved' if unknown else 'settled', 750000)]
        assert db.execute('SELECT count(*) FROM admitted_sets').fetchone() == (1,)
    assert ledger['held'] == ({'requests': 10, 'bytes': 1000} if unknown else {'requests': 0, 'bytes': 0})
    with pytest.raises(live_budget.BudgetError) as caught:
        budget.admit_set('acquisition:not-admitted-after-stop', 'c' * 64, {'fetch': 1, 'search': 0})
    assert caught.value.code == 'live_set_admission_closed'


def test_native_and_provider_transport_share_observed_resource_charge():
    plan = {'kind': 'private', 'ceilings': {'requests': 20, 'bytes': 1000}}
    summary = complete_empty() | {'sourceRequests': 7, 'sourceBytes': 100,
                                  'providerOutcomeCounts': {'success': 2, 'http-failure': 1}, 'providerBytes': 80}
    record = {'status': 'finished', 'summary': summary}
    ledger = {'held': {'requests': 20, 'bytes': 1000}, 'spent': {'requests': 0, 'bytes': 0}}
    assert collect.measured_usage(plan, record) == {'requests': 10, 'bytes': 180}
    assert collect.outcome(plan, record)['counts']['requests'] == 10
    assert collect.outcome(plan, record)['counts']['bytes'] == 180
    collect.settle(ledger, plan, record)
    assert ledger == {'held': {'requests': 0, 'bytes': 0}, 'spent': {'requests': 10, 'bytes': 180}}
    summary['providerUnknownByteUpperBound'] = 2000
    assert collect.measured_usage(plan, record) is None


def test_fallback_request_reservation_does_not_double_again_on_successor(tmp_path):
    rows = [row for row in collect.source_matrix([]) if row['sourceId'] == 'hankyung-daily']
    control = tmp_path / 'control.json'
    collect.atomic(control, {})
    options = {'freshFromDay': '2026-10-28', 'throughDay': '2026-10-28', 'fromDay': '2026-07-28',
               'setRequests': 2000, 'setBytes': 160_000_000, 'setSeconds': 1800,
               'approvalRef': 'synthetic-scope', 'fundingConfig': collect.ref(control)}
    plan = collect.build_plans(rows, tmp_path, options, {}, [], {})[0]
    collect.attach_fallback(plan, tmp_path, options)
    assert plan['ceilings']['requests'] == 4000
    assert plan['funding']['allowance'] == {'fetch': 2000, 'search': 0}
    successor = copy.deepcopy(plan)
    successor['id'] += '-next'
    successor['configTemplate'].update(planId=successor['id'], stateDir=str(tmp_path / 'state' / successor['id']))
    successor['configTemplate'].pop('fallback')
    collect.attach_fallback(successor, tmp_path, options)
    assert successor['ceilings']['requests'] == 4000
    assert successor['funding']['allowance'] == {'fetch': 2000, 'search': 0}
    assert successor['funding']['unitDigest'] != plan['funding']['unitDigest']


def test_official_registration_replaces_missing_adapter_and_preserves_fsc_route():
    from zoop_ai_pipeline.news_sources import source_descriptors
    rows = collect.source_matrix([descriptor.wire() for descriptor in source_descriptors()])
    options = {'fromDay': '2026-07-28', 'throughDay': '2026-10-28'}
    collect.register_official_sources(rows, options)
    by_id = {row['sourceId']: row for row in rows}
    assert by_id['fsc-press-releases']['kind'] == 'private'
    for identifier in ('bis-federal-register', 'opendart', 'sec-edgar'):
        assert by_id[identifier]['kind'] == 'official'
        assert by_id[identifier]['status'] == 'supported'
        assert by_id[identifier]['reasonCode'] is None
    assert by_id['sec-edgar']['hosts'] == ['data.sec.gov', 'www.sec.gov']
    assert by_id['opendart']['officialPrerequisites']


def test_actual_official_cli_missing_key_is_one_row_prerequisite_without_http(tmp_path, monkeypatch):
    options = {'freshFromDay': '2026-10-28', 'fromDay': '2026-07-28', 'throughDay': '2026-10-28',
               'setRequests': 10, 'setBytes': 2_000_000, 'setSeconds': 20, 'approvalRef': 'synthetic-explicit-scope'}
    rows = collect.register_official_sources(collect.source_matrix([]), options)
    row = next(row for row in rows if row['sourceId'] == 'opendart')
    plan = collect.build_plans([row], tmp_path, options, {}, [], {})[0]
    config, exclusions = collect.materialize(plan, collect.exclusion_sets(), tmp_path)
    monkeypatch.setenv('OPENDART_API_KEY', 'synthetic-ambient-not-authorized')
    result = subprocess.run(collect.child_command('official', 'collect-child', config, exclusions),
                            env=collect.clean_env(), capture_output=True, text=True, check=False)
    assert result.returncode == 2, result.stderr
    summary = json.loads(result.stdout)
    assert summary['state'] == 'prerequisite'
    assert summary['sourceRequests'] == summary['sourceBytes'] == 0
    assert summary['prerequisites'] and summary['retainedInWindow'] == 0
    outcome = collect.outcome(plan, {'status': 'finished', 'summary': summary})
    assert outcome['status'] == 'blocked' and 'source_prerequisite' in outcome['reasonCodes']
    assert collect.official_items(plan['configTemplate']['stateDir']) == []


def test_official_reference_pins_original_container_separately_from_derived_text(tmp_path):
    state = tmp_path / 'official-state'
    state.mkdir()
    binding = {'planId': 'official-plan', 'sourceId': 'opendart'}
    collect.atomic(state / 'PLAN.json', binding)
    identifier = 'official-source-' + 'd' * 64
    container, body = b'<filing><text>Exact filing text</text></filing>', b'Exact filing text'
    (state / (identifier + '.raw')).write_bytes(container)
    (state / (identifier + '.body.md')).write_bytes(body)
    extraction = state / (identifier + '.extraction.json')
    collect.atomic(extraction, {'schemaVersion': 'zoop-official-extraction-1', 'members': []})
    record = {'schemaVersion': 'zoop-official-source-record-1', 'privateId': identifier,
              'planId': 'official-plan', 'source': 'opendart',
              'planDigest': hashlib.sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
              'rawSha256': hashlib.sha256(container).hexdigest(), 'rawBytes': len(container),
              'textSha256': hashlib.sha256(body).hexdigest(), 'prepared': {'text': body.decode()},
              'bodyArtifact': {'file': identifier + '.body.md', 'sha256': hashlib.sha256(body).hexdigest()},
              'extractionArtifact': {'file': extraction.name, 'sha256': collect.sha(extraction)}}
    path = state / (identifier + '.json')
    collect.atomic(path, record)
    items = collect.official_items(state)
    assert items == [{'sourceId': 'opendart', 'stateDir': str(state), 'recordPath': str(path),
                      'recordSha256': collect.sha(path), 'privateId': identifier, 'planId': 'official-plan'}]
    assert record['rawSha256'] != record['textSha256']
    (state / (identifier + '.body.md')).write_bytes(b'Changed derived text')
    with pytest.raises(ValueError, match='official_artifact_pin_invalid'):
        collect.official_items(state)


def test_opendart_key_is_injected_only_into_explicit_opendart_child(frozen, monkeypatch):
    root, manifest, ledger = frozen(('dart.test', 'other.test'), concurrency=2)
    manifest['plans'][0].update(kind='official', sourceId='opendart')
    monkeypatch.setenv('OPENDART_API_KEY', 'synthetic-ambient-forbidden')
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'synthetic-ambient-forbidden')
    clock = Clock()
    boundary = ProcessBoundary(clock)
    collect.execute(root, manifest, ledger, launch=boundary, now=clock.now, sleep=clock.sleep,
                    disk_free=lambda: 10**12, dart_values={'OPENDART_API_KEY': 'synthetic-explicit'},
                    fetch_values={'DEEPSEEK_API_KEY': 'synthetic-explicit-fetch'})
    dart_env = boundary.environments['set-0']
    assert dart_env['OPENDART_API_KEY'] == 'synthetic-explicit'
    assert 'DEEPSEEK_API_KEY' not in dart_env
    assert boundary.environments['set-1'] is None
    assert 'OPENDART_API_KEY' not in collect.clean_env()


def test_actual_publication_day_classifies_mixed_private_batch_and_reuse(tmp_path):
    items = []
    for identifier, day in (('current', '2026-10-28'), ('older', '2026-08-03'), ('missing', None), ('reused', '2026-10-28')):
        path = tmp_path / (identifier + '.json')
        collect.atomic(path, {'publicationDay': day})
        items.append({'recordPath': str(path), 'recordSha256': collect.sha(path)})
    reused = {'privateItems': [items[-1]]}
    result = collect.item_freshness(items, reused, '2026-10-28', {})
    assert [result[item['recordPath']]['freshness'] for item in items] == ['fresh', 'backfill', 'unknown', 'reused']
    assert result[items[1]['recordPath']]['publicationDay'] == '2026-08-03'
    assert result[items[2]['recordPath']]['publicationDay'] is None


@pytest.mark.parametrize('escalation', [None, 'STOP', 'deadline'])
def test_local_checkpoint_drains_children_without_closing_funding_unless_global_stop(frozen, escalation, monkeypatch):
    fixture = frozen(concurrency=2)
    root, manifest, ledger = fixture
    clock = Clock()
    boundary = ProcessBoundary(clock, finishes={'set-0': 4, 'set-1': 5})

    budget = shared_budget(root, clock, monkeypatch)

    def request_checkpoint(current):
        if current.ticks == 1:
            ledger['closedReason'] = 'revision_checkpoint_drain'
        elif current.ticks == 2 and escalation == 'STOP':
            (root / 'STOP').touch()
        elif current.ticks == 2 and escalation == 'deadline':
            manifest['options']['stopNewWorkAt'] = current.now().isoformat()

    clock.on_sleep = request_checkpoint
    collect.execute(root, manifest, ledger, launch=boundary, now=clock.now, sleep=clock.sleep,
                    disk_free=lambda: 10**12, budget=budget)
    assert boundary.launched == boundary.finished == ['set-0', 'set-1']
    assert ledger['plans']['set-2']['status'] == 'not_started'
    assert ledger['plans']['set-0']['status'] == ledger['plans']['set-1']['status'] == 'finished'
    stop = budget.snapshot()['stopIntent']
    assert stop is None if escalation is None else stop['reason'] == ('operator_soft_stop' if escalation == 'STOP' else 'stop_new_deadline')
    assert budget.snapshot()['sets'] == {'completed': 2}


def test_finish_deadline_terminates_only_owned_active_children_and_keeps_reservations(frozen):
    fixture = frozen(hosts=('one.test', 'two.test'), concurrency=1)
    root, manifest, ledger = fixture
    clock = Clock()
    reserve = collect.FINISH_RESERVE_SECONDS + 2 * collect.TERMINATION_GRACE_SECONDS
    manifest['options']['finishBy'] = (clock.now() + timedelta(seconds=reserve + 2)).isoformat()
    for plan in manifest['plans']:
        plan['ceilings']['seconds'] = 1
    boundary = ProcessBoundary(clock, finishes={'set-0': 20})
    dispatch(fixture, clock, boundary)
    assert boundary.launched == boundary.terminated == ['set-0']
    assert ledger['plans']['set-0']['status'] == 'unknown'
    assert ledger['plans']['set-0']['terminationReason'] == 'finish_deadline'
    assert ledger['plans']['set-1']['status'] == 'not_started'
    assert ledger['held'] == {'requests': 10, 'bytes': 1000}
    assert ledger['spent'] == {'requests': 0, 'bytes': 0}
    assert clock.ticks == 2


def test_finish_window_refuses_child_whose_full_allowance_cannot_fit(frozen):
    fixture = frozen(hosts=('one.test',), concurrency=1)
    _, manifest, ledger = fixture
    clock = Clock()
    reserve = collect.FINISH_RESERVE_SECONDS + 2 * collect.TERMINATION_GRACE_SECONDS
    manifest['options']['finishBy'] = (clock.now() + timedelta(seconds=reserve + 20)).isoformat()
    boundary = ProcessBoundary(clock)
    dispatch(fixture, clock, boundary)
    assert boundary.launched == []
    assert ledger['plans']['set-0'] == {'status': 'not_started', 'reasonCode': 'finish_window_insufficient'}
    assert ledger['held'] == {'requests': 0, 'bytes': 0}
