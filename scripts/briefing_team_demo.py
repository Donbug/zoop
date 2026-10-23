#!/usr/bin/env python3
"""Replay checked-in, recorded briefing read projections. No AI, prices, keys or existing DB.

Uses a new disposable Docker PostgreSQL and the built Spring API; optionally starts
the installed Vite frontend. Ctrl-C removes only this run's processes/container.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'api/demo/briefing-2026-10-21_22'
TABLES = ('artifacts', 'articles', 'article_versions', 'evidence', 'briefing_rounds')
DATABASE = 'zoop_briefing_replay_team'
USER = 'briefing_team'
IMAGE = 'postgres:16.13-alpine'
LABEL = 'com.zoop.briefing-team-demo'


class DemoError(Exception):
    pass


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def response_digest(value):
    # Request tracing changes on every read; all stored content/timestamps remain part of the comparison.
    value = dict(value)
    if isinstance(value.get('metadata'), dict):
        value['metadata'] = dict(value['metadata'])
        value['metadata'].pop('requestId', None)
    return digest(canonical(value))


def load(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise DemoError('duplicate_json_key')
            result[key] = value
        return result
    def constant(_):
        raise DemoError('non_json_number')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def safe_file(root, name):
    root = root.resolve()
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or not path.parts:
        raise DemoError('invalid_data_path')
    target = root.joinpath(*path.parts)
    if target.resolve() != target.absolute() or not target.is_file():
        raise DemoError('missing_or_symlink_data')
    if target.stat().st_size > 12_000_000:
        raise DemoError('data_file_too_large')
    return target


def validate(root):
    index = load(safe_file(root, 'index.json').read_bytes())
    if (index['schemaVersion'] != 'zoop-briefing-team-demo-v1'
            or index['scope'] != 'recorded_read_projection'
            or index['responseDigest'] != 'canonical_json_excluding_only_metadata_requestId'
            or index['productionAuthorized'] is not False
            or index['newAiCalls'] != 0 or index['newPriceCalls'] != 0
            or set(index['tables']) != set(TABLES)):
        raise DemoError('invalid_demo_scope')
    files = {}
    for item in index['files']:
        name = item['path']
        if name in files:
            raise DemoError('duplicate_data_path')
        raw = safe_file(root, name).read_bytes()
        if digest(raw) != item['sha256'] or len(raw) != item['bytes']:
            raise DemoError('demo_file_changed:' + name)
        files[name] = raw
    required = {'manifest.json', 'grants.json'} | {'tables/' + t + '.json' for t in TABLES}
    if not required.issubset(files):
        raise DemoError('missing_demo_file')
    rows = {t: load(files['tables/' + t + '.json']) for t in TABLES}
    for table in TABLES:
        if not isinstance(rows[table], list) or len(rows[table]) != index['tables'][table]:
            raise DemoError('table_count_mismatch')
    rounds = rows['briefing_rounds']
    if not 1 <= len(rounds) <= 14 or len(index['expected']) != len(rounds):
        raise DemoError('invalid_round_count')
    manifest = load(files['manifest.json'])
    if (digest(files['manifest.json']) != index['originalManifestSha256']
            or digest(files['grants.json']) != manifest['grantsSha256']):
        raise DemoError('read_authority_changed')
    for row in rounds:
        replay = row['public_snapshot']['replay']
        if (row['status'] != 'published' or row['graph_version_id'] is not None
                or row['generation_token'] is not None or row['lease_until'] is not None
                or replay['scope'] != 'publication_clock_simulation'
                or replay['retrospectiveBodies'] is not True or replay['operationalCollectionGate'] is not False):
            raise DemoError('only_completed_local_simulations')
    if {r['id'] for r in rounds} != {r['roundId'] for r in index['expected']}:
        raise DemoError('round_identity_mismatch')
    if any(row['summary_analysis_id'] is not None for row in rows['evidence']):
        raise DemoError('unexpected_analysis_dependency')
    artifacts = {r['storage_uri']: r for r in rows['artifacts']}
    for name, raw in files.items():
        if name in required:
            continue
        if not name.startswith('artifacts/briefing_graphs/') or not name.endswith('.json'):
            raise DemoError('unexpected_asset')
        row = artifacts.get('artifact-root:' + name.removeprefix('artifacts/'))
        if row is None or row['kind'] != 'graph_snapshot' or digest(raw) != row['sha256'] or len(raw) != row['bytes']:
            raise DemoError('graph_asset_mismatch')
    for expected in index['expected']:
        for path, sha in {expected['path']: expected['responseSha256'], **expected['relatedResponses']}.items():
            if not path.startswith('/api/v1/briefings') or not re.fullmatch('[a-f0-9]{64}', sha):
                raise DemoError('invalid_expected_response')
    return index, files


def seed_sql(files):
    """Only whitelisted tables; JSON is data, never a SQL identifier or executable file."""
    lines = ['BEGIN;', 'LOCK TABLE ' + ','.join(TABLES) + ' IN ACCESS EXCLUSIVE MODE;']
    occupied = ' OR '.join('EXISTS(SELECT 1 FROM ' + t + ')' for t in TABLES)
    lines.append("DO $guard$ BEGIN IF " + occupied + " THEN RAISE EXCEPTION 'demo_requires_empty_database'; END IF; END $guard$;")
    for table in TABLES:
        raw = files['tables/' + table + '.json'].decode()
        literal = "'" + raw.replace("'", "''") + "'::jsonb"
        if table == 'articles':
            literal = "(SELECT jsonb_agg(value || '{\"current_version\":null}'::jsonb) FROM jsonb_array_elements(" + literal + '))'
        lines.append('INSERT INTO ' + table + ' SELECT * FROM jsonb_populate_recordset(NULL::' + table + ',' + literal + ');')
    articles = files['tables/articles.json'].decode().replace("'", "''")
    lines.append("UPDATE articles a SET current_version=b.current_version FROM jsonb_populate_recordset(NULL::articles,'" + articles + "'::jsonb) b WHERE a.id=b.id;")
    lines.append("DO $guard$ BEGIN IF EXISTS(SELECT 1 FROM briefing_rounds WHERE payload_sha256 IS DISTINCT FROM encode(sha256(convert_to(published_payload::text,'UTF8')),'hex')) THEN RAISE EXCEPTION 'stored_payload_changed'; END IF; END $guard$;")
    lines.append('COMMIT;')
    return '\n'.join(lines)


def clean_environment():
    # Provider keys, DB configuration, Java options and application .env files are not inherited.
    keep = ('PATH', 'HOME', 'USERPROFILE', 'SystemRoot', 'COMSPEC', 'TEMP', 'TMP')
    return {key: os.environ[key] for key in keep if key in os.environ}


def get(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url, timeout=5) as response:
        return json.load(response)


def verify(api, index):
    checked = []
    for row in index['expected']:
        paths = {row['path']: row['responseSha256'], **row['relatedResponses']}
        for path, expected in paths.items():
            if response_digest(get(api + path)) != expected:
                raise DemoError('recorded_response_changed:' + path)
        checked.append({'date': row['date'], 'edition': row['edition'], 'coreItems': row['coreItems']})
    return checked


def free_port(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            raise DemoError('port_in_use:' + str(port)) from None
        return sock.getsockname()[1]


def java_command(explicit):
    command = explicit or (str(Path(os.environ['JAVA_HOME']) / 'bin/java') if os.environ.get('JAVA_HOME') else shutil.which('java'))
    if not command:
        raise DemoError('set_JAVA_HOME_to_JDK_21')
    done = subprocess.run([command, '-version'], capture_output=True, text=True, timeout=20)
    match = re.search(r'version "(\d+)', done.stdout + done.stderr)
    if done.returncode or not match or int(match[1]) < 21:
        raise DemoError('JDK_21_or_newer_required')
    return command


def run(args):
    index, files = validate(Path(args.data).resolve())
    if args.check:
        return {'status': 'CHECKED', 'newAiCalls': 0, 'newPriceCalls': 0, 'rounds': index['expected']}
    java = java_command(args.java)
    jar = Path(args.jar).resolve()
    if not jar.is_file():
        raise DemoError('built_jar_missing_run_make_api-build')
    node = shutil.which('node')
    vite = ROOT / 'web/node_modules/vite/bin/vite.js'
    if not args.api_only and (not node or not vite.is_file()):
        raise DemoError('install_web_dependencies_and_Node_first')
    api_port, web_port = free_port(args.api_port), free_port(args.web_port)
    if not args.api_only and api_port == web_port:
        raise DemoError('api_and_web_need_separate_ports')
    env = clean_environment()
    def docker(*command, **kwargs):
        done = subprocess.run(['docker', *command], env=kwargs.pop('env', env), capture_output=True,
                              text=True, timeout=kwargs.pop('timeout', 60), **kwargs)
        if done.returncode:
            raise DemoError('docker_' + command[0] + '_failed')
        return done.stdout.strip()
    docker('info', '--format', '{{.ServerVersion}}', timeout=20)
    docker('image', 'inspect', args.image)  # No implicit pulls or package installation.
    name = 'zoop-briefing-team-' + secrets.token_hex(5)
    password, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    children = []
    created = False
    with tempfile.TemporaryDirectory(prefix='zoop-briefing-team-') as directory:
        work = Path(directory).resolve()
        try:
            for path, raw in files.items():
                if path in ('manifest.json', 'grants.json') or path.startswith('artifacts/'):
                    target = work / path
                    parent = work
                    for part in PurePosixPath(path).parts[:-1]:
                        parent = parent / part
                        parent.mkdir(mode=0o700, exist_ok=True)
                    target.write_bytes(raw)
                    target.chmod(0o600)
            docker('run', '-d', '--pull', 'never', '--name', name, '--label', LABEL + '=1',
                   '--tmpfs', '/var/lib/postgresql/data', '-e', 'POSTGRES_DB=' + DATABASE,
                   '-e', 'POSTGRES_USER=' + USER, '-e', 'POSTGRES_PASSWORD', '-p', '127.0.0.1::5432', args.image,
                   env={**env, 'POSTGRES_PASSWORD': password})
            created = True
            mapped = docker('port', name, '5432/tcp')
            db_port = next(line.rsplit(':', 1)[1] for line in mapped.splitlines() if line.startswith('127.0.0.1:'))
            for _ in range(100):
                try:
                    docker('exec', name, 'pg_isready', '-h', '127.0.0.1', '-U', USER, '-d', DATABASE, timeout=5)
                    break
                except DemoError:
                    time.sleep(.5)
            else:
                raise DemoError('database_not_ready')
            api = 'http://127.0.0.1:' + str(api_port)
            web = 'http://127.0.0.1:' + str(web_port)
            appenv = {**env, 'DB_URL': 'jdbc:postgresql://127.0.0.1:' + db_port + '/' + DATABASE,
                      'DB_USERNAME': USER, 'DB_PASSWORD': password, 'SPRING_PROFILES_ACTIVE': 'local',
                      'SERVER_ADDRESS': '127.0.0.1',
                      'ZOOP_AUTH_CSRF_ACTIVE_KEY_ID': 'team-demo', 'ZOOP_AUTH_CSRF_KEYS': 'team-demo=' + csrf,
                      'ZOOP_AUTH_ALLOWED_ORIGINS': web + ',' + api,
                      'ZOOP_API_CORS_ALLOWED_ORIGINS': web, 'ZOOP_BRIEFING_REPLAY_READ_ENABLED': 'true',
                      'ZOOP_BRIEFING_REPLAY_MANIFEST': str(work / 'manifest.json'),
                      'ZOOP_DOCUMENT_READ_GRANTS': str(work / 'grants.json'),
                      'ZOOP_DOCUMENT_READ_ARTIFACT_ROOT': str(work / 'artifacts'),
                      'ZOOP_GRAPH_SNAPSHOT_SOURCE': 'artifact', 'ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT': str(work / 'artifacts')}
            with (work / 'migration.log').open('w') as log:
                done = subprocess.run([java, '-jar', str(jar), '--spring.main.web-application-type=none'],
                                      cwd=work, env=appenv, stdout=log, stderr=subprocess.STDOUT, timeout=180)
            if done.returncode:
                raise DemoError('migration_failed')
            docker('exec', '-i', name, 'psql', '-U', USER, '-d', DATABASE, '-v', 'ON_ERROR_STOP=1',
                   input=seed_sql(files), timeout=30)
            with (work / 'api.log').open('w') as log:
                child = subprocess.Popen([java, '-jar', str(jar), '--server.address=127.0.0.1', '--server.port=' + str(api_port)],
                                         cwd=work, env=appenv, stdout=log, stderr=subprocess.STDOUT)
            children.append(child)
            for _ in range(180):
                if child.poll() is not None:
                    raise DemoError('api_start_failed')
                try:
                    get(api + index['expected'][0]['path'])
                    break
                except Exception:
                    time.sleep(.5)
            else:
                raise DemoError('api_not_ready')
            result = {'status': 'READY', 'newAiCalls': 0, 'newPriceCalls': 0, 'rounds': verify(api, index),
                      'apiUrl': api, 'briefingUrl': web + '/briefing?date=2026-10-22&edition=evening&reading=compact'}
            if not args.api_only:
                with (work / 'web.log').open('w') as log:
                    webenv = {**env, 'ZOOP_DEV_API_TARGET': api, 'ZOOP_DEV_HTTPS_CERT': '', 'ZOOP_DEV_HTTPS_KEY': ''}
                    frontend = subprocess.Popen([node, str(vite), '--host', '127.0.0.1', '--port', str(web_port), '--strictPort'],
                                                cwd=ROOT / 'web', env=webenv, stdout=log, stderr=subprocess.STDOUT)
                children.append(frontend)
                for _ in range(100):
                    if frontend.poll() is not None:
                        raise DemoError('frontend_start_failed')
                    try:
                        get(web + '/package.json')
                        verify(web, index)  # The frontend proxy must return the same stored publications.
                        break
                    except Exception:
                        time.sleep(.3)
                else:
                    raise DemoError('frontend_not_ready')
            else:
                result['briefingUrl'] = None
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if not args.once:
                while True:
                    if any(c.poll() is not None for c in children):
                        raise DemoError('demo_process_exited')
                    time.sleep(1)
            return result
        except BaseException:
            for file in work.glob('*.log'):
                tail = '\n'.join(file.read_text(errors='replace').splitlines()[-15:])
                for secret in (password, csrf):
                    tail = tail.replace(secret, '[redacted]')
                print(file.name + ':\n' + tail, file=sys.stderr)
            raise
        finally:
            for child in reversed(children):
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=5)
            if created:
                docker('rm', '-f', '-v', name)


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', default=str(DATA))
    p.add_argument('--jar', default=str(ROOT / 'api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar'))
    p.add_argument('--java')
    p.add_argument('--image', default=IMAGE)
    p.add_argument('--api-port', type=int, default=8080)
    p.add_argument('--web-port', type=int, default=5173)
    p.add_argument('--check', action='store_true', help='Check bundled data without Docker, Java or network')
    p.add_argument('--api-only', action='store_true')
    p.add_argument('--once', action='store_true', help='Verify all HTTP responses, then stop and clean up')
    return p


def main():
    def stopped(_signal, _frame):
        raise KeyboardInterrupt
    for name in ('SIGTERM', 'SIGHUP'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stopped)
    try:
        args = parser().parse_args()
        result = run(args)
        if args.check:
            print(json.dumps({'status': result['status'], 'rounds': len(result['rounds']), 'newAiCalls': 0}))
    except KeyboardInterrupt:
        print('Team demo stopped; this run\'s temporary DB and processes removed.')
    except (DemoError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print('Team demo failed: ' + (str(error) if isinstance(error, DemoError) else type(error).__name__), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
