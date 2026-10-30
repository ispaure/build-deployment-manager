"""Receipt-bound source transfer; reconciling a lost transport never re-extracts."""

IDENTITY = '''import hashlib,json,os,pathlib,sys
path=pathlib.Path(sys.argv[1]);token=sys.argv[2]
identity=dict(token=token,archive_sha256=sys.argv[3],uid=int(sys.argv[4]),gid=int(sys.argv[5]),runner_sha256=sys.argv[6])
if path.is_symlink() or path.resolve()!=path or path.name!=token:
 raise ValueError('Source staging workspace identity mismatch')
'''

STAGE = IDENTITY + '''import base64,fcntl,io,tarfile
request=json.loads(sys.stdin.buffer.read())
data=base64.b64decode(request['archive'],validate=True)
runner=base64.b64decode(request['runner'],validate=True)
if hashlib.sha256(runner).hexdigest()!=identity['runner_sha256']: raise ValueError('Guest helper digest mismatch')
if hashlib.sha256(data).hexdigest()!=identity['archive_sha256']: raise ValueError('Source transfer digest mismatch')
# Exclusive directory creation admits exactly one extractor, even if a previous
# transport failure is reported before its delayed guest process starts.
path.mkdir(parents=True,exist_ok=False)
with open(path/'.manager-stage.lock','xb') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 # Publish ownership only after the staging lease exists and is held.
 with open(path/'.manager-owned.json.tmp','x') as owner:
  json.dump(dict(token=token,stage=identity),owner);owner.flush();os.fsync(owner.fileno())
 os.replace(path/'.manager-owned.json.tmp',path/'.manager-owned.json')
 with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive: archive.extractall(path/'source',filter='data')
 (path/'.manager-guest.py').write_bytes(runner)
 for root,dirs,files in os.walk(path):
  os.chown(root,identity['uid'],identity['gid'])
  for name in files: os.chown(os.path.join(root,name),identity['uid'],identity['gid'],follow_symlinks=False)
 temporary=path/'.manager-stage.json.tmp'
 with open(temporary,'x') as receipt:
  json.dump(identity,receipt);receipt.flush();os.fsync(receipt.fileno())
  os.fchown(receipt.fileno(),identity['uid'],identity['gid'])
 os.replace(temporary,path/'.manager-stage.json')
print(json.dumps(dict(transferred_sha256=identity['archive_sha256'])))
'''

INSPECT_STAGE = IDENTITY + '''
if not path.exists():
 print(json.dumps(dict(state='absent')));raise SystemExit(0)
if not path.is_dir(): raise ValueError('Source staging path is not a directory')
marker=path/'.manager-owned.json';receipt=path/'.manager-stage.json'
if marker.is_symlink() or receipt.is_symlink(): raise ValueError('Linked source staging receipt')
if not marker.exists():
 print(json.dumps(dict(state='pending')));raise SystemExit(0)
owner=json.loads(marker.read_text())
if owner.get('token')!=token or owner.get('stage')!=identity:
 raise ValueError('Source staging ownership or request changed')
if not receipt.exists():
 print(json.dumps(dict(state='pending')));raise SystemExit(0)
if json.loads(receipt.read_text())!=identity:
 raise ValueError('Source staging completion identity changed')
print(json.dumps(dict(state='complete',identity=identity)))
'''
