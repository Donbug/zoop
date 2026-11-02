"""Versioned collection controls sharing the original day funding and pacing roots.

prepare is offline and preserves every drained predecessor namespace. run is an
operator-gated new process: only untouched plans are admitted automatically.
Known pre-provider rejections and finite cursors remain evidence, never retries
or released reservations.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import sys
from datetime import datetime, timezone

SOURCE_ROOT = Path(__file__).resolve().parents[3]
for package in ('ai/worker/src', 'ai/pipeline/src'):
    sys.path.insert(0, str(SOURCE_ROOT / package))
import overnight_collect as base

SCHEMA = 'zoop-collection-revision-1'


def pinned(path):
    return base.ref(path)


def require_pin(pin):
    if pinned(pin['path']) != pin:
        raise ValueError('revision_input_pin_changed:' + str(pin['path']))


def lock_existing(path, *, exclusive=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    except BaseException:
        os.close(fd)
        raise
    return fd


def revision_namespace(path, day_root):
    return (path.resolve() == path and path.parent == day_root / 'collection-revisions'
            and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,60}', path.name) is not None)


def collection_chain(previous, control, funding_pin):
    """Walk only pinned predecessors back to this day's original collection."""
    original = Path(control['root']).resolve(strict=True) / 'collection'
    chain, seen = [], set()
    current = previous
    while True:
        if current in seen or (current != original and not revision_namespace(current, original.parent)):
            raise ValueError('explicit_same_day_revision_chain_required')
        seen.add(current)
        pins = {name: pinned(current / name) for name in ('PLAN.json', 'LEDGER.json', 'INDEX.json')}
        manifest, ledger = base.load(current / 'PLAN.json'), base.load(current / 'LEDGER.json')
        if (manifest['runId'] != control['runId'] or manifest['options']['fundingConfig'] != funding_pin
                or ledger['planSha256'] != pins['PLAN.json']['sha256']):
            raise ValueError('previous_plan_ledger_mismatch')
        chain.append(pins)
        if current == original:
            break
        require_pin(manifest['revisionEvidence'])
        metadata = base.load(manifest['revisionEvidence']['path'])
        parent = Path(metadata['previousRoot'])
        if parent != original and not revision_namespace(parent, original.parent):
            raise ValueError('explicit_same_day_revision_chain_required')
        expected = {name: pinned(parent / name) for name in ('PLAN.json', 'LEDGER.json', 'INDEX.json')}
        if (metadata['schemaVersion'] != SCHEMA or metadata['revisionRoot'] != str(current)
                or metadata['runId'] != control['runId'] or metadata['fundingConfig'] != funding_pin
                or metadata['budgetPath'] != str(original.parent / 'modelbudget/live-budget.sqlite3')
                or metadata['pacingRoot'] != str(original / 'fetch-pacing')
                or metadata['previous'] != expected or manifest['previousCollection'] != expected
                or ledger['previousCollection'] != expected):
            raise ValueError('previous_revision_chain_mismatch')
        if metadata.get('collectionChain') is not None:
            for ancestor in metadata['collectionChain']:
                for pin in ancestor.values():
                    require_pin(pin)
        current = parent
    return list(reversed(chain))


def require_drained(ledger):
    if (ledger.get('endedAt') is None
            or ledger.get('closedReason') not in {None, 'controller_failure_drain', 'operator_soft_stop', 'revision_checkpoint_drain'}
            or any(record.get('status') in {'reserved', 'running'} for record in ledger['plans'].values())):
        raise ValueError('previous_controller_must_have_finished_draining')


def update_untouched_metadata(plan):
    """New-plan metadata only; never modify an attempted predecessor config."""
    if plan['kind'] != 'private':
        return
    config = plan['configTemplate']
    for source in config['sources']:
        if source['name'] == 'amazon-newsroom' and source.get('descriptor'):
            source['descriptor']['publicationMeta'] = ['parsely-pub-date', 'article:published_time']
        if source['name'] == 'fnnews-sitemaps':
            config['policy']['maxDiscoveryResponseBytes'] = 10_000_000
            plan['ceilings']['bytes'] = config['policy']['maxTotalBytes'] + 10_000_000


