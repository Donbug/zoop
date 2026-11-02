#!/usr/bin/env python3
"""Owned loopback HTTP registration -> two-source compose -> package3 -> Java-only serving.

Run from the repository with the installed pipeline interpreter and a freshly built jar:
  ai/pipeline/.venv/bin/python -B api/scripts/cumulative_publication_smoke.py \
    --jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar --output /tmp/cumulative-synthetic
  ai/pipeline/.venv/bin/python -B api/scripts/cumulative_publication_smoke.py \
    --mode actual --legacy-count 17 \
    --actual-native-root /absolute/native --actual-legacy-root /absolute/legacy \
    --actual-selection-sha256 SELECTION_FILE_SHA256 \
    --actual-native-manifest-sha256 NATIVE_MANIFEST_SHA256 \
    --actual-prepared-sha256 PREPARED_HANDOFF_SHA256 \
    --overlap-review /absolute/review.json --overlap-review-sha256 REVIEW_FILE_SHA256 \
    --jar api/build/libs/zoop-api-0.0.1-SNAPSHOT.jar --output /private/new-actual-proof

Requires cached local PostgreSQL Docker image, macOS sandbox-exec, installed pipeline/service
venvs and worker CLI. Builds and dependency installation belong to the caller. Synthetic mode
uses the existing loopback provider fixture. Actual mode only reads the retained selected native
jobs; it exports a fresh P3 handoff with target-generated bindings. Actual legacy17 bootstrap
continues through a normal legacy22 import, retaining published headlines with explicit pinned
field selections and adding the five reviewed issue IDs. --legacy-count 22 starts at the full
selection and reports actual carry-forward as unexercised.
Counts describe issue records, not certified independent real-world events. All outputs, source
fingerprints, HTTP bodies, operator receipts, failures and private SQL stay in the new 0700
output directory. Only owned processes/container/network are removed. Original source authority
is read-only; revocation exercises separate serving-authority copies.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import stat
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import quote, urlencode

sys.dont_write_bytecode = True
import graph_delivery_smoke as delivery
import graph_handoff_activation_smoke as activation
import http_native_delivery_smoke as http_native
import legacy_real_import_smoke as legacy
import legacy_real_package as package

REPO = Path(__file__).resolve().parents[2]
DESTINATION = 'cumulative-isolated-serving'
LABEL = 'com.zoop.cumulative-publication-smoke'
check, graph, hs, base = delivery.check, delivery.handoff, delivery.handoff.hs, delivery.handoff.base
SQL = delivery.literal
CORE_FIELDS = ('label', 'action', 'target', 'assertionStatus', 'eventTime', 'timePrecision', 'period',
               'geography', 'geographyPolicyVersion', 'geographyEvidenceIds')


def load(path):
    return json.loads(Path(path).read_bytes())


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    path.write_bytes(base.json_bytes(value) + b'\n')
    path.chmod(0o600)


def pin(path, expected):
    check(path.is_file() and sha(path) == expected, 'frozen input pin mismatch: ' + str(path))
    return load(path)


def fingerprint(root):
    """Open no lock inode: observing a lock can release this process's POSIX record lock."""
    root = Path(root)
    check(root.exists() and not root.is_symlink(), 'missing or symlink preservation root: ' + str(root))
    paths = sorted(root.rglob('*')) if root.is_dir() else [root]
    result = {}
    for path in paths:
        if path.name == '.document-import.lock':
            continue
        info = path.lstat()
        key = str(path.relative_to(root)) if root.is_dir() else path.name
        if stat.S_ISLNK(info.st_mode):
            result[key] = {'link': os.readlink(path), 'mode': stat.S_IMODE(info.st_mode), 'mtimeNs': info.st_mtime_ns}
        elif stat.S_ISREG(info.st_mode):
            result[key] = {'sha256': sha(path), 'bytes': info.st_size, 'mode': stat.S_IMODE(info.st_mode), 'mtimeNs': info.st_mtime_ns}
    return result


def isolate(denied=(), *, python=False):
    policy = legacy.SANDBOX
    if denied:
        policy += '(deny file-read* ' + ' '.join('(subpath ' + json.dumps(str(p)) + ')' for p in denied) + ')'
    if python:
        policy += '(deny process-exec (regex #".*/([Pp]ython[^/]*|zoop-ai-[^/]*)$"))'
    return ['/usr/bin/sandbox-exec', '-p', policy]


class Database(base.Database):
    def scalar(self, sql):
        return json.loads(self.run(f"SELECT COALESCE(to_json(({sql})), 'null'::json)"))


