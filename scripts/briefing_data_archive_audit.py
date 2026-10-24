#!/usr/bin/env python3
"""Reproduce bounded credential and DB-column checks without executing any payload.

The public rules do not reproduce the historical private known-value list and
cannot certify absence of arbitrary secrets, personal data or licensing issues.
"""
import argparse
import collections
import gzip
import io
import json
from pathlib import Path
import re
import sys
import zipfile

from briefing_data_archive import Archive, DEFAULT, ROOT, sha

POLICY = DEFAULT/'audit-policy-v1.json'
VERSION = 'zoop-archive-recheck-v1'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


class Inspector:
    def __init__(self, policy):
        self.policy = policy
        self.rules = [(r['id'], re.compile(r['pattern'], r.get('flags', 0))) for r in policy['textRules']]
        self.key = re.compile(policy['credentialFieldPattern'], re.I)
        self.findings = collections.Counter()
        self.zip_objects = 0
        self.zip_members = 0
        self.gzip_objects = 0
        self.reviewed_fields = collections.Counter()

    def safe_value(self, value):
        if value is None: return True
        if isinstance(value, str): return not value or value in self.policy['redactionMarkers']
        return not value

    def reviewed_field(self, digest, pointer, parent, child):
        for item in self.policy.get('reviewedFieldExceptions', []):
            if (item['objectSha256'] == digest and item['pointer'] == pointer
                    and isinstance(child, str) and set(parent) == set(item['requiredSiblingKeys'])
                    and {k: type(v).__name__ for k, v in parent.items()} == item['requiredValueTypes']):
                self.reviewed_fields[(digest, pointer)] += 1
                return True
        return False

    def structured(self, value, digest, pointer=''):
        if isinstance(value, dict):
            for key, child in value.items():
                location = pointer+'/'+key.replace('~', '~0').replace('/', '~1')
                if self.key.fullmatch(key) and isinstance(child, (str, dict, list)) and not self.safe_value(child):
                    if not self.reviewed_field(digest, location, value, child):
                        self.findings[(digest, 'nonempty-credential-field')] += 1
                self.structured(child, digest, location)
        elif isinstance(value, list):
            for index, child in enumerate(value): self.structured(child, digest, pointer+'/'+str(index))

    def text(self, text, digest):
        for name, pattern in self.rules:
            for match in pattern.finditer(text):
                # Assignment rules have a credential-value capture. Redaction
                # markers are deliberately retained, never classified as keys.
                value = match.groupdict().get('value')
                if value is not None and self.safe_value(value): continue
                self.findings[(digest, name)] += 1

    def inspect(self, raw, digest, depth=0):
        limit = self.policy['maximumExpandedBytesPerObject']
        if depth > self.policy['maximumArchiveDepth'] or len(raw) > limit:
            raise ValueError('Audit expansion limit exceeded')
        if raw.startswith(b'PK\x03\x04'):
            self.zip_objects += 1
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if sum(i.file_size for i in archive.infolist()) > limit:
                    raise ValueError('ZIP expansion limit exceeded')
                self.text(archive.comment.decode('utf-8', 'surrogateescape'), digest)
                for item in archive.infolist():
                    self.zip_members += 1
                    self.text(item.filename, digest)
                    self.inspect(archive.read(item), digest, depth+1)
            return
        if raw.startswith(b'\x1f\x8b'):
            self.gzip_objects += 1
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as archive:
                expanded = archive.read(limit+1)
            self.inspect(expanded, digest, depth+1)
            return
        text = raw.decode('utf-16', 'replace') if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else raw.decode('utf-8', 'surrogateescape')
        self.text(text, digest)
        # Parse a complete JSON object/array, otherwise inspect valid JSONL
        # records individually. Partial recorded responses remain text scans.
        try:
            value = json.loads(text)
        except (ValueError, RecursionError):
            for line in text.splitlines():
                if not line.lstrip().startswith(('{', '[')): continue
                try: value = json.loads(line)
                except (ValueError, RecursionError): continue
                self.structured(value, digest)
        else: self.structured(value, digest)


def check_columns(table, raw, policy):
    if table not in policy['postgresColumns']:
        raise ValueError('Unapproved PostgreSQL table: '+table)
    allowed = set(policy['postgresColumns'][table])
    count = 0
    administrative = collections.Counter()
    for line in raw.splitlines():
        value = json.loads(line)
        if not isinstance(value, dict) or not set(value) <= allowed:
            raise ValueError('Unapproved PostgreSQL columns: '+table)
        # The fixed snapshot includes system/fixture actors. Public fixtures
        # may use reserved example/test domains; arbitrary personal email is
        # not admitted as an administrative snapshot by this policy.
        email = value.get('admin_email_snapshot')
        if email is not None:
            permitted = email in ('system', *policy['redactionMarkers']) or re.fullmatch(policy['syntheticEmailPattern'], email)
            if not permitted: raise ValueError('Administrative email needs review: '+table)
            administrative['system' if email=='system' else 'redacted' if email in policy['redactionMarkers'] else 'reserved_fixture_email'] += 1
        count += 1
    return count, administrative