def scope(previous, revision, funding_pin, stop_new):
    previous = Path(os.path.abspath(previous))
    revision = Path(os.path.abspath(revision))
    require_pin(funding_pin)
    day_root = Path(base.load(funding_pin['path'])['root']).resolve(strict=True)
    control = base.validate_run_config(funding_pin, day_root / 'collection', stop_new)
    if (previous.resolve(strict=True) != previous or previous == revision
            or not revision_namespace(revision, day_root)):
        raise ValueError('explicit_same_day_revision_namespace_required')
    if previous != day_root / 'collection':
        if not revision_namespace(previous, day_root):
            raise ValueError('explicit_same_day_revision_namespace_required')
        collection_chain(previous, control, funding_pin)
    return previous, revision, control


def budget_snapshot(control):
    """One WAL-aware read transaction; never call a budget method while preparing."""
    from zoop_ai_pipeline.live_funding import run_policy
    expected = run_policy(control)
    path = base.verified_path(Path(control['root']) / 'modelbudget/live-budget.sqlite3')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5, isolation_level=None)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        policy_row = db.execute('SELECT policy FROM funding_policy').fetchone()
        if policy_row is None or json.loads(policy_row[0]) != expected:
            raise ValueError('shared_funding_policy_mismatch')
        caps = dict(db.execute("SELECT key,value FROM meta WHERE key IN ('max_nano','bucket_shared','bucket_personal')"))
        if caps != {'max_nano': expected['totalMaxNanoUsd'],
                    **{'bucket_' + key: value for key, value in expected['bucketMaxNanoUsd'].items()}}:
            raise ValueError('shared_funding_policy_mismatch')
        sets = {row[0]: {'unitDigest': row[1], 'state': row[2]}
                for row in db.execute('SELECT set_id,unit_digest,state FROM admitted_sets')}
        reservations = [{'attemptId': row[0], 'setId': row[1], 'state': row[2], 'chargedNano': row[3]}
                        for row in db.execute('SELECT r.attempt_id,s.set_id,r.state,r.charged_nano '
                                              'FROM reservations r LEFT JOIN reservation_sets s USING(attempt_id)')]
        stop = db.execute('SELECT reason,stopped_at,forced FROM admission_stop WHERE singleton=1').fetchone()
        result = {'path': str(path), 'fundingPolicy': expected, 'sets': sets, 'reservations': reservations,
                  'admissionStop': list(stop) if stop else None}
        db.execute('ROLLBACK')
        return result
    finally:
        db.close()


def actual_refs(plan):
    state = Path(plan['configTemplate']['stateDir'])
    if not state.exists():
        return {'nativeItems': [], 'privateItems': []}
    lock = lock_existing(state / '.lock')
    try:
        if plan['kind'] == 'native':
            return {'nativeItems': base.native_items(plan), 'privateItems': []}
        if plan['kind'] == 'private':
            return {'nativeItems': [], 'privateItems': base.private_items(state)}
        if plan['kind'] == 'official':
            return {'nativeItems': [], 'privateItems': base.official_items(state)}
        return {'nativeItems': [], 'privateItems': []}
    finally:
        os.close(lock)


def untouched(previous, plan, record, monetary):
    if (record.get('status') != 'not_started' or record.get('reasonCode') not in {
            'controller_failure_drain', 'operator_soft_stop', 'revision_checkpoint_drain'}
            or any(record.get(key) is not None for key in ('startedAt', 'pid', 'config', 'fundedSetId'))):
        return False
    if Path(plan['configTemplate']['stateDir']).exists():
        return False
    for folder, suffix in (('configs', '.json'), ('configs', '.exclusions.json'),
                           ('logs', '.stdout.json'), ('logs', '.stderr.txt')):
        if (previous / folder / (plan['id'] + suffix)).exists():
            return False
    set_id = plan.get('funding', {}).get('setId')
    return set_id is None or set_id not in monetary['sets']