class Jar(activation.FixtureJar):
    def __init__(self, *args, denied=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.denied = tuple(denied)
        self.migrated = False

    def base_env(self):
        return {**super().base_env(), 'ZOOP_GRAPH_SNAPSHOT_SOURCE': 'none',
                'ZOOP_GRAPH_AUTO_ACTIVATION_ENABLED': 'false',
                'ZOOP_INGESTION_CLI': '/unavailable/zoop-ai-ingest',
                'ZOOP_HANDOFF_CLI': '/unavailable/zoop-ai-handoff',
                'PYTHON': '/unavailable/python'}

    def argv(self, *extra):
        flags = ('--spring.flyway.enabled=false', '--spring.jpa.hibernate.ddl-auto=validate',
                 '--spring.sql.init.mode=never') if self.migrated else ()
        properties = {argument.split('=', 1)[0]: argument for argument in (*flags, *extra)}
        return isolate(self.denied, python=True) + super().argv(*properties.values())


class Delivery(delivery.Delivery):
    def start(self, label, command, *, request=None, version=None, digest=None, root=None, destination=DESTINATION, extra=None):
        if command != 'install':
            return super().start(label, command, request=request, version=version, digest=digest,
                                 root=root, destination=destination, extra=extra)
        self.count += 1
        result = self.smoke.layout.requests / f'delivery-{self.count:03d}-{label}.json'
        jar = Jar(self.smoke.args.java, self.smoke.args.jar, self.smoke.db, self.smoke.layout,
                  denied=(*self.smoke.jar.denied, self.smoke.world.root, self.smoke.layout.artifacts))
        jar.migrated = self.smoke.jar.migrated
        env = {**jar.base_env(), 'ZOOP_GRAPH_DELIVERY_INSTALL_ENABLED': 'true',
               'ZOOP_GRAPH_DELIVERY_INSTALL_DESTINATION_ID': destination,
               'ZOOP_GRAPH_DELIVERY_INSTALL_VERSION_ID': version,
               'ZOOP_GRAPH_DELIVERY_INSTALL_EXPECTED_PACKAGE_DIGEST': digest,
               'ZOOP_GRAPH_DELIVERY_INSTALL_ARTIFACT_ROOT': str(root or self.root),
               'ZOOP_GRAPH_DELIVERY_INSTALL_RESULT': str(result),
               'ZOOP_DOCUMENT_READ_INGESTION_SOURCES': str(self.registry), **(extra or {})}
        with result.with_suffix('.log').open('xb') as output:
            process = subprocess.Popen(jar.argv('--spring.main.web-application-type=none'), env=env,
                                       cwd=self.smoke.root, stdout=output, stderr=subprocess.STDOUT)
        self.processes.append(process)
        return process, result, label


class Harness:
    def __init__(self, args, root, db, report):
        self.args, self.root, self.db, self.report = args, root, db, report
        self.layout = SimpleNamespace(work=root, root=root, artifacts=root / 'producer-artifacts', requests=root / 'requests')
        for path in (self.layout.artifacts, self.layout.requests, root / 'http', root / 'receipts', root / 'serving-artifacts'):
            path.mkdir(mode=0o700)
        self.world = SimpleNamespace(root=root / 'native')
        self.jar = Jar(args.java, args.jar, db, self.layout)
        self.services, self.runs = [], []
        self.authority = root / 'serving-authorities.json'
        self.authority_leaves = []
        self.counter = 0
        self.source_snapshots = {}
        self.auth = None
        self.decisions = root / 'compose-decisions.json'
        save(self.decisions, {'schemaVersion': 'zoop-graph-publication-decisions-1',
                             'issueMappings': [], 'fieldSelections': [], 'relationSelections': []})

    def record(self, name, condition, **facts):
        self.report['steps'].append({'step': name, 'status': 'passed' if condition else 'failed', **facts})
        check(condition, name)

    def operator(self, label, env=None, *, request=None, prefix=None, expected=None):
        self.counter += 1
        stem = f'{self.counter:03d}-{label}'
        result = self.layout.requests / (stem + '.json')
        settings = dict(env or {})
        if prefix:
            settings[prefix + '_ENABLED'] = 'true'
            settings[prefix + '_RESULT'] = str(result)
        if request is not None:
            request_path = self.layout.requests / (stem + '.request.json')
            save(request_path, request)
            settings[prefix + '_REQUEST'] = str(request_path)
        environment = self.jar.base_env()
        if (settings.get('ZOOP_DOCUMENT_IMPORT_OBSERVATION_SOURCE') == 'http'
                or settings.get('ZOOP_GRAPH_HANDOFF_IMPORT_OBSERVATION_SOURCE') == 'http'):
            environment.pop('ZOOP_INGESTION_CLI')
        if settings.get('ZOOP_GRAPH_HANDOFF_IMPORT_HANDOFF_SOURCE') == 'http':
            environment.pop('ZOOP_HANDOFF_CLI')
        environment.update(settings)
        done = subprocess.run(self.jar.argv('--spring.main.web-application-type=none'),
                              env=environment, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=420, cwd=self.root)
        (self.layout.requests / (stem + '.log')).write_bytes(done.stdout.replace(self.db.password.encode(), b'[redacted]'))
        value = load(result) if result.is_file() and result.stat().st_size else None
        self.report['commands'].append({'step': label, 'exitCode': done.returncode, 'result': str(result), 'resultPresent': value is not None})
        if expected is not None:
            self.record(label, done.returncode == 0 and value is not None and value.get('status') == 'succeeded'
                        and (expected == 'succeeded' or value.get('outcome') == expected), result=value)
        return done.returncode, value

    def artifact(self, ident, root=None):
        rows = self.db.rows('SELECT id,kind,storage_uri,sha256,bytes FROM artifacts WHERE id=' + SQL(ident))
        check(len(rows) == 1, 'missing registered artifact: ' + ident)
        row = rows[0]
        path = (root or self.layout.artifacts) / row['storage_uri'].split(':', 1)[1]
        check(path.stat().st_size == row['bytes'] and sha(path) == row['sha256'], 'registered artifact pin mismatch')
        return row, load(path)

    def source(self, version):
        row, receipt = self.artifact('artifact-receipt-' + version)
        _, snapshot = self.artifact('artifact-' + version)
        self.source_snapshots[version] = snapshot
        return SimpleNamespace(version=version, receipt_pin=row['sha256'], receipt=receipt, snapshot=snapshot)

    def copy_authorities(self, registries):
        routes = []
        for index, original in enumerate(dict.fromkeys(map(Path, registries))):
            leaf = self.root / f'serving-source-{index}.json'
            leaf.write_bytes(original.read_bytes())
            leaf.chmod(0o600)
            self.authority_leaves.append(leaf)
            for source in load(leaf)['sources']:
                grant = source['grant']
                routes.append({'sourceId': source['sourceId'], 'grantId': grant['grantId'],
                               'revision': grant['revision'], 'sources': str(leaf)})
        check(len({(r['sourceId'], r['grantId'], r['revision']) for r in routes}) == len(routes), 'authority routes must be unique')
        save(self.authority, {'schemaVersion': 'zoop-source-authority-set-1', 'authorities': routes})

    def native_wrapper(self, module, name):
        path = self.root / name
        path.write_text(f'#!{sys.executable}\nimport sys, runpy\nsys.path.insert(0, {str(REPO / "ai/pipeline/src")!r})\n'
                        + hs.GUARD + f'runpy.run_module({module!r}, run_name="__main__")\n')
        path.chmod(0o700)
        return path

    def service(self, label, world, command, allowlist=None):
        service = http_native.read_service(self.args, self.root / label, world, command, allowlist)
        self.services.append(service)
        return service

    def native_cli(self, label, command, request):
        world = self.world
        argv = [str(self.args.handoff_cli), command, '--state-dir', str(world.root / 'handoff'),
                '--source-contexts', str(world.context_file), '--source-contexts-sha256', world.context_sha,
                '--canonical', str(world.root / 'canonical.json'), '--decisions', str(world.root / 'decisions.json'),
                '--bindings', str(world.root / 'bindings.json')]
        env = {'PATH': os.defpath, 'HOME': str(Path.home()), 'PYTHONDONTWRITEBYTECODE': '1',
               'ZOOP_STATE_DIR': str(self.root / 'reserved-app'), 'ZOOP_AI_WORKER_STATE_DIR': str(self.root / 'reserved-worker')}
        done = subprocess.run(argv, input=base.json_bytes(request), env=env, capture_output=True, timeout=420, cwd=self.root)
        (self.root / (label + '.stdout')).write_bytes(done.stdout)
        (self.root / (label + '.stderr')).write_bytes(done.stderr)
        self.record(label, done.returncode == 0, exitCode=done.returncode)
        return json.loads(done.stdout)

    def import_native(self, manifest, expected_ids):
        command = self.native_wrapper('zoop_ai_pipeline.ingestion_cli', 'zoop-ai-ingest-read')
        self.args.handoff_cli = self.native_wrapper('zoop_ai_pipeline.handoff_cli', 'zoop-ai-handoff-read')
        self.args.exposure_cli = self.native_wrapper('zoop_ai_pipeline.handoff_exposure_cli', 'zoop-ai-exposure-read')
        selectors = [ref for context in load(self.world.context_file)['contexts'] for ref in context['observations']]
        service = self.service('observation-http', self.world, command)
        try:
            for identity, expected in ((None, 401), ('reader', 403)):
                response = service.request('POST', http_native.OBSERVATIONS, as_=identity,
                                           body={'schemaVersion': base.SCHEMA, **selectors[0]})
                self.record('observation-auth-' + str(expected), response.status_code == expected)
            for index, ref in enumerate(selectors):
                response = service.request('POST', http_native.OBSERVATIONS, as_='handoffer',
                                           body={'schemaVersion': base.SCHEMA, **ref})
                self.record('observation-exact-' + str(index), response.status_code == 200
                            and all(response.json()['observation'][key] == value for key, value in ref.items())
                            and response.headers.get('cache-control') == 'no-store')
                save(self.root / f'observation-{index:02d}.json', response.json())
            self.operator('http-document-registration', {**http_native.clients(service),
                'ZOOP_DOCUMENT_IMPORT_OBSERVATION_SOURCE': 'http', 'ZOOP_ARTIFACT_ROOT': str(self.layout.artifacts)},
                prefix='ZOOP_DOCUMENT_IMPORT', request={'schemaVersion': base.IMPORT_SCHEMA, 'items': [base.item(ref) for ref in selectors]}, expected='succeeded')
        finally:
            service.close()
        self.record('registered-actual-selector-set', {(r['article_id'], r['version']) for r in self.db.versions()}
                    == {(ref['documentId'], ref['documentVersion']) for ref in selectors})
        bindings = self.root / 'target-bindings.json'
        self.operator('target-derived-bindings', {'ZOOP_DOCUMENT_BINDINGS_OUTPUT': str(bindings)},
                      prefix='ZOOP_DOCUMENT_BINDINGS', expected='succeeded')
        (self.world.root / 'bindings.json').write_bytes(bindings.read_bytes())
        manifest['files'] = hs.file_hashes(self.world.root)
        save(self.world.root / 'manifest.json', manifest)
        frozen = self.native_cli('handoff-freeze', 'freeze', manifest)
        exported = self.native_cli('handoff-export', 'export', {'schemaVersion': 'zoop-ai-handoff-1', 'handoffId': manifest['handoffId']})
        bundle = exported['bundle']
        self.record('native9-p3-fixed-selection', bundle['schemaVersion'] == 'zoop-graph-handoff-bundle-9'
                    and bundle['policy']['version'] == 'zoop-public-projection-policy-3'
                    and {issue['id'] for issue in bundle['issues']} == expected_ids)
        save(self.root / 'native-bundle.json', bundle)
        if self.args.mode == 'actual':
            prior = load(self.args.actual_native_root / 'bundle.json')
            fields = ('id', 'title', 'action', 'target', 'assertionStatus', 'eventTime', 'timePrecision', 'period', 'mentions')
            before = {item['id']: {key: item[key] for key in fields} for item in prior['issues']}
            after = {item['id']: {key: item[key] for key in fields} for item in bundle['issues']}
            self.record('actual-native-original-core-preserved', before == after)
            self.record('actual-native-original-proof-preserved', all(bundle[key] == prior[key]
                        for key in ('evidence', 'impacts', 'relations', 'sources')))
        allowlist = self.root / 'handoff-exports.json'
        save(allowlist, {'schemaVersion': 'zoop-ai-handoff-exports-1', 'handoffs': [{'principal': 'handoffer',
             'handoffId': manifest['handoffId'], 'manifestDigest': frozen['receipt']['manifestDigest'],
             'bundleDigest': frozen['receipt']['bundleDigest']}]})
        service = self.service('handoff-http', self.world, command, allowlist)
        try:
            route = '/internal/v1/graph-handoffs/' + manifest['handoffId'] + '/bundle'
            for identity, expected in ((None, 401), ('reader', 403)):
                response = service.request('GET', route, as_=identity)
                self.record('handoff-auth-' + str(expected), response.status_code == expected)
            response = service.request('GET', route, as_='handoffer')
            self.record('http-handoff-exact-bundle', response.status_code == 200 and response.json()['bundle'] == bundle)
            request = graph.Smoke.request(manifest['handoffId'], frozen['receipt']['manifestDigest'], frozen['receipt']['bundleDigest'])
            _, result = self.operator('http-native-import', {**http_native.clients(service, handoff=True),
                'ZOOP_GRAPH_HANDOFF_IMPORT_HANDOFF_SOURCE': 'http', 'ZOOP_GRAPH_HANDOFF_IMPORT_OBSERVATION_SOURCE': 'http',
                'ZOOP_ARTIFACT_ROOT': str(self.layout.artifacts)}, prefix='ZOOP_GRAPH_HANDOFF_IMPORT', request=request, expected='staged')
        finally:
            service.close()
        self.record('native-import-inactive', result['active'] is False)
        source = self.source(result['graphVersionId'])
        self.record('native-import-original-proof', source.receipt['bundle'] == bundle)
        return source

    def import_legacy(self, label, package_root, request, expected_ids):
        _, result = self.operator(label, {'ZOOP_LEGACY_REAL_IMPORT_PACKAGE_ROOT': str(package_root),
            'ZOOP_LEGACY_REAL_IMPORT_SOURCES': str(self.authority), 'ZOOP_LEGACY_REAL_IMPORT_ARTIFACT_ROOT': str(self.layout.artifacts)},
            prefix='ZOOP_LEGACY_REAL_IMPORT', request=request, expected='staged')
        source = self.source(result['graphVersionId'])
        self.record(label + '-fixed-selection', {issue['issueId'] for issue in source.snapshot['issues']} == expected_ids)
        retained = load(package_root / 'bundle.json')
        self.record(label + '-original-core-and-audit', all(source.receipt['legacyProvenance'][field] == retained[field]
                    for field in ('origin', 'companies', 'candidate_audit', 'effective_review_decisions', 'enabled_rules', 'review_exclusions')))
        originals = {issue['issue_id']: issue for issue in retained['issues']}
        self.record(label + '-source-supported-headlines', all(
            (issue['label'], issue['action'], issue['assertionStatus'], issue['target']) in
            {(mention['title'], mention['action'], mention['assertion_status'], mention.get('target'))
             for mention in originals[issue['issueId']]['mentions']}
            for issue in source.snapshot['issues']))
        return source

    def compose_request(self, incoming, base_source=None):
        return {'schemaVersion': 'zoop-graph-publication-compose-1',
                'baseVersionId': base_source.version if base_source else None,
                'incomingVersionIds': sorted(source.version for source in incoming),
                'expectedActiveVersionId': self.db.scalar('SELECT id FROM graph_versions WHERE active'),
                'expectedBaseReceiptSha256': base_source.receipt_pin if base_source else None,
                'incomingReceiptPins': sorted([{'versionId': source.version, 'sha256': source.receipt_pin} for source in incoming], key=lambda row: row['versionId']),
                'expectedRuleRevision': self.db.scalar('SELECT COALESCE(MAX(log_revision),0) FROM publication_rule_changes'),
                'expectedReviewRevision': self.db.scalar('SELECT COALESCE(MAX(global_revision),0) FROM review_decisions'),
                'decisionsSha256': sha(self.decisions), 'operator': 'cumulative-local-proof'}

    def compose(self, label, incoming, base_source=None, *, request=None, failure=None):
        request = request or self.compose_request(incoming, base_source)
        before = activation.publication_state(self.db)
        code, result = self.operator(label, {'ZOOP_GRAPH_PUBLICATION_COMPOSE_DECISIONS': str(self.decisions),
            'ZOOP_GRAPH_PUBLICATION_COMPOSE_ARTIFACT_ROOT': str(self.layout.artifacts),
            'ZOOP_DOCUMENT_READ_INGESTION_SOURCES': str(self.authority)},
            prefix='ZOOP_GRAPH_PUBLICATION_COMPOSE', request=request, expected=None if failure else 'staged')
        if failure:
            self.record(label, code != 0 and result == {'schemaVersion': 'zoop-graph-publication-compose-result-1', 'status': 'failed', 'code': failure}
                        and activation.publication_state(self.db) == before)
            return None
        source = self.source(result['graphVersionId'])
        self.record(label + '-inactive-pointer-preserved', result['activation'] == 'not-activated'
                    and self.db.scalar('SELECT id FROM graph_versions WHERE active') == before['active']
                    and self.db.rows('SELECT * FROM graph_activations ORDER BY id') == before['activations'])
        self.record(label + '-receipt-file-pin', result['receiptSha256'] == source.receipt_pin)
        originals = [*incoming] + ([base_source] if base_source else [])
        expected = {issue['issueId']: issue for original in originals for issue in original.snapshot['issues']}
        observed = {issue['issueId']: issue for issue in source.snapshot['issues']}
        self.record(label + '-all-original-issue-records', set(observed) == set(expected))
        self.record(label + '-exact-core-fields', all(all(observed[ident][key] == issue[key] for key in CORE_FIELDS) for ident, issue in expected.items()))
        self.record(label + '-flat-original-leaves', all(item['sourceKind'] in ('native', 'legacy-real')
                    and item['sourceVersionId'] not in {source.version, base_source.version if base_source else None}
                    for item in source.receipt['basis']['sources']))
        source.result = result
        return source

    def retain_published_headlines(self, publication, original, incoming):
        """Main's retain-old-headline decision, bound to this run's genuine original versions."""
        current = {issue['issueId']: issue for issue in publication.snapshot['issues']}
        old = {issue['issueId']: issue for issue in original.snapshot['issues']}
        new = {issue['issueId']: issue for issue in incoming.snapshot['issues']}
        self.record('legacy22-retains-reviewed17', set(old) <= set(new))
        selections = []
        for ident in sorted(set(old) & set(new)):
            for field in ('label', 'action', 'target', 'assertionStatus', 'eventTime', 'period', 'geography'):
                keys = (('eventTime', 'timePrecision') if field == 'eventTime' else
                        ('geography', 'geographyPolicyVersion', 'geographyEvidenceIds') if field == 'geography' else ())
                value = {key: current[ident][key] for key in keys} if keys else current[ident][field]
                selections.append({'issueId': ident, 'field': field,
                    'expectedValueDigest': hashlib.sha256(base.json_bytes(value)).hexdigest(),
                    'takeFrom': {'sourceVersionId': original.version, 'issueId': ident},
                    'evidenceRefs': [{'sourceVersionId': original.version, 'issueId': ident, 'evidenceId': old[ident]['evidenceIds'][0]}],
                    'reviewer': 'cumulative-local-proof',
                    'decisionRef': 'morning-cumulative-contract:retain-published-headlines', 'decisionVersion': '2026-10-31'})
        self.decisions = self.root / 'carryforward-decisions.json'
        save(self.decisions, {'schemaVersion': 'zoop-graph-publication-decisions-1',
                             'issueMappings': [], 'fieldSelections': selections, 'relationSelections': []})
        save(self.root / 'carryforward-decision-basis.json', {
            'baseVersionId': publication.version, 'baseReceiptSha256': publication.receipt_pin,
            'originalVersionId': original.version, 'originalReceiptSha256': original.receipt_pin,
            'incomingVersionId': incoming.version, 'incomingReceiptSha256': incoming.receipt_pin,
            'decision': 'Retain all seven published headline fields for the original seventeen issue IDs.',
            'sameEventMappings': [], 'decisionsSha256': sha(self.decisions)})

    def seal_install(self, label, source):
        runner = Delivery(self, self.root / 'serving-artifacts', self.authority, self.report, self.root / 'receipts')
        self.runs.append(runner)
        before = activation.publication_state(self.db)
        sealed = runner.succeeded(label + '-seal', 'seal-publication', 'sealed', request={
            'schemaVersion': 'zoop-graph-publication-seal-1', 'graphVersionId': source.version,
            'expectedReceiptSha256': source.receipt_pin, 'destinationId': DESTINATION, 'operator': 'cumulative-local-proof'}, destination=DESTINATION)
        row = self.db.rows('SELECT manifest,handoff_id,manifest_digest,bundle_digest,publication_id,publication_receipt_sha256 '
                           'FROM graph_delivery_packages WHERE version_id=' + SQL(source.version))[0]
        manifest = json.loads(row['manifest'])
        self.record(label + '-package3-truthful-pins', manifest['schemaVersion'] == 'zoop-graph-delivery-package-3'
                    and manifest['publicationId'] == source.result['publicationId']
                    and manifest['publicationReceiptSha256'] == source.receipt_pin
                    and all(row[key] is None for key in ('handoff_id', 'manifest_digest', 'bundle_digest')))
        expected_artifacts = {'artifact-' + source.version, 'artifact-receipt-' + source.version}
        for original in source.receipt['basis']['sources']:
            expected_artifacts.update((original['receipt']['artifactId'], original['projection']['artifactId']))
            original_receipt = self.artifact(original['receipt']['artifactId'])[1]
            for article in original_receipt['bundle']['articles']:
                text = self.db.scalar('SELECT text_artifact_id FROM article_versions WHERE article_id=' + SQL(article['articleId'])
                                      + ' AND version=' + SQL(article['articleVersion']))
                expected_artifacts.add(text)
        self.record(label + '-full-flat-closure', {item['artifactId'] for item in manifest['files']} == expected_artifacts)
        authority_leaf = self.authority_leaves[0]
        original_authority = authority_leaf.read_bytes()
        revoked = json.loads(original_authority)
        revoked['sources'][0]['grant']['allowedOperations'].remove('quote-display')
        try:
            save(authority_leaf, revoked)
            runner.refused(label + '-install-current-rights', 'rights_denied', version=source.version,
                           digest=sealed['packageDigest'], destination=DESTINATION)
        finally:
            authority_leaf.write_bytes(original_authority)
        runner.succeeded(label + '-java-only-install', 'install', 'installed', version=source.version,
                         digest=sealed['packageDigest'], destination=DESTINATION)
        for item in manifest['files']:
            path = self.root / 'serving-artifacts' / item['storageUri'].split(':', 1)[1]
            self.record(label + '-installed-' + item['artifactId'], path.stat().st_size == item['bytes'] and sha(path) == item['sha256'])
        self.record(label + '-delivery-no-activation', activation.publication_state(self.db) == before)
        save(self.root / (label + '-package.json'), manifest)
        return runner

    def web(self, *, producer=False):
        self.auth = self.auth or activation.bootstrap_session(self.db)
        root = self.layout.artifacts if producer else self.root / 'serving-artifacts'
        denied = (*self.jar.denied, self.world.root) + (() if producer else (self.layout.artifacts,))
        jar = Jar(self.args.java, self.args.jar, self.db, self.layout, denied=denied)
        jar.migrated = True
        key = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
        return activation.Web(jar, {'ZOOP_GRAPH_SNAPSHOT_SOURCE': 'artifact',
            'ZOOP_GRAPH_SNAPSHOT_ARTIFACT_ROOT': str(root),
            'ZOOP_DOCUMENT_READ_ARTIFACT_ROOT': str(root),
            'ZOOP_DOCUMENT_READ_INGESTION_SOURCES': str(self.authority), 'SPRING_PROFILES_ACTIVE': 'local',
            'ZOOP_AUTH_CSRF_ACTIVE_KEY_ID': 'activation-test', 'ZOOP_AUTH_CSRF_KEYS': 'activation-test=' + key,
            'ZOOP_AUTH_ALLOWED_ORIGINS': activation.ORIGIN, 'ZOOP_API_CORS_ALLOWED_ORIGINS': activation.ORIGIN})

    def expect(self, web, label, path, status=200, **kwargs):
        code, raw, _ = web.request(path, **kwargs)
        body = json.loads(raw)
        self.counter += 1
        save(self.root / 'http' / f'{self.counter:04d}-{label}.json', {'status': code, 'path': path, 'body': body})
        self.record(label, code == status, statusCode=code)
        return body

    def activate(self, web, source, *, status=200, mode='forward', expected=None, label='activate'):
        session = self.expect(web, label + '-session', '/api/v1/admin/auth/session', headers=self.auth)
        headers = {**self.auth, 'Origin': activation.ORIGIN, 'Content-Type': 'application/json',
                   'X-CSRF-Token': session['csrfToken'], 'Idempotency-Key': f'cumulative-{label}-{self.counter}'}
        previous = self.db.scalar('SELECT id FROM graph_versions WHERE active')
        answer = self.expect(web, label, '/api/v1/admin/graph/versions/' + source.version + '/activate', status,
                    payload={'reason': 'Isolated cumulative publication proof: ' + label.replace('-', ' '),
                             'expectedActiveVersionId': previous if expected is None else expected, 'mode': mode}, headers=headers)
        if status in (409, 422):
            expected_error = 'REVISION_CONFLICT' if status == 409 else 'INVALID_REQUEST'
            self.record(label + '-refusal-category', answer['error']['code'] == expected_error)
        self.record(label + '-pointer', self.db.scalar('SELECT id FROM graph_versions WHERE active') == (source.version if status == 200 else previous))

    def public(self, web, source, expected_ids, label):
        context = urlencode({'graphVersion': source.version})
        public = self.expect(web, label + '-graph', '/api/v1/graph?mode=all&' + context)
        context = urlencode({'graphVersion': source.version, 'asOf': public['metadata']['asOf']})
        issues = {node['id']: node for node in public['nodes'] if node['kind'] == 'issue'}
        self.record(label + '-exact-issue-records', set(issues) == expected_ids)
        expected = {item['issueId']: item for item in source.snapshot['issues']}
        for ident in sorted(expected_ids):
            issue = expected[ident]
            self.record(label + '-graph-core-' + ident, all(issues[ident][key] == issue[key]
                        for key in ('label', 'eventTime', 'timePrecision', 'action', 'target', 'geography')))
            event = self.expect(web, label + '-event', '/api/v1/events/' + quote(ident, safe='') + '?' + context)
            self.record(label + '-event-core-' + ident, event['id'] == ident and event['title'] == issue['label']
                        and all(event[key] == issue[key] for key in ('eventTime', 'timePrecision', 'period'))
                        and bool(event['companies']) and event['metadata']['graphVersion'] == source.version)
        expected_edges = {(r['source'], r['target'], r['relationType']) for r in source.snapshot['relations']
                          if (r['source'] not in expected or r['source'] in expected_ids)
                          and (r['target'] not in expected or r['target'] in expected_ids)}
        actual_edges = {(edge['source'], edge['target'], edge['relationType']) for edge in public['edges'] if not edge['derived']}
        self.record(label + '-direct-endpoint-type-identity', actual_edges == expected_edges)
        direct = {(r['source'], r['target']) for r in source.snapshot['relations'] if r['relationType'] == 'INVOLVES' and r['source'] in expected_ids}
        for edge in public['edges']:
            if edge['derived']:
                self.record(label + '-derived-owner-path', edge['relationType'] == 'SHARES_ISSUE' and bool(edge['via'])
                            and all((via, edge['source']) in direct and (via, edge['target']) in direct for via in edge['via']))
        documents_seen = set()
        articles = {(item['articleId'], item['version']): item for item in source.snapshot['articles']}
        for company in source.snapshot['companies']:
            ident = quote(company['companyId'], safe='')
            detail = self.expect(web, label + '-company', '/api/v1/companies/' + ident + '?' + context)
            self.record(label + '-company-canonical-links', detail['id'] == company['companyId'] and detail['name'] == company['label']
                        and {item['issueId'] for item in detail['directIssues']} == {issue for issue, cid in direct if cid == company['companyId']})
            self.expect(web, label + '-company-graph', '/api/v1/companies/' + ident + '/graph?' + context)
            documents = self.expect(web, label + '-company-documents', '/api/v1/companies/' + ident + '/documents?limit=100&' + context)
            self.record(label + '-document-page-complete', documents['nextCursor'] is None)
            for document in documents['items']:
                key = (document['id'], document['documentVersion'])
                self.record(label + '-document-version-and-content', key in articles and
                            all(document[field] == articles[key][field] for field in ('title', 'url')))
                documents_seen.add(key)
        self.record(label + '-all-source-articles-readable', documents_seen == set(articles))
        for issue, company in sorted(direct):
            impact = self.expect(web, label + '-impact', '/api/v1/companies/' + quote(company, safe='')
                + '/issues/' + quote(issue, safe='') + '/impact?' + context)
            self.record(label + '-impact-pin', impact['companyId'] == company and impact['issueId'] == issue
                        and impact['metadata']['graphVersion'] == source.version and impact['pathStatus'] == 'direct_available')
        for evidence in source.snapshot['evidence']:
            answer = self.expect(web, label + '-evidence', '/api/v1/evidence/' + evidence['evidenceId'] + '?' + context)
            text_id = self.db.scalar('SELECT text_artifact_id FROM article_versions WHERE article_id=' + SQL(evidence['articleId'])
                                     + ' AND version=' + SQL(evidence['articleVersion']))
            row = self.db.rows('SELECT storage_uri FROM artifacts WHERE id=' + SQL(text_id))[0]
            text = (self.root / 'serving-artifacts' / row['storage_uri'].split(':', 1)[1]).read_text()
            self.record(label + '-exact-unicode-span', answer['quoteVerified'] is True
                        and answer['quote'] == text[evidence['start']:evidence['end']]
                        and all(answer[key] == evidence[key] for key in ('articleVersion', 'start', 'end')))
        return public

    def exclusion(self, label, request, expected='applied'):
        _, result = self.operator(label, {'ZOOP_DISCLOSURE_EXCLUSION_ARTIFACT_ROOT': str(self.layout.artifacts),
            'ZOOP_DOCUMENT_READ_INGESTION_SOURCES': str(self.authority)}, prefix='ZOOP_DISCLOSURE_EXCLUSION',
            request=request, expected=expected)
        return result

    def native_rights(self, web, publication, native_source, legacy_ids):
        articles = native_source.receipt['bundle']['articles']
        observed = articles[0]['observations'][0]
        wanted = (observed['sourceId'], observed['grant']['grantId'], observed['grant']['revision'])
        denied_articles = {article['articleId'] for article in articles if any(
            (item['sourceId'], item['grant']['grantId'], item['grant']['revision']) == wanted
            for item in article['observations'])}
        denied_issues = {issue['issueId'] for issue in native_source.snapshot['issues']
                         if denied_articles.intersection(issue['articleIds'])}
        evidence = next(item['evidenceId'] for item in native_source.snapshot['evidence'] if item['articleId'] in denied_articles)
        leaf = next(path for path in self.authority_leaves if any(
            (item['sourceId'], item['grant']['grantId'], item['grant']['revision']) == wanted for item in load(path)['sources']))
        raw = leaf.read_bytes()
        changed = json.loads(raw)
        for item in changed['sources']:
            if (item['sourceId'], item['grant']['grantId'], item['grant']['revision']) == wanted:
                item['grant']['allowedOperations'].remove('store')
        try:
            save(leaf, changed)
            public = self.expect(web, 'native-current-rights-graph', '/api/v1/graph?graphVersion=' + publication.version)
            ids = {node['id'] for node in public['nodes'] if node['kind'] == 'issue'}
            self.record('native-current-rights-selective', bool(denied_issues) and not denied_issues & ids and legacy_ids <= ids)
            self.expect(web, 'native-current-rights-evidence', '/api/v1/evidence/' + evidence + '?graphVersion=' + publication.version, 404)
            self.activate(web, publication, status=409, label='active-publication-current-rights-refused')
        finally:
            leaf.write_bytes(raw)

    def overlays(self, web, publication, original, other_ids, historical=()):
        original_ids = {issue['issueId'] for issue in original.snapshot['issues']}
        candidates = [(issue['issueId'], evidence) for issue in original.snapshot['issues'] for evidence in issue['evidenceIds']
                      if all(evidence not in other['evidenceIds'] for other in publication.snapshot['issues'] if other['issueId'] != issue['issueId'])
                      and all(evidence not in relation['evidenceIds'] for relation in publication.snapshot['relations'] if relation['source'] != issue['issueId'])]
        check(candidates, 'requires an exclusively owned evidence span for exclusion propagation')
        target, evidence_id = sorted(candidates)[0]
        # Legacy source has one exact grant scope in this fixture and in the reviewed actual selection.
        grant_pins = original.receipt['manifest']['grantBindings']
        wanted = {(row['sourceId'], row['grantId'], row['revision']) for row in grant_pins}
        leaf = next(path for path in self.authority_leaves if any((s['sourceId'], s['grant']['grantId'], s['grant']['revision']) in wanted for s in load(path)['sources']))
        raw = leaf.read_bytes()
        revoked = json.loads(raw)
        for item in revoked['sources']:
            if (item['sourceId'], item['grant']['grantId'], item['grant']['revision']) in wanted:
                item['grant']['allowedOperations'].remove('quote-display')
        try:
            save(leaf, revoked)
            for selected in (publication, *historical):
                body = self.expect(web, 'current-rights-graph', '/api/v1/graph?graphVersion=' + selected.version)
                ids = {item['id'] for item in body['nodes'] if item['kind'] == 'issue'}
                self.record('current-rights-source-selective', not ids & original_ids and other_ids <= ids)
                self.expect(web, 'current-rights-event', '/api/v1/events/' + target + '?graphVersion=' + selected.version, 404)
                self.expect(web, 'current-rights-evidence', '/api/v1/evidence/' + evidence_id + '?graphVersion=' + selected.version, 404)
        finally:
            leaf.write_bytes(raw)
        request = {'schemaVersion': 'zoop-disclosure-exclusion-1', 'action': 'exclude-publication',
                   'requestId': 'exclude-' + publication.version, 'operator': 'cumulative-local-proof',
                   'reason': 'Isolated source ownership propagation proof', 'graphVersionId': publication.version,
                   'receiptSha256': publication.receipt_pin, 'targets': [{'kind': 'issue', 'id': target}]}
        result = self.exclusion('publication-exclusion', request)
        self.exclusion('empty-publication-exclusion', {**request, 'requestId': 'empty-' + publication.version, 'targets': []}, expected='unchanged')
        for selected in (publication, *historical):
            body = self.expect(web, 'excluded-graph', '/api/v1/graph?graphVersion=' + selected.version)
            self.record('exclusion-cascades-endpoints', target not in {node['id'] for node in body['nodes']}
                        and all(target not in (edge['source'], edge['target']) and target not in edge['via'] for edge in body['edges']))
            self.expect(web, 'excluded-event', '/api/v1/events/' + target + '?graphVersion=' + selected.version, 404)
            self.expect(web, 'excluded-evidence', '/api/v1/evidence/' + evidence_id + '?graphVersion=' + selected.version, 404)
        ownership = next(item for item in publication.receipt['issueSources'] if item['issueId'] == target)
        scopes = sorted({item['sourceVersionId'] for item in ownership['members']})
        for index, version in enumerate(scopes):
            result = self.exclusion('explicit-original-source-lift', {'schemaVersion': 'zoop-disclosure-exclusion-1', 'action': 'lift',
                'requestId': 'lift-' + publication.version + '-' + str(index), 'operator': 'cumulative-local-proof',
                'reason': 'Restore isolated proof target', 'graphVersionId': version,
                'expectedRevision': result['revision'], 'targets': request['targets']})
            if index + 1 < len(scopes):
                self.expect(web, 'other-source-exclusion-still-applies', '/api/v1/events/' + target + '?graphVersion=' + publication.version, 404)
        for selected in (publication, *historical):
            self.expect(web, 'lifted-event', '/api/v1/events/' + target + '?graphVersion=' + selected.version)


def actual_inputs(h):
    args, root = h.args, h.root
    native, legacy_root = args.actual_native_root, args.actual_legacy_root
    selection = pin(legacy_root / 'NEXT_IMPORT_INPUTS.json', args.actual_selection_sha256)
    native_pins = pin(native / 'FILE_SHA_MANIFEST.json', args.actual_native_manifest_sha256)
    for filename in ('canonical-registry.json', 'public-decisions.json', 'source-contexts.json', 'handoff-manifest.json',
                     'bundle.json', 'database-registered.json', 'source-preserved-before.json'):
        pin(native / filename, native_pins[filename]['sha256'])
    prepared = pin(legacy_root / 'LEGACY3_INPUT_HANDOFF.json', args.actual_prepared_sha256)
    overlap = pin(args.overlap_review, args.overlap_review_sha256)
    save(root / 'reviewed-overlaps.json', overlap)
    h.record('reviewed-overlap-classifications', sorted(item['classification'] for item in overlap['pairs'])
             == ['BROADER_NARROWER_OVERLAP'] * 3 + ['DISTINCT_STAGE']
             and overlap['coverage']['independentEventCardinality'] is None)
    h.actual_selection, h.actual_prepared = selection, prepared
    for item in [*prepared['files'], *prepared['sourceFiles']]:
        pin(Path(item['path']), item['sha256'])
    frozen_manifest = Path(selection['frozenLegacy17']['path'])
    pin(frozen_manifest, selection['frozenLegacy17']['sha256'])
    for field in ('original97', 'sourceAuthority'):
        pin(Path(selection[field]['path']), selection[field]['sha256'])
    source_roots = set(load(native / 'source-preserved-before.json'))
    source_roots.update((str(native), str(legacy_root), str(frozen_manifest.parent.parent),
                         str(Path(selection['original97']['path']).parent), str(Path(selection['sourceAuthority']['path']).parent)))
    source_roots.update(str(Path(path).parent) for path in prepared['sourcePreservation'])
    h.report['preservationRoots'] = sorted(source_roots)
    h.originals = {name: fingerprint(Path(name)) for name in sorted(source_roots)}
    save(root / 'preservation-before.json', h.originals)
    world_root = root / 'native'
    world_root.mkdir(mode=0o700)
    for old, new in (('canonical-registry.json', 'canonical.json'), ('public-decisions.json', 'decisions.json'), ('source-contexts.json', 'source-contexts.json')):
        (world_root / new).write_bytes((native / old).read_bytes())
    decisions = load(world_root / 'decisions.json')
    decisions.update(schemaVersion='zoop-public-decisions-5', policyVersion='zoop-public-projection-policy-3')
    save(world_root / 'decisions.json', decisions)
    h.world = SimpleNamespace(root=world_root, context_file=world_root / 'source-contexts.json', context_sha=sha(world_root / 'source-contexts.json'))
    contexts = load(h.world.context_file)['contexts']
    h.copy_authorities([Path(context['sources']) for context in contexts] + [Path(selection['sourceAuthority']['path'])])
    h.jar.denied = tuple(Path(name) for name in source_roots) + (world_root,)
    native_manifest = load(native / 'handoff-manifest.json')
    native_manifest.update(handoffId='cumulative-native-' + root.name, policyVersion='zoop-public-projection-policy-3')
    native_ids = set(selection['nativeIssueIdsPreserve'])
    check(native_ids == {issue['id'] for issue in load(native / 'bundle.json')['issues']}, 'native reviewed selection drift')
    current = load(native / 'database-registered.json')['companies']
    additions = load(frozen_manifest.parent.parent / 'company-additions.json')['companies']
    catalogue = [{key: row[key] for key in ('id', 'name', 'aliases')} for row in current]
    catalogue += [{'id': row['company_id'], 'name': row['name'], 'aliases': row['aliases']} for row in additions]
    h.record('reviewed-catalogue33-union', len(current) == 30 and len(catalogue) == 33 and len({r['id'] for r in catalogue}) == 33)
    if args.legacy_count == 17:
        package_root = root / 'legacy-package'
        import shutil
        shutil.copytree(frozen_manifest.parent, package_root)
        request = load(frozen_manifest.parent.parent / 'import-request.json')
        legacy_ids = set(selection['legacyIssueIdsPreserve'])
        policy = None
    else:
        inputs = prepared['exporterInputArguments']
        package_root = root / 'legacy-package'
        request, _ = package.prepare(Path(inputs['source']), package_root, load(inputs['bindings']),
            load(inputs['company-bindings']), 'cumulative-local-proof', Path(inputs['metadata-policy']))
        legacy_ids = set(selection['allLegacyIssueIdsUnderNewMetadataPolicy'])
        policy = load(inputs['metadata-policy'])
    h.record('reviewed-legacy-exact-selection', set(load(package_root / 'manifest.json')['selectedIssueIds']) == legacy_ids)
    h.report['recordSemantics'] = {'legacyIssueIds': sorted(legacy_ids), 'nativeIssueIds': sorted(native_ids),
        'expectedIssueRecords': len(legacy_ids | native_ids), 'certifiedIndependentEvents': None,
        'sameEventMappings': [], 'overlapReviewSha256': args.overlap_review_sha256}
    return native_manifest, native_ids, package_root, request, legacy_ids, catalogue, policy


def synthetic_legacy(h, label, *, later=False):
    source = h.root / (label + '-source')
    selection, _, bindings = legacy.fixture(source)
    if later:
        original = selection['articles'][0]
        old_id, old_version = original['record']['article_id'], original['article_version']
        record = dict(original['record'])
        record['article_id'] = 'c' * 64
        record['title'] = 'Synthetic later Acme source'
        new_version = package.sha(package.canonical({key: value for key, value in record.items() if key != 'collected_at'}))
        original['record'] = record
        save(source / 'LEGACY_SELECTION.json', selection)
        replacements = {
            'issue-synthetic-lab': 'issue-synthetic-later',
            'relation-synthetic-lab': 'relation-synthetic-later',
            'candidate-synthetic-lab': 'candidate-synthetic-later',
            old_id: record['article_id'], old_version: new_version,
        }
        for filename in ('LEGACY_SELECTION.json', 'GEOGRAPHY_REVIEW.json', 'SOURCE_PROVENANCE.json'):
            text = (source / filename).read_text()
            for previous, current in replacements.items():
                text = text.replace(previous, current)
            (source / filename).write_text(text)
        bindings[0].update(originalArticleId=record['article_id'], originalArticleVersion=new_version)
        selection = load(source / 'LEGACY_SELECTION.json')
    audit = selection['candidate_audit'][0]
    audit['source_audit_record_sha256'] = hashlib.sha256(base.json_bytes(audit)).hexdigest()
    save(source / 'LEGACY_SELECTION.json', selection)
    ident = selection['issues'][0]['issue_id']
    policy = {'schemaVersion': 'zoop-legacy-metadata-policy-1', 'policyVersion': 'legacy-real-projection-3', 'issues': [{
        'issueId': ident, 'sourceAuditDigests': [audit['source_audit_record_sha256']],
        'geography': {'mode': 'unknown', 'reasonCode': 'not-supported'},
        'eventTime': {'mode': 'unknown', 'reasonCode': 'not-supported'}, 'period': {'mode': 'preserve'},
        'decisionRef': 'synthetic-field-withholding', 'decisionVersion': '1'}]}
    policy_path = h.root / (label + '-metadata-policy.json')
    save(policy_path, policy)
    package_root = h.root / (label + '-package')
    request, _ = package.prepare(source, package_root, bindings, legacy.company_bindings(selection), 'synthetic-operator', policy_path)
    return package_root, request, {ident}, policy


def synthetic_inputs(h):
    world = hs.build_context_world(h.root / 'native')
    h.world = world
    decisions = load(world.root / 'decisions.json')
    decisions['companies'][0]['publicId'] = 'SYNTH:CUMULATIVE'
    decisions.update(schemaVersion='zoop-public-decisions-5', policyVersion='zoop-public-projection-policy-3')
    save(world.root / 'decisions.json', decisions)
    (world.root / 'bindings.json').unlink()
    registry = h.root / 'legacy-source-registry.json'
    save(registry, {'schemaVersion': base.SCHEMA, 'revision': 'synthetic-1', 'sources': [{
        'sourceId': 'synthetic-source', 'adapter': 'authored-files', 'inputRoot': str(h.root), 'allowedHosts': ['example.invalid'],
        'scopes': [{'scopeId': 'synthetic', 'selection': 'owned synthetic fixture', 'initialCursor': None, 'articleXPath': None, 'timestampLimitations': ['authored fixture']}],
        'grant': {'grantId': 'synthetic-grant', 'revision': '1', 'sourceId': 'synthetic-source', 'enabled': True, 'rights': 'known',
                  'allowedOperations': ['read', 'store', 'quote-display'], 'recipients': [], 'purposes': [],
                  'evidence': ['operator-owned authored synthetic fixture'], 'expiresAt': None}}]})
    h.copy_authorities([context.paths.sources for context in world.native_contexts] + [registry])
    h.originals = {str(path): fingerprint(path) for context in world.native_contexts
                   for path in (context.paths.ingestion, context.paths.extraction, context.paths.relation, context.metering)}
    save(h.root / 'preservation-before.json', h.originals)
    h.jar.denied = (world.root,)
    package_root, request, legacy_ids, policy = synthetic_legacy(h, 'bootstrap-legacy')
    manifest = hs.manifest_doc(world, 'cumulative-synthetic-native', {})
    manifest['policyVersion'] = 'zoop-public-projection-policy-3'
    catalogue = [{'id': 'SYNTH:CUMULATIVE', 'name': '합성기업', 'aliases': []}, {'id': 'SYNTHETIC:ACME', 'name': 'Synthetic Acme', 'aliases': []}]
    h.report['syntheticLoopbackRequests'] = world.fixture_requests
    return manifest, {'issue:context-0', 'issue:context-1'}, package_root, request, legacy_ids, catalogue, policy


def seed_catalogue(h, catalogue):
    existing = h.db.rows('SELECT id,name,aliases FROM companies ORDER BY id')
    by_id = {row['id']: row for row in existing}
    additions = []
    for row in catalogue:
        if row['id'] in by_id:
            h.record('catalogue-existing-' + row['id'], by_id[row['id']] == row)
        else:
            additions.append(row)
    if additions:
        encoded = SQL(base.json_bytes(additions).decode())
        h.db.run('INSERT INTO companies(id,name,aliases,name_key,search_text) SELECT id,name,ARRAY(SELECT jsonb_array_elements_text(aliases)),name,name '
                 f'FROM jsonb_to_recordset({encoded}::jsonb) AS c(id text,name text,aliases jsonb)')
    observed = h.db.rows('SELECT id,name,aliases FROM companies ORDER BY id')
    if h.args.mode == 'actual':
        h.record('owned-catalogue33-exact', observed == sorted(catalogue, key=lambda row: row['id']))
    h.catalogue = h.db.rows('SELECT * FROM companies ORDER BY id')
    save(h.root / 'catalogue-before.json', h.catalogue)


def scenario(h):
    h.report['phase'] = 'frozen-inputs'
    inputs = actual_inputs(h) if h.args.mode == 'actual' else synthetic_inputs(h)
    manifest, native_ids, package_root, request, legacy_ids, catalogue, policy = inputs
    h.report['phase'] = 'database-bootstrap'
    code, _ = h.operator('owned-schema-bootstrap')
    h.record('owned-schema-bootstrap', code == 0)
    h.jar.migrated = True
    seed_catalogue(h, catalogue)
    if h.args.bootstrap == 'fixture':
        with activation.Web(h.jar, {'ZOOP_GRAPH_SNAPSHOT_SOURCE': 'fixture', 'ZOOP_GRAPH_AUTO_ACTIVATION_ENABLED': 'false'},
                            ready='Graph fixture fixture-2026-10-08 '):
            pass
    initial_pointer = h.db.scalar('SELECT id FROM graph_versions WHERE active')
    h.report['initialActiveVersionId'] = initial_pointer
    h.report['phase'] = 'http-native-and-legacy-normal-imports'
    native_source = h.import_native(manifest, native_ids)
    legacy_source = h.import_legacy('normal-legacy-import', package_root, request, legacy_ids)
    h.record('both-normal-imports-preserve-active', h.db.scalar('SELECT id FROM graph_versions WHERE active') == initial_pointer)
    h.record('native-only-and-legacy-only-identities', bool(native_ids) and bool(legacy_ids) and not native_ids & legacy_ids)
    if policy:
        by_id = {item['issueId']: item for item in legacy_source.snapshot['issues']}
        for item in policy['issues']:
            issue = by_id[item['issueId']]
            for field, public in (('geography', 'geography'), ('eventTime', 'eventTime'), ('period', 'period')):
                if item[field]['mode'] == 'unknown':
                    h.record('explicit-unknown-' + field + '-' + item['issueId'], issue[public] is None)
    h.report['phase'] = 'atomic-bootstrap-composition'
    bootstrap_request = h.compose_request([native_source, legacy_source])
    publication = h.compose('bootstrap-compose', [native_source, legacy_source], request=bootstrap_request)
    h.record('bootstrap-exactly-two-leaves', publication.result['counts']['sources'] == 2
             and publication.result['counts']['issues'] == len(native_ids | legacy_ids))
    h.report['phase'] = 'package3-java-only-install'
    h.seal_install('bootstrap', publication)
    h.report['phase'] = 'manual-admin-and-public-http'
    with h.web() as web:
        h.activate(web, publication, label='bootstrap-manual-activate')
        h.public(web, publication, native_ids | legacy_ids, 'bootstrap')
        h.native_rights(web, publication, native_source, legacy_ids)
        h.compose('stale-bootstrap-compose', [native_source, legacy_source], request=bootstrap_request, failure='active_conflict')
        h.overlays(web, publication, legacy_source, native_ids)
    with h.web(producer=True) as web:
        h.activate(web, native_source, status=409, label='raw-source-replacement-refused')
    active_publication = publication
    if h.args.mode == 'synthetic' or h.args.legacy_count == 17:
        h.report['phase'] = 'fresh-original-source-carryforward'
        if h.args.mode == 'synthetic':
            fresh_package, fresh_request, incoming_ids, new_policy = synthetic_legacy(h, 'later-legacy', later=True)
        else:
            inputs = h.actual_prepared['exporterInputArguments']
            fresh_package = h.root / 'later-legacy22-package'
            fresh_request, _ = package.prepare(Path(inputs['source']), fresh_package, load(inputs['bindings']),
                load(inputs['company-bindings']), 'cumulative-local-proof', Path(inputs['metadata-policy']))
            incoming_ids = set(h.actual_selection['allLegacyIssueIdsUnderNewMetadataPolicy'])
            new_policy = load(inputs['metadata-policy'])
            h.record('actual-five-genuinely-additional-records', incoming_ids - legacy_ids == set(h.actual_selection['additionalIssueIds']))
        fresh = h.import_legacy('fresh-normal-import', fresh_package, fresh_request, incoming_ids)
        fresh_ids = incoming_ids - legacy_ids
        if h.args.mode == 'actual':
            h.retain_published_headlines(publication, legacy_source, fresh)
        carried = h.compose('carryforward-compose', [fresh], publication)
        h.record('three-flat-original-leaves', carried.result['counts']['sources'] == 3)
        by_id = {issue['issueId']: issue for issue in carried.snapshot['issues']}
        for item in new_policy['issues']:
            if item['issueId'] not in fresh_ids:
                continue
            for field in ('geography', 'eventTime', 'period'):
                if item[field]['mode'] == 'unknown':
                    h.record('carried-new-unknown-' + field + '-' + item['issueId'], by_id[item['issueId']][field] is None)
        h.seal_install('carryforward', carried)
        with h.web() as web:
            h.activate(web, carried, label='carryforward-manual-activate')
            h.public(web, carried, native_ids | legacy_ids | fresh_ids, 'carryforward')
            h.activate(web, publication, status=422, label='old-publication-forward-refused')
            h.activate(web, publication, mode='rollback', label='explicit-historical-rollback')
            h.public(web, publication, native_ids | legacy_ids, 'rollback')
            h.activate(web, carried, mode='rollback', label='explicit-restore-carryforward')
            h.overlays(web, carried, legacy_source, native_ids, historical=(publication,))
        active_publication = carried
        h.report['carryforward'] = {'exercised': True, 'mode': h.args.mode, 'graphVersionId': carried.version,
            'newIssueIds': sorted(fresh_ids), 'retainedIssueIds': sorted(native_ids | legacy_ids),
            'issueRecords': len(native_ids | legacy_ids | fresh_ids), 'sourceCount': 3}
    else:
        h.report['carryforward'] = {'exercised': False, 'mode': 'actual', 'reason': 'Started from the complete reviewed legacy22 selection.'}
    h.record('catalogue-preserved-exactly', h.db.rows('SELECT * FROM companies ORDER BY id') == h.catalogue)
    h.report['bootstrapPublication'] = {'graphVersionId': publication.version, 'issueRecords': len(native_ids | legacy_ids), 'sourceCount': 2}
    h.report['publication'] = {'graphVersionId': active_publication.version,
        'issueRecords': active_publication.result['counts']['issues'],
        'sourceCount': active_publication.result['counts']['sources'], 'certifiedIndependentEvents': None}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--jar', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new private output directory; every failed attempt is retained')
    parser.add_argument('--java')
    parser.add_argument('--mode', choices=('synthetic', 'actual'), default='synthetic')
    parser.add_argument('--bootstrap', choices=('null', 'fixture'), default='null')
    parser.add_argument('--legacy-count', type=int, choices=(17, 22), default=17,
                        help='actual bootstrap selection: 17 then carry forward22 (default), or bootstrap22')
    parser.add_argument('--actual-native-root', type=Path, help='required in actual mode: native input directory')
    parser.add_argument('--actual-legacy-root', type=Path, help='required in actual mode: legacy input directory')
    parser.add_argument('--actual-selection-sha256', help='required in actual mode: NEXT_IMPORT_INPUTS.json SHA256')
    parser.add_argument('--actual-native-manifest-sha256', help='required in actual mode: FILE_SHA_MANIFEST.json SHA256')
    parser.add_argument('--actual-prepared-sha256', help='required in actual mode: LEGACY3_INPUT_HANDOFF.json SHA256')
    parser.add_argument('--overlap-review', type=Path)
    parser.add_argument('--overlap-review-sha256')
    parser.add_argument('--service-python', type=Path, default=REPO / 'ai/service/.venv/bin/python')
    parser.add_argument('--worker-cli', type=Path, default=REPO / 'ai/worker/.venv/bin/zoop-ai')
    args = parser.parse_args()
    for key in ('jar', 'output'):
        setattr(args, key, getattr(args, key).resolve())
    for key in ('service_python', 'worker_cli'):
        setattr(args, key, getattr(args, key).absolute())
    if args.output.exists():
        parser.error('--output must be absent')
    if args.mode == 'actual':
        required = ('actual_native_root', 'actual_legacy_root', 'actual_selection_sha256',
                    'actual_native_manifest_sha256', 'actual_prepared_sha256', 'overlap_review', 'overlap_review_sha256')
        missing = ['--' + key.replace('_', '-') for key in required if not getattr(args, key)]
        if missing:
            parser.error('actual mode requires ' + ', '.join(missing))
        for key in ('actual_native_root', 'actual_legacy_root'):
            source = getattr(args, key).resolve()
            setattr(args, key, source)
            if args.output == source or source in args.output.parents or args.output in source.parents:
                parser.error('output must not overlap frozen input roots')
    clean = activation.isolated_environment(dict(os.environ))
    os.environ.clear()
    os.environ.update({**clean, 'PYTHONDONTWRITEBYTECODE': '1'})
    os.umask(0o077)
    args.java = delivery.local.find_java(args.java)
    args.output.mkdir(mode=0o700)
    report = {'status': 'failed', 'phase': 'preflight', 'mode': args.mode, 'steps': [], 'commands': [],
              'externalProviderCalls': 0, 'externalModelCalls': 0, 'cleanup': {}, 'runtimeProof': 'local only'}
    owned = 'zoop-cumulative-' + secrets.token_hex(8)
    container_created = network_created = False
    h = None
    password = None
    def observed_docker(label, *arguments, **kwargs):
        done = delivery.local.docker(*arguments, **kwargs)
        for stream in ('stdout', 'stderr'):
            text = getattr(done, stream).replace(password or '\0', '[redacted]')
            (args.output / (label + '.' + stream)).write_text(text)
        report['commands'].append({'step': label, 'exitCode': done.returncode})
        return done
    def stop(signum, frame):
        raise InterruptedError('owned smoke interrupted')
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, stop)
    try:
        for path in (args.jar, args.service_python, args.worker_cli, Path('/usr/bin/sandbox-exec')):
            check(path.is_file(), 'required cached dependency missing: ' + str(path))
        report['jarSha256'] = sha(args.jar)
        endpoint = delivery.local.docker('context', 'inspect', '--format', '{{.Endpoints.docker.Host}}')
        check(endpoint.returncode == 0 and endpoint.stdout.strip().startswith('unix://'), 'local Docker socket required')
        delivery.local.preflight_docker(delivery.local.DEFAULT_IMAGE)
        image = delivery.local.docker('image', 'inspect', delivery.local.DEFAULT_IMAGE, '--format', '{{.Id}}')
        check(image.returncode == 0, 'cached PostgreSQL image required')
        report['postgresImageId'] = image.stdout.strip()
        network = observed_docker('network-create', 'network', 'create', '--driver', 'bridge', '--label', LABEL + '=1', owned)
        check(network.returncode == 0, 'owned network creation')
        network_created = True
        password = secrets.token_urlsafe(32)
        created = observed_docker('database-create', 'run', '-d', '--pull', 'never', '--name', owned, '--label', LABEL + '=1', '--network', owned,
            '-e', 'POSTGRES_DB=' + delivery.local.DB_NAME, '-e', 'POSTGRES_USER=' + delivery.local.DB_USER,
            '-e', 'POSTGRES_PASSWORD', '-p', '127.0.0.1::5432', delivery.local.DEFAULT_IMAGE, env={**os.environ, 'POSTGRES_PASSWORD': password})
        check(created.returncode == 0, 'owned PostgreSQL startup')
        container_created = True
        mapped = observed_docker('database-port', 'port', owned, '5432/tcp')
        mapping = mapped.stdout.strip()
        check(mapped.returncode == 0 and mapping.startswith('127.0.0.1:') and '\n' not in mapping, 'owned database loopback mapping')
        port = int(mapping.rsplit(':', 1)[1])
        delivery.local.wait_database(owned, port)
        os.environ.update(DB_URL=f'jdbc:postgresql://127.0.0.1:{port}/{delivery.local.DB_NAME}', DB_USERNAME=delivery.local.DB_USER, DB_PASSWORD=password)
        db = Database(os.environ['DB_URL'], delivery.local.DB_USER, password, delivery.local.DB_NAME, owned, None)
        check(not db.tables_exist(), 'owned database must be empty')
        h = Harness(args, args.output, db, report)
        scenario(h)
        report.update(status='passed', phase='complete')
    except (Exception, KeyboardInterrupt) as error:
        report['failure'] = {'type': type(error).__name__, 'phase': report['phase'],
                             'message': str(error)[:500].replace(os.environ.get('DB_PASSWORD') or '\0', '[redacted]')}
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        if h:
            for service in h.services:
                service.close()
            for runner in h.runs:
                for process in runner.processes:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=30)
            for index, web in enumerate(activation.Web.instances):
                if web.process.poll() is None:
                    web.__exit__()
                (args.output / f'web-{index:02d}.log').write_text(''.join(web.lines).replace(h.db.password, '[redacted]'))
            report['cleanup']['processes'] = (
                all(service.process is None or service.process.poll() is not None for service in h.services)
                and all(process.poll() is not None for runner in h.runs for process in runner.processes)
                and all(web.process.poll() is not None for web in activation.Web.instances))
            if hasattr(h, 'originals'):
                try:
                    after = {path: fingerprint(Path(path)) for path in h.originals}
                    save(args.output / 'preservation-after.json', after)
                    report['preservationUnchanged'] = after == h.originals
                    if not report['preservationUnchanged']:
                        report['status'] = 'failed'
                except Exception as error:
                    report['preservationError'] = str(error)[:300]
                    report['status'] = 'failed'
        if container_created:
            observed_docker('database-logs-before-cleanup', 'logs', '--timestamps', owned)
            observed_docker('database-state-before-cleanup', 'inspect', '--format',
                '{"State":{{json .State}},"Ports":{{json .NetworkSettings.Ports}},"RequestedPortBindings":{{json .HostConfig.PortBindings}}}', owned)
            dumped = delivery.local.docker('exec', owned, 'pg_dump', '-U', delivery.local.DB_USER, '-d', delivery.local.DB_NAME, '--no-owner', '--no-acl')
            (args.output / 'database-private.sql').write_text(dumped.stdout)
            (args.output / 'database-dump.stderr').write_text(dumped.stderr)
            report['privateSqlRetained'] = dumped.returncode == 0
            observed_docker('database-stop', 'stop', '--time', '10', owned)
            removed = observed_docker('database-remove', 'rm', '-v', owned)
            report['cleanup']['container'] = removed.returncode == 0
        if network_created:
            report['cleanup']['network'] = observed_docker('network-remove', 'network', 'rm', owned).returncode == 0
        if not all(report['cleanup'].values()) or (container_created and not report['privateSqlRetained']):
            report['status'] = 'failed'
        save(args.output / 'report.json', report)
        print(json.dumps({'status': report['status'], 'report': str(args.output / 'report.json'), 'failure': report.get('failure')}))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