def audit(root, policy_path):
    code_paths = [Path(__file__), ROOT/'scripts/briefing_data_archive.py', ROOT/'scripts/briefing_archive_redaction.py']
    code_hashes = [sha(path.read_bytes()) for path in code_paths]
    policy_bytes = policy_path.read_bytes()
    policy = json.loads(policy_bytes)
    if policy['schemaVersion'] != VERSION: raise ValueError('Unsupported audit policy')
    archive = Archive(root)
    if sha((root/'manifest.json').read_bytes()) != policy['archiveManifestSha256']:
        raise ValueError('Policy belongs to a different archive manifest')
    bindings = [{'path': 'manifest.json', 'sha256': policy['archiveManifestSha256']}]
    for name in ('files.jsonl', 'excluded.jsonl', 'redactions.jsonl'):
        item = archive.manifest[name]
        bindings.append({'path': item.get('path', name), 'sha256': item['sha256'], 'bytes': item['bytes']})
    bindings.extend({k: s[k] for k in ('path', 'sha256', 'bytes')} for s in archive.manifest['shards'])
    expected = collections.defaultdict(set)
    db = collections.defaultdict(list)
    for row in archive.files:
        expected[row['sha256']].add(row['bytes'])
        if '/briefing-data-142/postgres/' in row['path'] and row['path'].endswith('.jsonl'):
            db[row['sha256']].append(Path(row['path']).stem)
    inspector = Inspector(policy)
    objects = 0; tables = collections.Counter(); administrative = collections.Counter()
    for digest, raw in archive.objects():
        if expected.pop(digest, None) != {len(raw)}: raise ValueError('Object/catalog mismatch')
        inspector.inspect(raw, digest)
        for table in db.get(digest, []):
            count, actors = check_columns(table, raw, policy)
            tables[table] += count; administrative.update(actors)
        objects += 1
    if expected: raise ValueError('Missing audited objects')
    required = {(item['objectSha256'], item['pointer']) for item in policy.get('reviewedFieldExceptions', [])}
    if set(inspector.reviewed_fields) != required or any(n != 1 for n in inspector.reviewed_fields.values()):
        raise ValueError('Reviewed metadata exceptions do not match the fixed snapshot')
    if code_hashes != [sha(path.read_bytes()) for path in code_paths] or policy_bytes != policy_path.read_bytes():
        raise ValueError('Audit code or policy changed while running; rerun with fixed files')
    findings = [{'objectSha256': d, 'rule': r, 'matches': n} for (d, r), n in sorted(inspector.findings.items())]
    return {'schemaVersion': VERSION, 'status': 'PASS' if not findings else 'REVIEW_REQUIRED',
            'policySha256': sha(policy_bytes), 'scannerSha256': code_hashes[0],
            'readerSha256': code_hashes[1],
            'publisherRedactorSha256': code_hashes[2],
            'distributionSha256': sha(canonical(bindings)), 'distributionFiles': bindings,
            'objectsInspected': objects, 'logicalFiles': len(archive.files),
            'zipObjectsInspected': inspector.zip_objects, 'zipMembersInspected': inspector.zip_members,
            'gzipObjectsInspected': inspector.gzip_objects,
            'postgresRowsByTable': dict(sorted(tables.items())), 'administrativeValues': dict(administrative),
            'findings': findings, 'newAiCalls': 0, 'newProviderCalls': 0,
            'reviewedMetadataFields': [{'objectSha256': d, 'pointer': p, 'matches': n}
                                       for (d, p), n in sorted(inspector.reviewed_fields.items())],
            'limits': policy['limits']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=DEFAULT)
    parser.add_argument('--policy', type=Path, default=POLICY)
    parser.add_argument('--check', type=Path, help='Require byte-independent JSON equality with a published recheck')
    args = parser.parse_args()
    result = audit(args.archive, args.policy)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result['status'] != 'PASS': raise ValueError('Credential findings require review; values are never printed')
    if args.check and result != json.loads(args.check.read_bytes()): raise ValueError('Recheck differs from published evidence')


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        print('Audit error: '+str(error), file=sys.stderr); raise SystemExit(1)
