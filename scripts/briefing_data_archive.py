#!/usr/bin/env python3
"""Offline, credential-free access to the recorded Zoop briefing corpus."""
from __future__ import annotations
import argparse,collections,gzip,hashlib,json,os,re,secrets,stat,sys,tarfile
from contextlib import contextmanager
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]
DEFAULT=ROOT/'data/briefing-archive-2026-10-23'
DIR_FD_FUNCTIONS=(os.open,os.mkdir,os.stat,os.link,os.unlink)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def safe_path(name):
 if not isinstance(name,str) or '\x00' in name:raise ValueError('Unsafe logical path')
 p=PurePosixPath(name)
 if not p.parts or p.is_absolute() or '..' in p.parts or '\\' in name or str(p)!=name:raise ValueError('Unsafe logical path')
 return p

def require_atomic_extraction():
 # Fail closed rather than silently reverting to path-based writes on platforms
 # without descriptor-relative, no-follow filesystem operations (use WSL there).
 if (os.name!='posix' or not all(hasattr(os,n) for n in ('O_NOFOLLOW','O_DIRECTORY','O_NONBLOCK'))
     or not all(f in os.supports_dir_fd for f in DIR_FD_FUNCTIONS)):
  raise OSError('Atomic extraction requires POSIX dir_fd/O_NOFOLLOW and hard links; use Linux, macOS or WSL')

@contextmanager
def directory(parts,base=None):
 """Keep parent handles open: a swapped path cannot redirect a later write."""
 fds=[];bindings=[]
 try:
  fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY) if base is None else os.dup(base)
  fds.append(fd)
  for part in parts:
   try:os.mkdir(part,mode=0o700,dir_fd=fd)
   except FileExistsError:pass
   child=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
   bindings.append((fd,part,os.fstat(child)));fds.append(child);fd=child
  def unchanged():
   for parent,name,opened in bindings:
    current=os.stat(name,dir_fd=parent,follow_symlinks=False)
    if not stat.S_ISDIR(current.st_mode) or (current.st_dev,current.st_ino)!=(opened.st_dev,opened.st_ino):
     raise ValueError('Output directory changed during extraction')
  yield fd,unchanged
 finally:
  for fd in reversed(fds):os.close(fd)

def existing_file(parent,name,digest,size):
 try:fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
 except FileNotFoundError:return False
 except OSError as error:raise ValueError('Refusing unsafe existing target: '+name) from error
 try:
  opened=os.fstat(fd)
  if not stat.S_ISREG(opened.st_mode) or opened.st_size!=size:
   raise ValueError('Refusing to overwrite different file: '+name)
  hashed=hashlib.sha256()
  while chunk:=os.read(fd,1024*1024):hashed.update(chunk)
  current=os.stat(name,dir_fd=parent,follow_symlinks=False)
  if (not stat.S_ISREG(current.st_mode) or (current.st_dev,current.st_ino)!=(opened.st_dev,opened.st_ino)
      or hashed.hexdigest()!=digest):raise ValueError('Refusing to overwrite different file: '+name)
  return True
 finally:os.close(fd)

def publish_file(parent,name,raw,digest,check):
 check()
 if existing_file(parent,name,digest,len(raw)):
  check();return
 temporary='.zoop-archive-'+secrets.token_hex(16)
 fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
 try:
  try:
   remaining=memoryview(raw)
   while remaining:
    written=os.write(fd,remaining)
    if written<=0:raise OSError('Incomplete staging write')
    remaining=remaining[written:]
   os.fsync(fd)
  finally:os.close(fd)
  check()
  try:
   # link is an atomic no-clobber commit. rename/replace would overwrite a
   # competing file. Both names use the same anchored directory/filesystem.
   os.link(temporary,name,src_dir_fd=parent,dst_dir_fd=parent,follow_symlinks=False)
  except FileExistsError:
   if not existing_file(parent,name,digest,len(raw)):
    raise ValueError('Output target disappeared during extraction')
  check()
 finally:os.unlink(temporary,dir_fd=parent)
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
  require_atomic_extraction();output=output.resolve()
  by_digest=collections.defaultdict(list)
  for row in rows:by_digest[row['sha256']].append(row)
  count=0
  with directory(output.parts[1:]) as (root,root_unchanged):
   for digest,raw in self.objects():
    for row in by_digest.pop(digest,[]):
     if len(raw)!=row['bytes']:raise ValueError('Logical file size mismatch')
     parts=safe_path(row['path']).parts
     with directory(parts[:-1],root) as (parent,parent_unchanged):
      def check():root_unchanged();parent_unchanged()
      publish_file(parent,parts[-1],raw,digest,check)
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
