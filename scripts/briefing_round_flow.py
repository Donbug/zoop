#!/usr/bin/env python3
"""Resume completed local series through cutoff prices, DB, graph and HTTP. No AI calls."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from types import SimpleNamespace
import urllib.request

import briefing_local_run as local
import briefing_series_prices as prices

base = prices.base
ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 'zoop-briefing-round-flow-v1'


def copy_tree(source, output):
    base.private_dir(output)
    for f in source.rglob('*'):
        if f.is_symlink():
            raise base.ReplayError('flow_symlink_input')
        if f.is_file():
            target = output / f.relative_to(source)
            base.private_dir(target.parent)
            base.write_once(target, base.regular(f))


class Ledger:
    """Append-only attempts; completed steps are validated, never silently replaced."""
    def __init__(self, root):
        self.root, self.executed, self.reused = root, [], []
        base.private_dir(root)

    def step(self, name, action, validate=lambda _: True):
        folder = self.root / name
        base.private_dir(folder)
        attempts = sorted(folder.glob('*.result.json'))
        for path in reversed(attempts):
            saved = base.strict_load(base.regular(path))
            if saved['status'] == 'COMPLETE':
                if validate(saved['result']):
                    self.reused.append(name)
                    return saved['result']
                break
        number = len(list(folder.glob('*.started.json'))) + 1
        prefix = f'{number:04d}'
        base.write_once(folder / (prefix + '.started.json'), base.canonical({'stage': name, 'startedAt': base.now()}))
        try:
            result = action()
            if not validate(result):
                raise base.ReplayError('flow_stage_validation_' + name)
        except Exception as error:
            base.write_once(folder / (prefix + '.result.json'), base.canonical({
                'stage': name, 'status': 'FAILED', 'finishedAt': base.now(),
                'code': str(error) if isinstance(error, base.ReplayError) else type(error).__name__}))
            raise
        base.write_once(folder / (prefix + '.result.json'), base.canonical({
            'stage': name, 'status': 'COMPLETE', 'finishedAt': base.now(), 'result': result}))
        self.executed.append(name)
        return result


def failed_requests(output):
    bundle = base.strict_load(base.regular(output / 'bundle-v2.json'))
    return any(s['httpStatus'] != 200
               for r in bundle['marketEnrichment']['seriesCompanyPrices']['rounds']
               for p in r['prices'].values() for s in p['sources'])


def price_step(baseline, work, authorization, cache=None, transport=None):
    """Keep failed archives; copy only successful per-symbol/interval receipts to the next attempt."""
    attempts = work / 'prices'
    base.private_dir(attempts)
    folders = sorted(p for p in attempts.iterdir() if p.is_dir())
    if folders:
        latest = folders[-1]
        proof = latest / 'prices-proof.json'
        if proof.exists():
            result = prices.run(SimpleNamespace(baseline=str(baseline), output=str(latest), authorization_ref=authorization),
                                lambda _: (_ for _ in ()).throw(base.ReplayError('flow_unexpected_refetch')))
            if not failed_requests(latest):
                return {'bundle': str(latest / 'bundle-v2.json'), 'bundleSha256': result['bundleSha256']}
    output = attempts / f'{len(folders) + 1:04d}'
    if not folders and cache:
        copy_tree(cache, output)
    else:
        base.private_dir(output)
        if folders:
            # Success receipts cannot be refetched, and failure receipts cannot be overwritten.
            old = folders[-1] / 'company-prices'
            target = output / 'company-prices'
            base.private_dir(target)
            for path in old.glob('*.json'):
                receipt = base.strict_load(base.regular(path))
                if receipt['httpStatus'] != 200:
                    continue
                raw = base.regular(old / (receipt['sha256'] + '.bin'))
                if base.digest(raw) != receipt['sha256'] or len(raw) != receipt['bytes']:
                    raise base.ReplayError('flow_price_cache_changed')
                base.write_once(target / path.name, base.regular(path))
                base.write_once(target / (receipt['sha256'] + '.bin'), raw)
    result = prices.run(SimpleNamespace(baseline=str(baseline), output=str(output), authorization_ref=authorization), transport)
    if failed_requests(output):
        raise base.ReplayError('flow_price_request_failed_resume_to_retry')
    return {'bundle': str(output / 'bundle-v2.json'), 'bundleSha256': result['bundleSha256']}


def validate_prices(result, baseline, authorization):
    if result['bundleSha256'] != base.digest(base.regular(Path(result['bundle']))):
        raise base.ReplayError('flow_completed_price_changed')
    def forbidden_refetch(_):
        raise base.ReplayError('flow_unexpected_refetch')
    prices.run(SimpleNamespace(baseline=str(baseline), output=str(Path(result['bundle']).parent),
                              authorization_ref=authorization), forbidden_refetch)
    if failed_requests(Path(result['bundle']).parent):
        raise base.ReplayError('flow_price_request_failed_resume_to_retry')
    return True


def get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def process_identity(pid):
    # PID liveness alone also matches a recycled PID. Pin OS start time and command.
    done = subprocess.run(['ps', '-p', str(pid), '-o', 'lstart=', '-o', 'command='],
                          capture_output=True, text=True, check=False)
    if done.returncode or not done.stdout.strip():
        raise base.ReplayError('flow_process_identity_unavailable')
    return base.digest(done.stdout.strip().encode())


def response_identity(url):
    value = get(url)
    if isinstance(value, dict) and isinstance(value.get('metadata'), dict):
        value['metadata'].pop('requestId', None)
    return base.digest(base.canonical(value))


def owned_process(record, url):
    if not alive(record['pid']):
        return False
    if (record.get('url') != url or not record.get('processIdentity')
            or process_identity(record['pid']) != record['processIdentity']):
        raise base.ReplayError('flow_process_ownership_changed')
    if record.get('responseIdentity') != response_identity(url):
        raise base.ReplayError('flow_process_response_changed')
    return True


def process(work, name, command, url, env):
    folder = work / 'processes' / name
    base.private_dir(folder)
    old = sorted(folder.glob('*.json'))
    if old:
        previous = base.strict_load(base.regular(old[-1]))
        if alive(previous['pid']):
            # Existing owned process may still be recovering; never kill or duplicate it.
            owned_process(previous, url)
            return previous
    port = int(url.split(':', 2)[2].split('/')[0])
    local.free_port(port)
    with (work / 'logs' / (name + '.log')).open('ab') as log:
        os.chmod(log.name, 0o600)
        child = subprocess.Popen([str(x) for x in command], cwd=ROOT if name == 'api' else ROOT / 'web',
                                 env=env, stdout=log, stderr=subprocess.STDOUT)
    result = {'pid': child.pid, 'url': url, 'startedAt': base.now(), 'processIdentity': process_identity(child.pid)}
    for _ in range(90):
        if child.poll() is not None:
            raise base.ReplayError('flow_' + name + '_start_failed')
        try:
            result['responseIdentity'] = response_identity(url)
            base.write_once(folder / f'{len(old) + 1:04d}.json', base.canonical(result))
            return result
        except Exception:
            time.sleep(.3)
    raise base.ReplayError('flow_' + name + '_not_ready')


def run(args, transport=None):
    work, baseline = Path(args.output).resolve(), Path(args.baseline).resolve()
    stages = ['completed_results', 'prices', 'database_import', 'graph_register', 'api', 'http_verify']
    if args.serve:
        stages.append('frontend')
    if not args.execute:
        return {'status': 'OFFLINE', 'stages': stages, 'newPaidCalls': 0, 'productionAuthorized': False}
    if baseline == work or baseline in work.parents or work in baseline.parents:
        raise base.ReplayError('flow_separate_output_required')
    base.private_dir(work)
    base.private_dir(work / 'logs')
    with (work / '.flow.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise base.ReplayError('flow_already_running') from None
        return execute(args, work, baseline, transport)


def execute(args, work, baseline, transport):
    source, clocks, jar = (Path(getattr(args, k)).resolve() for k in ('sources', 'clocks', 'jar'))
    original = base.regular(baseline / 'bundle-v2.json')
    bundle = base.strict_load(original)
    if not bundle.get('roundSeries') or bundle['marketEnrichment']['seriesCompanyOutlooks']['authorizationRef'] != args.authorization_ref:
        raise base.ReplayError('flow_completed_series_required')
    if not args.database.startswith('zoop_briefing_replay_local_') or not args.database.replace('_', '').isalnum():
        raise base.ReplayError('dedicated_local_database_required')
    identity = {'schemaVersion': SCHEMA, 'baselineSha256': base.digest(original), 'sourceSha256': base.digest(base.regular(source)),
        'clockSha256': base.digest(base.regular(clocks)), 'jarSha256': base.digest(base.regular(jar)),
        'database': args.database, 'pgPort': args.pg_port, 'pgUser': args.pg_user, 'apiPort': args.api_port,
        'webPort': args.web_port, 'authorizationRef': args.authorization_ref, 'maximumPaidCalls': args.max_calls,
        'continuity': args.continuity, 'coreSemantic': args.core_semantic, 'serve': args.serve}
    base.write_once(work / 'flow-identity.json', base.canonical(identity))
    ledger = Ledger(work / 'stages')
    ledger.step('completed_results', lambda: {'bundleSha256': identity['baselineSha256'], 'newPaidCalls': 0},
                lambda r: r['bundleSha256'] == base.digest(base.regular(baseline / 'bundle-v2.json')))
    price = ledger.step('prices', lambda: price_step(baseline, work, args.authorization_ref,
                        Path(args.price_cache).resolve() if args.price_cache else None, transport),
                        lambda r: validate_prices(r, baseline, args.authorization_ref))
    frozen = work / ('api-' + identity['jarSha256'][:16] + '.jar')
    base.write_once(frozen, base.regular(jar))
    base.private_dir(work / 'artifacts')
    key = work / '.csrf-key'
    if not key.exists():
        base.write_once(key, secrets.token_urlsafe(32).encode())
    env = {k:v for k,v in os.environ.items() if not any(x in k for x in ('API_KEY','TOKEN','SECRET','PASSWORD'))}
    env.update(JAVA_HOME=args.java_home, ZOOP_AUTH_CSRF_ACTIVE_KEY_ID='flow', ZOOP_AUTH_CSRF_KEYS='flow=' + key.read_text(),
               ZOOP_AUTH_ALLOWED_ORIGINS='http://127.0.0.1:' + str(args.web_port))
    java = Path(args.java_home) / 'bin/java'
    common = ['--spring.profiles.active=local', '--spring.datasource.url=jdbc:postgresql://127.0.0.1:' + str(args.pg_port) + '/' + args.database,
        '--spring.datasource.username=' + args.pg_user, '--spring.datasource.password=', '--spring.datasource.hikari.maximum-pool-size=2',
        '--spring.datasource.hikari.minimum-idle=0', '--zoop.briefing.replay.manifest=' + str(work / 'manifest.json'),
        '--zoop.document-read.grants=' + str(work / 'grants.json'), '--zoop.document-read.artifact-root=' + str(work / 'artifacts'),
        '--zoop.graph.snapshot.source=artifact', '--zoop.graph.snapshot.artifact-root=' + str(work / 'artifacts')]
    def connection():
        import psycopg
        return psycopg.connect(host='127.0.0.1', port=args.pg_port, dbname=args.database, user=args.pg_user, connect_timeout=5)
    def db_valid(_):
        if not (work / 'manifest.json').exists():
            return False
        manifest = base.strict_load(base.regular(work / 'manifest.json'))
        if (manifest['bundleSha256'] != price['bundleSha256'] or manifest['userInboxRef'] != args.authorization_ref
                or manifest['sourceFileSha256'] != identity['sourceSha256']
                or base.digest(base.regular(work / 'manifest.json')) != _['manifestSha256']
                or base.digest(base.regular(work / 'grants.json')) != manifest['grantsSha256']):
            raise base.ReplayError('flow_manifest_changed')
        with connection() as db:
            for row in manifest['rounds']:
                saved = db.execute("SELECT payload_sha256,encode(sha256(convert_to(public_snapshot::text,'UTF8')),'hex'),published_payload IS NULL OR payload_sha256=encode(sha256(convert_to(published_payload::text,'UTF8')),'hex') FROM briefing_rounds WHERE id=%s", (row['id'],)).fetchone()
                if saved is None:
                    return False
                if saved != (row['payloadSha256'], row['publicSnapshotSha256'], True):
                    raise base.ReplayError('flow_database_changed')
        return True
    def import_db():
        local.create_database(args)
        local.command([java, '-jar', frozen, *[x for x in common if not x.startswith('--zoop.document-read.grants=')],
            '--zoop.document-read.grants=', '--spring.main.web-application-type=none', '--zoop.briefing.replay.import-enabled=true',
            '--zoop.briefing.replay.source=' + str(source), '--zoop.briefing.replay.bundle=' + price['bundle'],
            '--zoop.briefing.replay.artifact-root=' + str(work / 'artifacts'), '--zoop.briefing.replay.grants=' + str(work / 'grants.json'),
            '--zoop.briefing.replay.clocks=' + str(clocks), '--zoop.briefing.replay.expected-source-sha256=' + identity['sourceSha256'],
            '--zoop.briefing.replay.user-inbox-ref=' + args.authorization_ref, '--zoop.briefing.replay.maximum-paid-calls=' + str(args.max_calls),
            '--zoop.briefing.replay.continuity-enabled=' + str(args.continuity).lower(),
            '--zoop.briefing.replay.core-semantic-enabled=' + str(args.core_semantic).lower()], work / 'logs/import.log', env)
        return {'manifestSha256': base.digest(base.regular(work / 'manifest.json'))}
    ledger.step('database_import', import_db, db_valid)
    def graph_valid(result):
        with connection() as db:
            for row in result['artifacts']:
                saved = db.execute('SELECT sha256,bytes FROM artifacts WHERE id=%s', (row['id'],)).fetchone()
                raw = base.regular(work / 'artifacts' / row['path'])
                if saved != (row['sha256'], row['bytes']) or base.digest(raw) != row['sha256']:
                    return False
        return bool(result['artifacts'])
    def graph():
        local.command([java, '-jar', frozen, *common, '--spring.main.web-application-type=none', '--server.address=127.0.0.1',
            '--zoop.briefing.replay.read-enabled=true', '--zoop.briefing.graph-reconstruction.enabled=true'], work / 'logs/graph.log', env)
        with connection() as db:
            rows = db.execute("SELECT id,sha256,bytes,storage_uri FROM artifacts WHERE kind='graph_snapshot' AND storage_uri LIKE 'artifact-root:briefing_graphs/%'").fetchall()
        return {'artifacts': [{'id':i,'sha256':s,'bytes':n,'path':p.removeprefix('artifact-root:')} for i,s,n,p in rows]}
    ledger.step('graph_register', graph, graph_valid)
    published = [r for r in base.strict_load(base.regular(work / 'manifest.json'))['rounds'] if r['payloadSha256']]
    first = published[0]['id']
    api = 'http://127.0.0.1:' + str(args.api_port)
    health = api + '/api/v1/briefings/' + first + '/graph'
    ledger.step('api', lambda: process(work, 'api', [java, '-jar', frozen, *common, '--server.address=127.0.0.1',
        '--server.port=' + str(args.api_port), '--zoop.briefing.replay.read-enabled=true'], health, env),
        lambda r: owned_process(r, health) and get(health).get('status') == 'available')
    checked_http = {}
    def verify_http():
        if 'result' in checked_http:
            return checked_http['result']
        result = []
        for definition in bundle['rounds']:
            body = get(api + '/api/v1/briefings?date=' + definition['date'] + '&edition=' + definition['edition'])
            if body['id'] != definition['roundId']:
                raise base.ReplayError('flow_round_response_mismatch')
            if body['status'] == 'published':
                if get(api + '/api/v1/briefings/' + body['id'] + '/graph')['status'] != 'available':
                    raise base.ReplayError('flow_graph_unavailable')
                for item in body['items']:
                    get(api + '/api/v1/briefings/' + body['id'] + '/items/' + item['eventId'])
            result.append({'roundId':body['id'],'status':body['status'],'prices':sum('price' in c for c in (body.get('companyOutlooks') or {}).get('companies',[]))})
        checked_http['result'] = {'rounds': result}
        return checked_http['result']
    # HTTP reads revalidate current authority even when generation/storage stages are cached.
    http = ledger.step('http_verify', verify_http, lambda r: r == verify_http())
    if args.serve:
        modules = ROOT / 'web/node_modules'
        if not modules.exists():
            if not args.node_modules:
                raise base.ReplayError('node_modules_path_required')
            modules.symlink_to(Path(args.node_modules).resolve(), target_is_directory=True)
        webenv = dict(env); webenv.update(ZOOP_DEV_API_TARGET=api, VITE_API_BASE_URL='')
        # Vite root returns HTML. Its manifest is a static JSON readiness endpoint.
        weburl = 'http://127.0.0.1:' + str(args.web_port) + '/package.json'
        ledger.step('frontend', lambda: process(work, 'frontend', [modules / '.bin/vite', '--host','127.0.0.1','--port',str(args.web_port),'--strictPort'], weburl, webenv),
                    lambda r: owned_process(r, weburl) and get(weburl).get('name') == 'zoop-web')
    result = {'status':'COMPLETE','executedStages':ledger.executed,'reusedStages':ledger.reused,'newPaidCalls':0,
        'rounds':http['rounds'],'bundle':price['bundle'],'apiUrl':api,
        'briefingUrl':'http://127.0.0.1:' + str(args.web_port) + '/briefing?reading=compact' if args.serve else None}
    history = work / 'runs'; base.private_dir(history)
    base.write_once(history / f'{len(list(history.glob("*.json"))) + 1:04d}.json', base.canonical(result))
    return result


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    for field in ('baseline','output','sources','clocks','jar','java-home','authorization-ref','database'):
        p.add_argument('--'+field,required=True)
    p.add_argument('--price-cache');p.add_argument('--node-modules')
    p.add_argument('--pg-port',type=int,default=55496);p.add_argument('--pg-user',default='company_test')
    p.add_argument('--api-port',type=int,default=18132);p.add_argument('--web-port',type=int,default=13136)
    p.add_argument('--max-calls',type=int,default=400)
    p.add_argument('--continuity',action='store_true');p.add_argument('--core-semantic',action='store_true')
    p.add_argument('--execute',action='store_true');p.add_argument('--serve',action='store_true')
    p.add_argument('--keep-alive',action='store_true')
    return p


if __name__=='__main__':
    args=parser().parse_args()
    try:
        print(json.dumps(run(args),ensure_ascii=False),flush=True)
        if args.keep_alive:
            while True: time.sleep(10)
    except Exception as error:
        print(json.dumps({'status':'FAILED','code':str(error) if isinstance(error,base.ReplayError) else type(error).__name__}),flush=True)
        raise SystemExit(1)