def known_unsent_and_cursors(plans, ledger):
    """Evidence only. This does not change refused/unknown candidate statuses."""
    candidates, cursors = [], []
    for plan in plans:
        record = ledger['plans'].get(plan['id'], {})
        summary = record.get('summary') or {}
        state = Path(plan['configTemplate']['stateDir'])
        if summary.get('continuationEligible'):
            cursors.append({'planId': plan['id'], 'originalControllerStatus': record.get('status'),
                            'stateDir': str(state), 'stopCode': summary.get('stopCode'),
                            'pendingCandidates': summary.get('pendingCandidates'),
                            'pendingPartitions': summary.get('pendingPartitions'),
                            'admission': 'requires-per-request-reconciliation; not automatically resumed'})
        if plan['kind'] != 'private' or not (state / 'STATE.json').exists():
            continue
        data = base.load(state / 'STATE.json')['state']
        for attempt in base.state_rows(data, state, 'attempts'):
            if attempt.get('code') != 'fallback_admission_mismatch':
                continue
            native = attempt.get('nativeObservation')
            candidates.append({'planId': plan['id'], 'candidateId': attempt.get('key'), 'stateDir': str(state),
                               'originalCode': attempt['code'], 'hasNativeObservation': native is not None,
                               'hasProviderReceipt': attempt.get('providerReceipt') is not None,
                               'hasProviderAttemptId': attempt.get('providerAttemptId') is not None,
                               'nativeObservationDigest': hashlib.sha256(json.dumps(native, sort_keys=True, ensure_ascii=False,
                                                                                    separators=(',', ':')).encode()).hexdigest() if native else None,
                               'admission': 'known-pre-provider-refusal; producer-native-reuse-guard-not-yet-enabled'})
    return {'knownUnsentCandidates': candidates, 'finiteCursorCandidates': cursors,
            'automaticReplay': False, 'oldStatesModified': False}


