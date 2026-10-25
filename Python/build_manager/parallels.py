"""Existing Parallels guest transport; project adapters own suites and VM policy."""
import base64
import hashlib
import io
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tarfile
import time
from uuid import UUID

from .redaction import Redactor


STAGE = '''import base64,hashlib,io,json,os,pathlib,sys,tarfile
path=pathlib.Path(sys.argv[1]); token=sys.argv[2]; expected=sys.argv[3]; uid=int(sys.argv[4]); gid=int(sys.argv[5])
data=base64.b64decode(sys.stdin.buffer.read(),validate=False)
if hashlib.sha256(data).hexdigest()!=expected: raise ValueError('Source transfer digest mismatch')
path.mkdir(parents=True,exist_ok=False)
(path/'.manager-owned.json').write_text(json.dumps(dict(token=token)))
with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive: archive.extractall(path/'source',filter='data')
for root,dirs,files in os.walk(path):
 os.chown(root,uid,gid)
 for name in files: os.chown(os.path.join(root,name),uid,gid,follow_symlinks=False)
print(json.dumps(dict(transferred_sha256=expected)))
'''

OWNED = '''import json,pathlib,sys
path=pathlib.Path(sys.argv[1]); token=sys.argv[2]
if path.is_symlink() or path.resolve()!=path or path.name!=token or json.loads((path/'.manager-owned.json').read_text())['token']!=token:
 raise ValueError('Guest workspace ownership mismatch')
'''

COLLECT = OWNED + '''
import base64,io,tarfile
stream=io.BytesIO()
with tarfile.open(fileobj=stream,mode='w:gz') as archive:
 for name in ('reports','source/test-results'):
  source=path/name
  if source.exists(): archive.add(source,arcname=name)
print(base64.b64encode(stream.getvalue()).decode())
'''

REMOVE = '''import pathlib,sys
if not pathlib.Path(sys.argv[1]).exists(): raise SystemExit(0)
''' + OWNED + '''
import shutil
shutil.rmtree(path)
'''

CANCEL = OWNED + '''
import os,signal,time
record=path/'active.json'
if record.exists():
 data=json.loads(record.read_text()); pid=data['pid']
 if data['token']!=token: raise ValueError('Active process ownership mismatch')
 rows={}
 for entry in pathlib.Path('/proc').glob('[0-9]*/stat'):
  try:
   fields=entry.read_text().rsplit(')',1)[1].split()
   rows[int(entry.parent.name)]=(int(fields[1]),fields[19])
  except (OSError,ValueError,IndexError): pass
 owned={pid}
 while True:
  more={child for child,(parent,_) in rows.items() if parent in owned}-owned
  if not more: break
  owned.update(more)
 for sig in (signal.SIGTERM,signal.SIGKILL):
  for child in sorted(owned-{pid})+[pid]:
   try:
    current=pathlib.Path('/proc',str(child),'stat').read_text().rsplit(')',1)[1].split()[19]
    if child in rows and current==rows[child][1]: os.kill(child,sig)
   except (OSError,ValueError,IndexError): pass
  if sig==signal.SIGTERM: time.sleep(1)
'''


