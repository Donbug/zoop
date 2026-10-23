#!/usr/bin/env python3
"""Offline, credential-free access to the recorded Zoop briefing corpus."""
from __future__ import annotations
import argparse,collections,gzip,hashlib,json,re,sys,tarfile
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]
DEFAULT=ROOT/'data/briefing-archive-2026-10-23'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def safe_path(name):
 p=PurePosixPath(name)
 if not name or p.is_absolute() or '..' in p.parts or '\\' in name:raise ValueError('Unsafe logical path')
 return p
class Archive:
 def __init__(self,root):
  self.root=root.resolve();self.manifest=json.loads((self.root/'manifest.json').read_bytes())
  if self.manifest['schemaVersion']!='zoop-collected-data-archive-v1':raise ValueError('Unsupported archive format')
  catalogs={}
  for name in ['files.jsonl','excluded.jsonl','redactions.jsonl']:
   item=self.manifest[name];data=(self.root/str(safe_path(item.get('path',name)))).read_bytes()
   if len(data)!=item['bytes'] or sha(data)!=item['sha256']:raise ValueError('Catalog checksum mismatch: '+name)
   catalogs[name]=gzip.decompress(data) if item.get('encoding')=='gzip' else data
  self.files=[json.loads(line) for line in catalogs['files.jsonl'].decode('utf-8').splitlines()]
  seen=set()
  for row in self.files:
   safe_path(row['path'])
   if not re.fullmatch('[0-9a-f]{64}',row['sha256']):raise ValueError('Invalid object digest')
   if row['path'] in seen:raise ValueError('Duplicate logical path')
   seen.add(row['path'])
  if len(self.files)!=self.manifest['files']:raise ValueError('Catalog count mismatch')
 def objects(self):
  seen=set()
  for shard in self.manifest['shards']:
   name=str(safe_path(shard['path']));path=self.root/name
   data=path.read_bytes()
   if len(data)!=shard['bytes'] or sha(data)!=shard['sha256']:raise ValueError('Shard checksum mismatch: '+name)
   with tarfile.open(path,'r:gz') as archive:
    count=0
    for item in archive:
     if not item.isfile() or not re.fullmatch(r'objects/[0-9a-f]{64}',item.name):raise ValueError('Unexpected archive member')
     digest=item.name.split('/')[1]
     if digest in seen:raise ValueError('Duplicate object')
     seen.add(digest);stream=archive.extractfile(item)
     if stream is None:raise ValueError('Missing object')
     raw=stream.read()
     if len(raw)!=item.size or sha(raw)!=digest:raise ValueError('Object checksum mismatch')
     count+=1;yield digest,raw
    if count!=shard['objects']:raise ValueError('Shard object count mismatch')
  if len(seen)!=self.manifest['uniqueObjects']:raise ValueError('Unique object count mismatch')
 def selected(self,group=None,prefix=None):
  return [r for r in self.files if (not group or r['group']==group) and (not prefix or r['path'].startswith(prefix))]
 def verify(self):
  expected=collections.defaultdict(set)
  for row in self.files:expected[row['sha256']].add(row['bytes'])
  count=0
  for digest,raw in self.objects():
   if digest not in expected or expected.pop(digest)!={len(raw)}:raise ValueError('Catalog/object mismatch')
   count+=1
  if expected:raise ValueError('Missing referenced objects')
  return {'status':'VERIFIED','files':len(self.files),'objects':count,'newAiCalls':0,'newProviderCalls':0}
 def extract(self,output,group=None,prefix=None):
  rows=self.selected(group,prefix)
  if not rows:raise ValueError('No matching files')
  output=output.resolve();output.mkdir(parents=True,exist_ok=True)
  by_digest=collections.defaultdict(list)
  for row in rows:by_digest[row['sha256']].append(row)
  count=0
  for digest,raw in self.objects():
   for row in by_digest.pop(digest,[]):
    if len(raw)!=row['bytes']:raise ValueError('Logical file size mismatch')
    path=output.joinpath(*safe_path(row['path']).parts)
    # Resolve each target as well as parents: refuse pre-existing symlinks escaping the destination.
    if not path.resolve().is_relative_to(output):raise ValueError('Output path escapes destination')
    if path.exists():
     if not path.is_file() or path.is_symlink() or sha(path.read_bytes())!=digest:raise ValueError('Refusing to overwrite different file: '+row['path'])
    else:
     path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw);path.chmod(0o600)
    count+=1
  if by_digest:raise ValueError('Missing selected objects')
  return {'status':'EXTRACTED','files':count,'output':str(output),'newAiCalls':0,'newProviderCalls':0}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',type=Path,default=DEFAULT)
 sub=p.add_subparsers(dest='command',required=True)
 sub.add_parser('verify');sub.add_parser('catalog')
 s=sub.add_parser('list');s.add_argument('--group');s.add_argument('--prefix')
 s=sub.add_parser('extract');s.add_argument('--group');s.add_argument('--prefix');s.add_argument('--output',type=Path,required=True)
 a=p.parse_args();archive=Archive(a.archive)
 if a.command=='catalog':
  print('group\tfiles\tMiB')
  for group,stats in archive.manifest['groups'].items():print(f"{group}\t{stats['files']}\t{stats['logicalBytes']/1048576:.2f}")
 elif a.command=='list':
  for row in archive.selected(a.group,a.prefix):print(json.dumps(row,ensure_ascii=False))
 elif a.command=='verify':print(json.dumps(archive.verify(),ensure_ascii=False))
 else:print(json.dumps(archive.extract(a.output,a.group,a.prefix),ensure_ascii=False))
if __name__=='__main__':
 try:main()
 except (ValueError,OSError,tarfile.TarError) as error:print('Archive error: '+str(error),file=sys.stderr);raise SystemExit(1)