def prepare(previous, revision, approval_ref, expected_records):
    if not approval_ref:
        raise ValueError('explicit_revision_approval_required')
    old_manifest, old_ledger = base.load(previous / 'PLAN.json'), base.load(previous / 'LEDGER.json')
    previous, revision, control = scope(previous, revision, old_manifest['options']['fundingConfig'],
                                        old_manifest['options']['stopNewWorkAt'])
    require_drained(old_ledger)
    if base.sha(previous / 'PLAN.json') != old_ledger['planSha256']:
        raise ValueError('previous_plan_ledger_mismatch')
    if revision.exists():
        raise ValueError('revision_namespace_already_exists')
    controller_lock = lock_existing(previous / '.controller.lock', exclusive=True)
    state_locks = []
    try:
        old_manifest, old_ledger = base.load(previous / 'PLAN.json'), base.load(previous / 'LEDGER.json')
        require_drained(old_ledger)
        chain = collection_chain(previous, control, old_manifest['options']['fundingConfig'])
        plans = base.all_plans(old_manifest, old_ledger)
        for plan in plans:
            state = Path(plan['configTemplate']['stateDir'])
            if state.exists() and (state / '.lock').exists():
                state_locks.append(lock_existing(state / '.lock'))
        monetary = budget_snapshot(control)
        previous_pins = {name: pinned(previous / name) for name in ('PLAN.json', 'LEDGER.json', 'INDEX.json')}
        revision.mkdir(mode=0o700, parents=True)
        for name in ('configs', 'state', 'logs', 'evidence'):
            (revision / name).mkdir(mode=0o700)
        manifest = copy.deepcopy(old_manifest)
        manifest['plans'] = copy.deepcopy(plans)
        manifest['sourcePins'] = base.source_pins()
        manifest['sourcePins'][str(Path(__file__).resolve())] = base.sha(__file__)
        manifest['createdAt'] = base.stamp()
        manifest['revisionId'] = revision.name
        manifest['previousCollection'] = previous_pins
        manifest['collectionChain'] = chain
        manifest['options']['approvalRef'] = approval_ref
        ledger = {'schemaVersion': 'zoop-daytime-acquisition-ledger-2', 'planSha256': None,
                  'startedAt': None, 'endedAt': None, 'plans': {}, 'continuations': [],
                  'held': copy.deepcopy(old_ledger['held']), 'spent': copy.deepcopy(old_ledger['spent']),
                  'originReadyAt': copy.deepcopy(old_ledger.get('originReadyAt', {})), 'closedReason': None,
                  'previousCollection': previous_pins, 'inheritedUnknownsPreserved': True}
        exclusion = base.exclusion_sets(base.load(old_manifest['priorExclusions']['path']))
        current = previous / 'evidence/CURRENT_EXCLUSIONS.json'
        if current.exists():
            exclusion = base.exclusion_sets(base.load(current))
        eligible, preserved, retained = [], [], []
        for plan in manifest['plans']:
            old_record = old_ledger['plans'].get(plan['id'], {})
            if untouched(previous, plan, old_record, monetary):
                eligible.append(plan['id'])
                plan['configTemplate']['stateDir'] = str(revision / 'state' / plan['id'])
                plan['configTemplate']['operatorApprovalRef'] = approval_ref if plan['kind'] != 'native' else plan['configTemplate'].get('operatorApprovalRef')
                if plan['kind'] == 'native':
                    plan['configTemplate'].pop('operatorApprovalRef', None)
                plan['configTemplate'].pop('fallback', None)
                plan.pop('funding', None)
                update_untouched_metadata(plan)
                if plan['kind'] == 'private' and manifest['options'].get('fundingConfig'):
                    base.attach_fallback(plan, revision, manifest['options'])
                continue
            preserved.append(plan['id'])
            record = copy.deepcopy(old_record)
            if not record:
                record = {'status': 'not_started', 'reasonCode': 'untouched_proof_not_established'}
            items = actual_refs(plan)
            retained.extend(items['privateItems'])
            retained.extend(items['nativeItems'])
            item_path = revision / 'evidence' / (plan['id'] + '.items.json')
            base.atomic(item_path, items, immutable=True)
            record['itemsRef'] = pinned(item_path)
            record['committedRecords'] = len(items['nativeItems']) + len(items['privateItems'])
            record['originalControllerStatus'] = old_record.get('status')
            record['reconciledCommittedArtifactsOnly'] = True
            ledger['plans'][plan['id']] = record
            state_path = Path(plan['configTemplate']['stateDir']) / 'STATE.json'
            if state_path.exists():
                base.absorb_state(state_path, exclusion)
        if len(retained) != expected_records:
            raise ValueError(f'committed_record_count_mismatch:{len(retained)}')
        pending = known_unsent_and_cursors(plans, old_ledger)
        base.atomic(revision / 'evidence/PENDING_RECONCILIATION.json', pending, immutable=True)
        base.atomic(revision / 'evidence/INHERITED_EXCLUSIONS.json', base.frozen_exclusions(exclusion), immutable=True)
        manifest['priorExclusions'] = pinned(revision / 'evidence/INHERITED_EXCLUSIONS.json')
        metadata = {'schemaVersion': SCHEMA, 'revisionId': revision.name, 'createdAt': base.stamp(),
                    'revisionRoot': str(revision), 'previousRoot': str(previous), 'runId': control['runId'],
                    'previous': previous_pins, 'fundingConfig': old_manifest['options']['fundingConfig'],
                    'collectionChain': chain,
                    'budgetPath': monetary['path'], 'pacingRoot': str(Path(control['root']) / 'collection/fetch-pacing'),
                    'sourceRoot': str(SOURCE_ROOT), 'sourcePins': manifest['sourcePins'], 'approvalRef': approval_ref,
                    'eligibleUntouchedPlanIds': eligible, 'preservedPlanIds': preserved,
                    'preservedUnknownPlanIds': [key for key, value in old_ledger['plans'].items() if value['status'] == 'unknown'],
                    'preservedReservedAttempts': [item for item in monetary['reservations'] if item['state'] == 'reserved'],
                    'inheritedResourceAccounting': {'held': old_ledger['held'], 'spent': old_ledger['spent']},
                    'reconciledCommittedRecords': len(retained), 'knownUnsentCandidates': len(pending['knownUnsentCandidates']),
                    'pendingCursorCandidates': len(pending['finiteCursorCandidates']),
                    'noBudgetReset': True, 'noOldNetworkReplay': True, 'consumerIndexPromoted': False}
        base.atomic(revision / 'REVISION.json', metadata, immutable=True)
        manifest['revisionEvidence'] = pinned(revision / 'REVISION.json')
        base.atomic(revision / 'PLAN.json', manifest, immutable=True)
        ledger['planSha256'] = base.sha(revision / 'PLAN.json')
        base.atomic(revision / 'LEDGER.json', ledger, immutable=True)
        base.publish_index(revision, manifest, ledger)
        print(json.dumps({'prepared': True, 'revisionRoot': str(revision), 'eligibleUntouchedPlans': len(eligible),
                          'reconciledCommittedRecords': len(retained), 'knownUnsentCandidates': len(pending['knownUnsentCandidates']),
                          'pendingCursors': len(pending['finiteCursorCandidates']), 'network': 'none'}))
    finally:
        for fd in reversed(state_locks):
            os.close(fd)
        os.close(controller_lock)