class Parallels:
    def __init__(self, executable=None):
        self.executable = executable or shutil.which('prlctl')
        if not self.executable:
            raise ValueError('Parallels command-line tools are unavailable. No hosted fallback was selected.')

    def inventory(self):
        return json.loads(subprocess.check_output([self.executable, 'list', '--all', '--json'], timeout=30))

    def selected(self, selector):
        matches = [item for item in self.inventory() if selector and selector in (item['uuid'], item['name'])]
        if len(matches) != 1:
            raise ValueError('Select exactly one existing guest from the Parallels inventory.')
        return matches[0]

    def start(self, selector):
        original = self.selected(selector)
        if original['status'] != 'running':
            if original['status'] != 'stopped':
                raise ValueError('Selected guest is suspended or busy; choose a stopped/running test guest explicitly.')
            subprocess.run([self.executable, 'start', original['uuid']], check=True, timeout=120)
        return original

    def command(self, selector, argv):
        # prlctl joins Linux exec arguments for the guest shell. Quote *every*
        # literal argument at this transport boundary; UI strings are not scripts.
        if not argv or any(not isinstance(value, str) or '\x00' in value for value in argv):
            raise ValueError('Guest commands require structured literal arguments.')
        UUID(selector)
        return [self.executable, 'exec', selector, *(shlex.quote(value) for value in argv)]

    def powershell_command(self, selector):
        UUID(selector)
        # A large -EncodedCommand crosses cmd.exe's command-line limit inside
        # guest tools. Only this fixed loader is in argv. The authenticated
        # stdin envelope carries trusted adapter code and separately bound data.
        loader = "$ErrorActionPreference='Stop';$ProgressPreference='SilentlyContinue';"
        loader += "$request=[Console]::In.ReadToEnd()|ConvertFrom-Json;$p=$request.values;"
        loader += "$transportInput=[Convert]::FromBase64String($request.data);& ([ScriptBlock]::Create($request.script))"
        encoded = base64.b64encode(loader.encode('utf-16le')).decode()
        return [self.executable, 'exec', selector, '--current-user', 'powershell.exe',
                '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]

    @staticmethod
    def powershell_payload(script, values=None, data=None):
        return json.dumps(dict(script=script, values=values or {}, data=base64.b64encode(data or b'').decode())).encode()

    def powershell(self, selector, script, values=None, *, data=None, timeout=60):
        result = subprocess.run(self.powershell_command(selector),
                                input=self.powershell_payload(script, values, data), capture_output=True, timeout=timeout)
        if result.returncode:
            detail = Redactor()(result.stderr.decode('utf-8', errors='replace')[-3000:])
            raise RuntimeError(f'Windows guest command failed ({result.returncode}): ' + detail)
        return result.stdout

    def execute(self, selector, argv, *, data=None, timeout=60):
        result = subprocess.run(self.command(selector, argv), input=data, capture_output=True, timeout=timeout)
        if result.returncode:
            detail = Redactor()(result.stderr.decode('utf-8', errors='replace')[-3000:])
            raise RuntimeError(f'Guest command failed ({result.returncode}); verify guest tools and prerequisites. ' + detail)
        return result.stdout

    def run_owned(self, vm, workspace, token, uid, argv, environment, cancelled, *, timeout):
        payload = base64.b64encode(json.dumps(dict(argv=argv, environment=environment)).encode()).decode()
        command = ['python3', workspace + '/source/build_manager/guest.py', workspace, token, str(uid)]
        # Parallels guest tools impose a command-line limit even for Linux.
        # Carry trusted structured data over stdin, as the Windows transport does.
        process = subprocess.Popen(self.command(vm, command), stdin=subprocess.PIPE)
        try:
            process.stdin.write(payload.encode())
        finally:
            process.stdin.close()
        started = time.monotonic()
        try:
            while process.poll() is None:
                if cancelled.is_set() or time.monotonic() - started > timeout:
                    self.cancel(vm, workspace, token)
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                    return 130 if cancelled.is_set() else 124
                time.sleep(.1)
            return process.returncode
        finally:
            if process.poll() is None:
                self.cancel(vm, workspace, token)
                process.terminate()
                process.wait(timeout=2)

    def stage(self, selector, snapshot, workspace, token, uid, gid, *, members=None):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz') as archive:
            if members is None:
                archive.add(snapshot, arcname='.')
            else:
                for name in members:
                    relative = Path(name)
                    if relative.is_absolute() or '..' in relative.parts:
                        raise ValueError('Source members must stay within the selected snapshot.')
                    archive.add(Path(snapshot) / relative, arcname=str(relative))
        payload = data.getvalue()
        digest = hashlib.sha256(payload).hexdigest()
        self.execute(selector, ['python3', '-c', STAGE, workspace, token, digest, str(uid), str(gid)],
                     data=base64.b64encode(payload), timeout=180)
        return digest

    def collect(self, selector, workspace, token, destination):
        raw = self.execute(selector, ['python3', '-c', COLLECT, workspace, token], timeout=120)
        data = base64.b64decode(raw.strip(), validate=True)
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=False)
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            archive.extractall(destination, filter='data')

    def cancel(self, selector, workspace, token):
        self.execute(selector, ['python3', '-c', CANCEL, workspace, token], timeout=30)

    def cleanup(self, selector, argv, *, timeout=60):
        # Only callers supplying idempotent, ownership-checked cleanup scripts
        # use this path. Never retry tests, uploads or arbitrary mutations.
        for attempt in range(3):
            try:
                return self.execute(selector, argv, timeout=timeout)
            except RuntimeError as error:
                if attempt == 2 or '(255)' not in str(error) or 'Invalid argument' not in str(error):
                    raise
                time.sleep(.2)

    def remove(self, selector, workspace, token):
        self.cleanup(selector, ['python3', '-c', REMOVE, workspace, token], timeout=30)

    def owned_exists(self, selector, workspace, token):
        code = '''import pathlib,sys
path=pathlib.Path(sys.argv[1])
if not path.exists(): print('false'); raise SystemExit(0)
''' + OWNED + "\nprint('true')\n"
        return self.execute(selector, ['python3', '-c', code, workspace, token], timeout=30).strip() == b'true'

    def shutdown(self, selector):
        subprocess.run([self.executable, 'stop', selector], check=True, timeout=120)
