"""Owned Windows guest workspaces over an explicitly supplied provider client."""
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import shutil
import time
import zipfile


OWNED = r'''
$root=[IO.Path]::GetFullPath($p.workspace)
if ((Split-Path -Leaf $root) -ne $p.token) { throw 'Workspace token/path mismatch' }
if ((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Workspace cannot be a reparse point' }
if ((Get-Content -LiteralPath (Join-Path $root '.manager-owned.json') -Raw|ConvertFrom-Json).token -ne $p.token) { throw 'Workspace ownership mismatch' }
function OwnedPath([string]$name) {
 $target=[IO.Path]::GetFullPath((Join-Path $root $name))
 if (-not $target.StartsWith($root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Path escapes owned workspace' }
 return $target
}
'''

STAGE = OWNED + r'''
$target=OwnedPath $p.folder
if (Test-Path -LiteralPath $target) { throw 'Source workspace already exists' }
$zip=OwnedPath ($p.folder+'.zip');[IO.File]::WriteAllBytes($zip,$transportInput)
if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $p.sha256) { throw 'Source transfer hash mismatch' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive=[IO.Compression.ZipFile]::OpenRead($zip)
try { foreach ($entry in $archive.Entries) {
 $path=[IO.Path]::GetFullPath((Join-Path $target $entry.FullName))
 if (-not $path.StartsWith($target+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Archive escapes source workspace' }
} } finally { $archive.Dispose() }
Expand-Archive -LiteralPath $zip -DestinationPath $target
'''

WRITE = OWNED + r'''
$target=OwnedPath $p.file
[IO.File]::WriteAllBytes($target,$transportInput)
'''

RUN = OWNED + r'''
$directory=OwnedPath $p.directory;$reports=OwnedPath $p.reports
$null=New-Item -ItemType Directory -Path $reports -Force
$stdout=Join-Path $reports 'runner.stdout.log';$stderr=Join-Path $reports 'runner.stderr.log'
$active=OwnedPath 'active.json'
@{pid=$PID;started=(Get-Process -Id $PID).StartTime.ToUniversalTime().ToString('o');operation=$p.operation;token=$p.token}|ConvertTo-Json|Set-Content -LiteralPath $active -Encoding UTF8
try {
 foreach ($property in $p.environment.PSObject.Properties) { [Environment]::SetEnvironmentVariable($property.Name,[string]$property.Value,'Process') }
 $process=Start-Process -FilePath $p.python -ArgumentList $p.command_line -WorkingDirectory $directory -NoNewWindow -PassThru -Wait -RedirectStandardOutput $stdout -RedirectStandardError $stderr
 @{exit=$process.ExitCode;operation=$p.operation}|ConvertTo-Json -Compress
} finally { if (Test-Path -LiteralPath $active) { Remove-Item -LiteralPath $active } }
'''

CANCEL = OWNED + r'''
$request=OwnedPath ('cancel-'+$p.operation)
[IO.File]::WriteAllText($request,'cancel')
Start-Sleep -Milliseconds 750
$active=OwnedPath 'active.json'
if (Test-Path -LiteralPath $active) {
 $record=Get-Content -LiteralPath $active -Raw|ConvertFrom-Json
 if ($record.token -ne $p.token -or $record.operation -ne $p.operation -or $record.pid -eq $PID) { throw 'Worker ownership mismatch' }
 $worker=Get-Process -Id $record.pid -ErrorAction SilentlyContinue
 if ($worker -and $worker.StartTime.ToUniversalTime().Ticks -eq ([DateTime]::Parse($record.started)).ToUniversalTime().Ticks) {
  $rows=Get-CimInstance Win32_Process;$ids=@([int]$record.pid)
  do { $more=@($rows|Where-Object { $ids -contains [int]$_.ParentProcessId -and $ids -notcontains [int]$_.ProcessId }|ForEach-Object {[int]$_.ProcessId});$ids+= $more } while ($more.Count -gt 0)
  $owned=@()
  foreach ($id in @($ids|Where-Object {$_ -ne $record.pid})) {
   $item=Get-Process -Id $id -ErrorAction SilentlyContinue
   $row=$rows|Where-Object {[int]$_.ProcessId -eq $id}|Select-Object -First 1
   if ($item -and $row -and [Math]::Abs($item.StartTime.ToUniversalTime().Ticks-([DateTime]$row.CreationDate).ToUniversalTime().Ticks) -le 10) { $owned+= $item }
  }
  $owned+= $worker
  foreach ($item in $owned) { try { $item.Kill() } catch [InvalidOperationException] {} }
 }
}
'''