def validate_revision(revision):
    manifest, ledger = base.load(revision / 'PLAN.json'), base.load(revision / 'LEDGER.json')
    require_pin(manifest['revisionEvidence'])
    metadata = base.load(manifest['revisionEvidence']['path'])
    if metadata['schemaVersion'] != SCHEMA or metadata['revisionRoot'] != str(revision.resolve()):
        raise ValueError('revision_metadata_invalid')
    previous, revision, control = scope(Path(metadata['previousRoot']), revision, metadata['fundingConfig'],
                                        manifest['options']['stopNewWorkAt'])
    if metadata['sourceRoot'] != str(SOURCE_ROOT) or metadata['runId'] != control['runId']:
        raise ValueError('revision_source_or_run_changed')
    if manifest['options'].get('finishBy') != control['finishBy']:
        raise ValueError('collection_finish_pin_changed')
    if base.sha(revision / 'PLAN.json') != ledger['planSha256']:
        raise ValueError('revision_plan_changed')
    for pin in metadata['previous'].values():
        require_pin(pin)
    chain = collection_chain(previous, control, metadata['fundingConfig'])
    if metadata.get('collectionChain') != chain or manifest.get('collectionChain') != chain:
        raise ValueError('revision_chain_changed')
    require_drained(base.load(previous / 'LEDGER.json'))
    for path, expected in manifest['sourcePins'].items():
        if base.sha(path) != expected:
            raise ValueError('revision_source_pin_changed:' + path)
    for name in ('priorExclusions', 'reusedCorpus', 'rightsEvidence', 'routeResearch'):
        require_pin(manifest[name])
    if manifest.get('replayPackages'):
        import collection_history
        collection_history.verify_replay_pins(manifest['replayPackages'])
    for plan in base.all_plans(manifest, ledger):
        if plan.get('funding'):
            require_pin(plan['funding']['proof'])
    return manifest, ledger, metadata, previous, control


