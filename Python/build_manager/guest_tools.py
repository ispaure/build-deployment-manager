"""Transport-independent isolated guest tool preparation; callers supply all pins.

Run only inside an explicitly selected guest and an owned workspace. Preparation
is not project validation; source transfer, suite policy and receipt storage
remain with the caller.
"""
import re
from urllib.parse import urlsplit


def windows_parameters(token, tools, *, python, guest_architecture, python_architecture):
    """Validate a portable uv/Git catalog before issuing a guest command."""
    if not re.fullmatch(r'[a-f0-9]{32}', token):
        raise ValueError('Invalid workspace ownership token.')
    for value in (python, guest_architecture, python_architecture):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', value):
            raise ValueError('Invalid interpreter or architecture selector.')
    catalog = {}
    for name in ('uv', 'git'):
        tool = tools[name]
        url = urlsplit(tool['url'])
        if (url.scheme != 'https' or url.hostname != 'github.com' or url.username
                or url.password or url.port not in (None, 443)
                or not re.fullmatch(r'[a-f0-9]{64}', tool['sha256'])):
            raise ValueError('Invalid pinned tool metadata.')
        catalog[name] = dict(tool)
    return dict(token=token, tools=catalog, python=python,
                guest_architecture=guest_architecture, python_architecture=python_architecture)


def linux_parameters(*, uv_version, python):
    """Return data for LINUX_BOOTSTRAP without embedding pins in executable code."""
    for value in (uv_version, python):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+', value):
            raise ValueError('Invalid interpreter or uv version selector.')
    return dict(uv_version=uv_version, python=python)


WINDOWS_PREPARE = r'''
if ((Get-Process -Id $PID).SessionId -eq 0) { throw 'Use the existing interactive guest test account.' }
if ($env:PROCESSOR_ARCHITECTURE -ne $p.guest_architecture) { throw 'This tool catalog requires the selected guest architecture.' }
if ($p.token -notmatch '^[a-f0-9]{32}$') { throw 'Invalid workspace ownership token.' }
$root=Join-Path ([Environment]::GetFolderPath('CommonDocuments')) ('bm\'+$p.token)
if (Test-Path -LiteralPath $root) { throw 'Owned workspace already exists; inspect it before retry.' }
$null=New-Item -ItemType Directory -Path $root
@{token=$p.token}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $root '.manager-owned.json') -Encoding UTF8
$downloads=Join-Path $root 'downloads'; $null=New-Item -ItemType Directory -Path $downloads
$tools=Join-Path $root 'tools'; $null=New-Item -ItemType Directory -Path $tools
$resolved=@{}
foreach ($entry in @(@{name='uv';value=$p.tools.uv},@{name='git';value=$p.tools.git})) {
 $tool=$entry.value
 if ($tool.url -notmatch '^https://github.com/' -or $tool.sha256 -notmatch '^[a-f0-9]{64}$') { throw 'Invalid pinned tool metadata.' }
 $zip=Join-Path $downloads ($entry.name+'.zip')
 Invoke-WebRequest -UseBasicParsing -Uri $tool.url -OutFile $zip -TimeoutSec 120
 if ((Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $tool.sha256) { throw 'Tool archive hash mismatch.' }
 $folder=Join-Path $tools $entry.name
 Expand-Archive -LiteralPath $zip -DestinationPath $folder
 $resolved[$entry.name]=(Get-ChildItem -LiteralPath $folder -Filter ($entry.name+'.exe') -Recurse|Select-Object -First 1).FullName
 if (-not $resolved[$entry.name]) { throw ('Tool executable missing: '+$entry.name) }
}
$env:UV_PYTHON_INSTALL_DIR=Join-Path $root 'python';$env:UV_CACHE_DIR=Join-Path $root 'cache';$env:UV_PYTHON_ARCH=$p.python_architecture
$environment=Join-Path $root 'environment'
& $resolved.uv venv --python $p.python --seed $environment
if ($LASTEXITCODE -ne 0) { throw 'Pinned Windows interpreter preparation failed.' }
$python=Join-Path $environment 'Scripts\python.exe'
$version=& $python -c 'import json,platform,sys;print(json.dumps(dict(version=sys.version,architecture=platform.machine())))'
if ($LASTEXITCODE -ne 0) { throw 'Pinned interpreter could not execute.' }
$record=@{token=$p.token;workspace=$root;python=$python;uv=$resolved.uv;git=$resolved.git;runtime=($version|ConvertFrom-Json);guestArchitecture=$env:PROCESSOR_ARCHITECTURE;session=(Get-Process -Id $PID).SessionId}
$record|ConvertTo-Json -Depth 5|Set-Content -LiteralPath (Join-Path $root 'prepared.json') -Encoding UTF8
$record|ConvertTo-Json -Depth 5 -Compress
'''


LINUX_BOOTSTRAP = '''import json,pathlib,subprocess,sys
p=json.loads(sys.argv[2])
root=pathlib.Path(sys.argv[1]); bootstrap=root/'bootstrap'; environment=root/'environment'
subprocess.run([sys.executable,'-m','venv',str(bootstrap)],check=True,timeout=120)
python=bootstrap/'bin/python'
subprocess.run([str(python),'-m','pip','install','uv=='+p['uv_version']],check=True,timeout=300)
subprocess.run([str(python),'-m','uv','venv','--python',p['python'],'--seed',str(environment)],check=True,timeout=600)
'''