COLLECT = OWNED + r'''
$items=@($p.paths|ForEach-Object {OwnedPath $_}|Where-Object {Test-Path -LiteralPath $_})
if ($items.Count -eq 0) { throw 'No operation evidence exists' }
$zip=OwnedPath ('evidence-'+$p.operation+'.zip')
Compress-Archive -LiteralPath $items -DestinationPath $zip -Force
@{data=[Convert]::ToBase64String([IO.File]::ReadAllBytes($zip));sha256=(Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()}|ConvertTo-Json -Compress
'''

REMOVE = OWNED + r'''
function RemoveTree([string]$path) {
 $item=Get-Item -LiteralPath $path -Force
 if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
  if ($item.PSIsContainer) { [IO.Directory]::Delete($path) } else { [IO.File]::Delete($path) }
 } elseif ($item.PSIsContainer) {
  foreach ($child in Get-ChildItem -LiteralPath $path -Force) { RemoveTree $child.FullName }
  [IO.Directory]::Delete($path)
 } else {
  $item.IsReadOnly=$false;[IO.File]::Delete($path)
 }
}
foreach ($relative in $p.paths) { $target=OwnedPath $relative;if (Test-Path -LiteralPath $target) { RemoveTree $target } }
'''


class WindowsGuest:
    def __init__(self, client, vm, workspace, token, operation):
        self.client, self.vm = client, vm
        self.values = dict(workspace=workspace, token=token, operation=operation)

    def call(self, script, *, values=None, data=None, timeout=60):
        return self.client.powershell(self.vm, script, dict(self.values, **(values or {})), data=data, timeout=timeout)

    def stage(self, folder, payload):
        self.call(STAGE, values=dict(folder=folder, sha256=hashlib.sha256(payload).hexdigest()), data=payload, timeout=180)

    def write(self, relative, data):
        self.call(WRITE, values=dict(file=relative), data=data)

    def run(self, python, argv, directory, reports, environment, cancelled, *, timeout):
        values = dict(self.values, python=python, command_line=subprocess.list2cmdline(argv),
                      directory=directory, reports=reports, environment=environment)
        process = subprocess.Popen(self.client.powershell_command(self.vm), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        payload = self.client.powershell_payload(RUN, values)
        started = time.monotonic()
        try:
            while True:
                try:
                    stdout, stderr = process.communicate(input=payload, timeout=.2)
                    break
                except subprocess.TimeoutExpired:
                    payload = None
                    if cancelled.is_set() or time.monotonic() - started > timeout:
                        self.call(CANCEL, timeout=30)
                        try:
                            process.communicate(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.terminate()
                        return 130 if cancelled.is_set() else 124
            if process.returncode:
                from .redaction import Redactor
                raise RuntimeError('Windows operation transport failed: ' + Redactor()(stderr.decode(errors='replace')[-2000:]))
            code = json.loads(stdout)['exit']
            if not isinstance(code, int):
                raise ValueError('Windows worker did not report an actual process exit code.')
            return code
        finally:
            if process.poll() is None:
                self.call(CANCEL, timeout=30)
                process.terminate()
                process.wait(timeout=3)

    def collect(self, paths, destination):
        record = json.loads(self.call(COLLECT, values=dict(paths=paths), timeout=180))
        payload = base64.b64decode(record['data'], validate=True)
        if hashlib.sha256(payload).hexdigest() != record['sha256']:
            raise ValueError('Windows evidence transfer digest mismatch.')
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for entry in archive.infolist():
                relative = entry.filename.replace('\\', '/')
                if relative.startswith('/') or '..' in Path(relative).parts or ':' in relative:
                    raise ValueError('Evidence archive escapes its result directory.')
                target = destination / relative
                if entry.is_dir() or relative.endswith('/') or entry.external_attr & 0x10:
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as source, target.open('wb') as output:
                        shutil.copyfileobj(source, output)

    def remove_paths(self, paths):
        self.call(REMOVE, values=dict(paths=paths), timeout=120)
