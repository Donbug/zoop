"""Prepare a new private multi-source registry revision; never edits the active file.

Additional sources must bring their own complete source and native-processing authority.
This command cannot infer permission from a URL or turn a disabled source on.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile

import briefing_news_intake as news


def prepare(current,output,revision,additional=None):
    current=news.private_path(current);output=Path(output).absolute()
    news.require(current!=output and not output.exists() and not output.is_symlink(),'new_registry_path')
    news.require(bool(revision.strip()),'registry_revision')
    value,_=news.load_registry({'newsSourceRegistry':str(current)})
    news.require(revision!=value['revision'],'new_registry_revision')
    value=copy.deepcopy(value);value.update(schemaVersion=news.EXPANDED_SCHEMA,revision=revision)
    if additional:
        data=json.loads(news.private_path(additional).read_bytes())
        news.require(isinstance(data,list),'additional_sources')
        value['sources'].extend(data)
    # Explicit new revision only. Grants, enabled flags and recipient scopes remain byte-equivalent JSON values.
    for s in value['sources']:
        s.update(maxListingPages=max(s['maxListingPages'],5),maxArticleAttempts=max(s['maxArticleAttempts'],60),maxDocuments=max(s['maxDocuments'],20))
    output.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    output=output.parent.resolve()/output.name
    news.require(not any((p/'.git').exists() for p in (output.parent,*output.parents)),'registry_outside_checkout')
    with tempfile.NamedTemporaryFile(dir=output.parent,delete=False) as stream:
        tmp=Path(stream.name);os.chmod(tmp,0o600);stream.write(news.b.canonical(value));stream.flush();os.fsync(stream.fileno())
    try:
        checked,sha=news.load_registry({'newsSourceRegistry':str(tmp)})
        news.require(all(not s['enabled'] or news.authorized(s) for s in checked['sources']),'enabled_source_authority_required')
        os.link(tmp,output)  # exclusive destination; no replacement of an existing registry
    finally:
        tmp.unlink()
    return {'schemaVersion':'briefing-news-registry-plan-v1','revision':revision,'sha256':sha,
            'sources':[{'sourceId':s['sourceId'],'enabled':s['enabled'],
                **{k:s[k] for k in ('maxListingPages','maxArticleAttempts','maxDocuments')}} for s in value['sources']],
            'activeRegistryChanged':False,'modelCalls':0}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--current',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--revision',required=True);p.add_argument('--additional-sources',type=Path)
    a=p.parse_args();print(json.dumps(prepare(a.current,a.output,a.revision,a.additional_sources),ensure_ascii=False))


if __name__=='__main__':main()
