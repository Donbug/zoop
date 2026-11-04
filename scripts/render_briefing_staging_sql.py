#!/usr/bin/env python3
"""Render an INSERT-only, transactional staging plan. Never connects to a DB.

The bundle stays private. A target operator must explicitly map the test
portfolio to its intended member, choose an unused preference revision and
place artifacts at a server-readable URI. This is NOT a publication script.
"""
import argparse
import copy
import hashlib
import json
import re
from pathlib import Path


TABLES = {
    'companies': ('id',),
    'artifacts': ('id',),
    'articles': ('id',),
    'article_versions': ('article_id', 'version'),
    'evidence': ('id',),
    'briefing_rounds': ('id',),
    'briefing_personal_pools': ('id',),
    'briefing_personal_preferences': ('id',),
    'briefing_personal_deliveries': ('id',),
}
HASH_COLUMNS = {
    'briefing_rounds': {'payload_sha256': 'published_payload'},
    'briefing_personal_pools': {'snapshot_sha256': 'snapshot'},
    'briefing_personal_deliveries': {'selection_sha256': 'selection_snapshot', 'result_sha256': 'result_snapshot'},
}


def literal(value):
    return "'" + value.replace("'", "''") + "'"


def verify_bundle(bundle):
    manifest = json.loads((bundle/'manifest.json').read_text())
    if manifest['publicationReady'] or not manifest['noAutomaticPublish']:
        raise ValueError('not an unpublished staging bundle')
    if not {f'tables/{table}.jsonl' for table in TABLES}.issubset(manifest['files']):
        raise ValueError('required table is outside the integrity manifest')
    for name, expected in manifest['files'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('unsafe bundle path')
        raw = (bundle/name).read_bytes()
        if len(raw) != expected['bytes'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
            raise ValueError('bundle integrity mismatch: '+name)
    return manifest


def render(bundle, member_id, preference_revision, artifact_uri_base):
    if not member_id.strip() or preference_revision < 1:
        raise ValueError('explicit target member and unused positive preference revision required')
    if not re.fullmatch(r'artifact-root:[a-z][a-z0-9_]{0,63}', artifact_uri_base):
        raise ValueError('server ArtifactFileStore directory URI required')
    manifest = verify_bundle(bundle)
    plan = ['-- Private data. Review the target, member mapping and artifact storage before any execution.',
            '-- INSERT only; never publishes, creates grants, activates graphs or changes existing records.',
            'BEGIN;', "SET LOCAL lock_timeout='5s';", "SET LOCAL standard_conforming_strings=on;",
            'DO $check$ BEGIN IF NOT EXISTS (SELECT 1 FROM members WHERE id='+literal(member_id)+
            " AND status='active') THEN RAISE EXCEPTION 'target member is missing or inactive'; END IF; END $check$;"]
    pref_id = 'prep-pref-'+hashlib.sha256((manifest['memberBindingRef']+'\n'+member_id+'\n'+str(preference_revision)).encode()).hexdigest()[:24]
    for table, keys in TABLES.items():
        records = [json.loads(s) for s in (bundle/'tables'/f'{table}.jsonl').read_text().splitlines()]
        for original in records:
            row = copy.deepcopy(original)
            if table == 'companies':
                # Keep an existing owner's catalog labels, aliases and profile.
                row.pop('name_key'); row.pop('search_text')
            if table == 'artifacts':
                row['storage_uri'] = artifact_uri_base.rstrip('/')+'/'+Path(row['storage_uri']).name
            if table in ('briefing_personal_preferences', 'briefing_personal_deliveries'):
                row['member_id'] = member_id
                if table.endswith('preferences'):
                    row.update(id=pref_id, revision=preference_revision)
                else:
                    row['preference_id'] = pref_id
                    row['id'] = 'prep-delivery-'+hashlib.sha256((original['id']+'\n'+pref_id).encode()).hexdigest()[:24]
            columns = list(row)
            if any(not c.replace('_','').isalnum() for c in columns):
                raise ValueError('unsafe column')
            source = 'jsonb_populate_record(NULL::'+table+','+literal(json.dumps(row,ensure_ascii=False))+ '::jsonb)'
            expressions = {c: 'x.'+c for c in columns}
            for column, value in HASH_COLUMNS.get(table,{}).items():
                expressions[column] = "encode(sha256(convert_to(x."+value+"::text,'UTF8')),'hex')"
            plan.append('INSERT INTO '+table+' ('+','.join(columns)+') SELECT '+','.join(expressions[c] for c in columns)+
                        ' FROM '+source+' AS x ON CONFLICT DO NOTHING;')
            # A repeat is a no-op only if the stored immutable values really match.
            compared = ['ticker','exchange_code'] if table == 'companies' else columns
            predicate = ' AND '.join('t.'+k+'=x.'+k for k in keys)
            predicate += ' AND ROW('+','.join('t.'+c for c in compared)+') IS NOT DISTINCT FROM ROW('+','.join(expressions[c] for c in compared)+')'
            plan.append('DO $check$ BEGIN IF NOT EXISTS (SELECT 1 FROM '+source+' AS x JOIN '+table+' AS t ON '+predicate+
                        ") THEN RAISE EXCEPTION 'staging collision in "+table+"; entire transaction must roll back'; END IF; END $check$;")
    plan += ['COMMIT;', '-- Still unpublished. Public API reads must remain unavailable until the independent publication gates pass.']
    return '\n'.join(plan)+'\n'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle',type=Path,required=True)
    p.add_argument('--member-id',required=True)
    p.add_argument('--preference-revision',type=int,required=True)
    p.add_argument('--artifact-uri-base',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    sql=render(a.bundle,a.member_id,a.preference_revision,a.artifact_uri_base)
    with a.output.open('x') as f:
        a.output.chmod(0o600); f.write(sql)
    print('Private staging SQL prepared; no database connection or publication performed.')


if __name__=='__main__':
    main()