def check(revision):
    manifest, ledger, metadata, _, _ = validate_revision(revision)
    directory = revision / 'evidence' / ('offline-configs-' + base.uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    exclusions = base.exclusion_sets(base.load(manifest['priorExclusions']['path']))
    results = []
    for plan in manifest['plans']:
        if plan['id'] not in metadata['eligibleUntouchedPlanIds']:
            continue
        config, exclusion_path = base.materialize(plan, exclusions, directory)
        result = base.subprocess.run(base.child_command(plan['kind'], 'validate-child', config, exclusion_path),
                                     env=child_env(), capture_output=True, text=True, check=False)
        results.append({'planId': plan['id'], 'returnCode': result.returncode})
        if result.returncode:
            base.atomic(revision / 'evidence/CHECK.json', {'passed': False, 'results': results, 'stderr': result.stderr})
            raise ValueError('revision_child_config_invalid:' + plan['id'])
    base.atomic(revision / 'evidence/CHECK.json', {'passed': True, 'network': 'none', 'configCount': len(results),
                                                 'planSha256': ledger['planSha256'], 'results': results})
    print(json.dumps({'passed': True, 'network': 'none', 'configCount': len(results)}))


def child_env(env=None):
    result = dict(env) if env is not None else base.clean_env()
    result['PYTHONPATH'] = str(SOURCE_ROOT / 'ai/pipeline/src') + os.pathsep + str(SOURCE_ROOT / 'ai/worker/src')
    return result


def launch(plan, root, config, exclusions, *, env=None):
    return base.RunningChild(plan, root, config, exclusions, env=child_env(env))


def run(revision, approval_ref, fetch_env, opendart_env):
    if not approval_ref:
        raise ValueError('explicit_revision_launch_approval_required')
    manifest, ledger, metadata, previous, control = validate_revision(revision)
    checked = base.load(revision / 'evidence/CHECK.json')
    if not checked['passed'] or checked['planSha256'] != ledger['planSha256']:
        raise ValueError('revision_offline_check_required')
    if ledger['startedAt'] is not None:
        raise ValueError('revision_restart_requires_reconciliation')
    if datetime.now(timezone.utc) >= datetime.fromisoformat(control['admitUntil'].replace('Z', '+00:00')):
        raise ValueError('revision_admission_cutoff')
    if (previous / 'STOP').exists():
        raise ValueError('previous_operator_stop_preserved')
    monetary = budget_snapshot(control)
    if monetary['admissionStop'] is not None:
        raise ValueError('shared_admission_stop_preserved')
    for plan in manifest['plans']:
        if plan['id'] in metadata['eligibleUntouchedPlanIds']:
            set_id = plan.get('funding', {}).get('setId')
            if set_id and set_id in monetary['sets']:
                raise ValueError('untouched_set_already_admitted:' + set_id)
    old_lock = lock_existing(previous / '.controller.lock', exclusive=True)
    own_lock = os.open(revision / '.controller.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    handlers = {}
    try:
        fcntl.flock(own_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        ledger['approvalRef'] = approval_ref

        def stop(signum, frame):
            # Checkpoint drain is local to this revision. TERM/INT remain global stops.
            if signum == signal.SIGUSR1 and ledger['closedReason'] not in (None, 'revision_checkpoint_drain'):
                return
            ledger['closedReason'] = 'revision_checkpoint_drain' if signum == signal.SIGUSR1 else 'operator_soft_stop'

        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGUSR1):
            handlers[sig] = signal.signal(sig, stop)
        budget = base.acquisition_budget(Path(control['root']) / 'collection', manifest)
        base.execute(revision, manifest, ledger, launch=launch, budget=budget,
                     fetch_values=base.read_runtime_key(fetch_env, 'DEEPSEEK_API_KEY'),
                     dart_values=base.read_runtime_key(opendart_env, 'OPENDART_API_KEY'))
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
        os.close(own_lock)
        os.close(old_lock)


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'check', 'run'))
    parser.add_argument('--previous-root', type=Path)
    parser.add_argument('--revision-root', type=Path, required=True)
    parser.add_argument('--approval-ref')
    parser.add_argument('--expected-new-records', type=int, default=138)
    parser.add_argument('--fetch-env', type=Path)
    parser.add_argument('--opendart-env', type=Path)
    args = parser.parse_args(argv)
    revision = args.revision_root.absolute()
    if args.command == 'prepare':
        if args.previous_root is None:
            parser.error('--previous-root required')
        prepare(args.previous_root, revision, args.approval_ref, args.expected_new_records)
    elif args.command == 'check':
        check(revision)
    else:
        run(revision, args.approval_ref, args.fetch_env, args.opendart_env)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
