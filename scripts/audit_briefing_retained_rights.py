#!/usr/bin/env python3
"""Trace private collector defaults without declaring publisher permission or changing a grant.

All output is private review material. A matching local default means no publisher
decision was recorded; it is neither a publisher refusal nor permission to publish.
"""
import argparse
import ast
from collections import Counter
import json
from pathlib import Path

from prepare_briefing_read_bindings import canonical, sha, unique
from render_briefing_staging_sql import verify_bundle


def collector_default():
    path=Path(__file__).resolve().parents[1]/'ai/pipeline/src/zoop_ai_pipeline/private_intake.py'
    raw=path.read_bytes()
    for node in ast.parse(raw).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='USE' for t in node.targets):
            return ast.literal_eval(node.value),dict(path=str(path.relative_to(Path(__file__).resolve().parents[1])),
                sha256=sha(raw),line=node.lineno)
    raise ValueError('collector default declaration missing')


def audit(bundle,units_file):
    manifest=verify_bundle(bundle)
    pins=manifest['sourceFiles']
    def pinned(path):
        raw=path.read_bytes()
        if pins.get(str(path))!=sha(raw):raise ValueError('retained source is not pinned or changed')
        return json.loads(raw)
    units=unique(pinned(units_file),lambda x:(x['observation']['documentId'],x['observation']['documentVersion']))
    tables={t:[json.loads(s) for s in (bundle/'tables'/f'{t}.jsonl').read_text().splitlines()]
        for t in ('articles','article_versions','artifacts')}
    articles=unique(tables['articles'],lambda x:x['id']);artifacts=unique(tables['artifacts'],lambda x:x['id'])
    versions=unique(tables['article_versions'],lambda x:(x['article_id'],x['version']))
    defaults,code=collector_default();documents=[]
    for key,version in sorted(versions.items()):
        unit=units[key];path=Path(unit['index']['recordPath']);record=pinned(path)
        if sha(path.read_bytes())!=unit['rawRecordSha256'] or unit['rawRecordSha256']!=unit['index']['recordSha256']:
            raise ValueError('retained record digest mismatch')
        plan_path=Path(unit['index']['stateDir'])/'PLAN.json';plan=json.loads(plan_path.read_bytes())
        if sha(canonical(plan))!=record['planDigest'] or plan['config']['planId']!=unit['index']['planId']:
            raise ValueError('retained plan mismatch')
        provider=articles[key[0]]['provider'];body=artifacts[version['text_artifact_id']]['sha256']
        if (record['source']!=provider or unit['index']['sourceId']!=provider
                or sha(record['prepared']['text'].encode())!=body or record['textSha256']!=body or unit['bodySha256']!=body):
            raise ValueError('retained document identity mismatch')
        recognized=(record['schemaVersion'] in ('zoop-private-news-record-1','zoop-private-news-record-2','zoop-private-news-record-3')
            and record['provenance']=='private-public-web' and plan['provenance']==record['provenance']
            and plan['schemaVersion']=='zoop-private-news-plan-1'
            and all(type(record.get(k)) is type(v) and record.get(k)==v and type(plan.get(k)) is type(v) and plan.get(k)==v
                for k,v in defaults.items()))
        documents.append(dict(documentId=key[0],documentVersion=key[1],sourceId=provider,bodySha256=body,
            recordSha256=unit['rawRecordSha256'],planSha256=record['planDigest'],
            observedUse={k:record.get(k) for k in defaults},
            restrictionOrigin='collector_private_default' if recognized else 'unresolved_metadata',
            publisherDecision='not_recorded' if recognized else 'not_established_by_this_audit',
            publicationAuthorized=False,newModelCallsAuthorized=False))
    return dict(schemaVersion='briefing-retained-rights-audit-v1',collectorDefaultDefinition=code,
        sourceBundleManifestSha256=sha((bundle/'manifest.json').read_bytes()),documents=documents,
        counts=dict(documents=len(documents),bySource=dict(Counter(d['sourceId'] for d in documents)),
            byOrigin=dict(Counter(d['restrictionOrigin'] for d in documents))),
        conclusion='Collector defaults are not publisher decisions; current use authority must be checked separately.',
        sourceRecordsChanged=False,grantsChanged=False,publicationReady=False,newAiCalls=0)


def write_audit(bundle,units_file,output):
    if output.exists():raise ValueError('output exists; preserve prior audit')
    result=audit(bundle,units_file)
    with output.open('xb') as f:output.chmod(0o600);f.write(canonical(result))
    return result['counts']


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('bundle','units-file','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();print(json.dumps(write_audit(a.bundle,a.units_file,a.output)))


if __name__=='__main__':main()
