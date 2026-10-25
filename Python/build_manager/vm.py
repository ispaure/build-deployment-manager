"""Dedicated, ownership-checked Parallels test machines. No Qt or project imports."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from uuid import UUID, uuid4

from .locking import workspace_lock
from .parallels import Parallels
from .profiles import save_json
from .redaction import Redactor


class VM:
    """Reuse our recorded guest, register its relocated bundle, or create it missing.

    A same-named machine without this checkout's receipt is never adopted. OS
    installation and test readiness are separate from creating virtual hardware.
    """
    kind = distribution = ''
    memory = 4096

    def __init__(self, checkout, client=None, event=lambda message: None):
        self.checkout = Path(checkout).resolve()
        self.root = self.checkout / 'VM'
        if self.root.is_symlink():
            raise ValueError('VM storage must be a real directory inside this checkout.')
        self.client = client or Parallels()
        self.event = event
        self.name = f'Build Deployment Manager ({self.kind})'
        self.record = self.root / (self.kind.lower() + '.json')

    def run(self, *args, timeout=120):
        self.event(' '.join(args[:2]))
        result = subprocess.run([self.client.executable, *map(str, args)],
                                capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(Redactor()((result.stderr or result.stdout)[-4000:]))
        return result.stdout

    def receipt(self):
        if self.record.is_symlink():
            raise ValueError('VM ownership receipt cannot be a symlink.')
        if not self.record.exists():
            return None
        data = json.loads(self.record.read_text())
        if data.get('schema') != 1 or data.get('name') != self.name:
            raise ValueError('Invalid VM ownership receipt.')
        UUID(data['uuid'])
        expected = self.root / (self.name + '.pvm')
        if data.get('bundle') != str(expected) or expected.is_symlink():
            raise ValueError('VM bundle ownership/path mismatch.')
        return data

    def selected(self):
        record = self.receipt()
        rows = self.client.inventory()
        matches = [r for r in rows if r['name'] == self.name or
                   (record and r['uuid'].strip('{}') == record['uuid'])]
        if not matches:
            return record, None
        if not record or len(matches) != 1 or matches[0]['uuid'].strip('{}') != record['uuid']:
            raise ValueError('A conflicting VM exists. Only this checkout’s recorded UUID may be used.')
        # Inventory alone cannot establish that a guest still lives in our folder.
        info = json.loads(self.run('list', record['uuid'], '--info', '--json'))
        if isinstance(info, list):
            info = info[0]
        home = info.get('Home') or info.get('home')
        if not home or Path(home).resolve() != Path(record['bundle']).resolve():
            raise ValueError('Recorded guest moved outside this checkout’s VM folder.')
        return record, matches[0]

    def ensure(self, *, restore=True):
        result = self._ensure_hardware()
        record = self.receipt()
        recipe = record.get('restore_recipe') if record else None
        if restore and recipe:
            methods = {'fedora-cloud': getattr(self, 'initialize_cloud', None),
                       'windows': getattr(self, 'initialize_unattended', None)}
            method = methods.get(recipe.get('kind'))
            if not method:
                raise ValueError('Saved recreation recipe does not match this guest OS.')
            self.event('Recreating OS from verified retained installation media')
            result = method(recipe['media'], recipe['sha256'])
            with workspace_lock(self.root / '.provision.lock'):
                record = self.receipt()
                record.pop('restore_recipe', None)
                save_json(self.record, record)
        return result

    def _ensure_hardware(self):
        if platform.system() != 'Darwin':
            raise ValueError('Dedicated Parallels provisioning requires macOS.')
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.root.chmod(0o700)
        with workspace_lock(self.root / '.provision.lock'):
            record, row = self.selected()
            if row:
                if record.get('state') == 'creating':
                    if row['status'] != 'stopped':
                        raise ValueError('Stop the partially configured guest before recovering setup.')
                    self.configure(record['uuid'])
                    record['state'] = 'installation-required'
                    save_json(self.record, record)
                return self.status()
            if record and Path(record['bundle']).exists():
                self.run('register', record['bundle'])
                return self.status()
            if shutil.disk_usage(self.root).free < 24 * 1024**3:
                raise ValueError('At least 24 GiB of host free space is required before creating a guest.')
            if record:
                # Keep prior identities for audit, never overwrite a surviving bundle.
                save_json(self.record.with_suffix('.previous.json'), record)
            recipe = record.get('recipe') if record else None
            record = dict(schema=1, uuid=str(uuid4()), name=self.name,
                          bundle=str(self.root / (self.name + '.pvm')), state='creating')
            if recipe: record['restore_recipe'] = recipe
            save_json(self.record, record)
            self.run('create', self.name, '--distribution', self.distribution,
                     '--dst', self.root, '--uuid', record['uuid'])
            self.configure(record['uuid'])
            record['state'] = 'installation-required'
            save_json(self.record, record)
            return self.status()

    def configure(self, uid):
        self.run('set', uid, '--cpus', '4', '--memsize', str(self.memory))
        self.run('set', uid, '--isolate-vm', 'on')
        self.run('set', uid, '--shf-host', 'off', '--shf-guest', 'off')
        self.run('set', uid, '--shared-profile', 'off', '--shared-clipboard', 'off', '--shared-cloud', 'off')

    def initialize(self, media, sha256):
        """Attach verified installer media. Subclasses define OS prerequisites."""
        path = Path(media).resolve(strict=True)
        if not path.is_file() or path.suffix.lower() != '.iso':
            raise ValueError('Select an OS installer ISO file.')
        if len(sha256) != 64 or any(c not in '0123456789abcdefABCDEF' for c in sha256):
            raise ValueError('Supply the vendor’s SHA-256 for the installer ISO.')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if digest.lower() != sha256.lower():
            raise ValueError('Installer checksum mismatch.')
        self.ensure(restore=False)
        with workspace_lock(self.root / '.provision.lock'):
            record, row = self.selected()
            if row['status'] != 'stopped':
                raise ValueError('Stop this dedicated VM before attaching installation media.')
            self.run('set', record['uuid'], '--device-set', 'cdrom0', '--image', path, '--connect')
            record.update(media=str(path), media_sha256=digest, state='installation-required')
            save_json(self.record, record)
        return self.status()

    def power(self, action):
        if action not in ('start', 'stop'):
            raise ValueError('Unsupported VM power action.')
        with workspace_lock(self.root / '.provision.lock'):
            record, row = self.selected()
            if not row:
                raise ValueError('Create or recover this dedicated VM first.')
            if (action == 'start' and row['status'] == 'running') or (action == 'stop' and row['status'] == 'stopped'):
                return self.status()
            if row['status'] not in ('stopped', 'running'):
                raise ValueError('VM is busy or suspended; inspect it in Parallels before continuing.')
            if action == 'start':
                record['ever_started'] = True
                save_json(self.record, record)
            # ACPI shutdown remains usable before guest tools are installed.
            if action == 'stop': self.run(action, record['uuid'], '--acpi')
            else: self.run(action, record['uuid'])
        return self.status()

    def status(self):
        record, row = self.selected()
        return dict(name=self.name, kind=self.kind, uuid=record['uuid'] if record else None,
                    storage=str(self.root), state=row['status'] if row else 'missing',
                    setup=record.get('state', 'installation-required') if record else 'not-created',
                    requirements=self.requirements(), note='Run Check readiness after OS and guest tools installation.')

    def readiness(self):
        record, row = self.selected()
        if not row or row['status'] != 'running':
            raise ValueError('Start the installed dedicated guest before checking readiness.')
        proof = self.probe(record['uuid'])
        if (not isinstance(proof, dict) or proof.get('system') != self.kind or
                tuple(proof.get('python_version', ())) < (3, 12) or not proof.get('git')):
            raise ValueError('Guest OS/Python/Git readiness is incomplete: ' + json.dumps(proof))
        save_json(self.root / (self.kind.lower() + '-readiness.json'), proof)
        record['state'] = 'test-tools-ready'
        save_json(self.record, record)
        return dict(self.status(), readiness=proof)

    def requirements(self):
        raise NotImplementedError

    def probe(self, uid):
        raise NotImplementedError


class LinuxVM(VM):
    kind, distribution = 'Linux', 'fedora-core'

    def initialize(self, media, sha256):
        return super().initialize(media, sha256)

    def initialize_cloud(self, media, sha256):
        """Install a verified Fedora cloud disk and a private NoCloud seed.

        Only a newly created, never-started guest may receive the initial disk.
        Repeating this operation reuses the disk; it never overwrites guest data.
        """
        from .vm_bootstrap import fedora_seed, import_fedora_disk
        path = Path(media).resolve(strict=True)
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if len(sha256) != 64 or digest != sha256.lower():
            raise ValueError('Fedora cloud image checksum mismatch.')
        self.ensure(restore=False)
        with workspace_lock(self.root / '.provision.lock'):
            record, row = self.selected()
            if record.get('cloud_initialized'):
                return self.status()
            if row['status'] != 'stopped' or record.get('ever_started') or record.get('state') != 'installation-required':
                raise ValueError('Cloud initialization requires a new stopped dedicated guest.')
            disk = Path(record['bundle']) / 'Fedora.hdd'
            if disk.exists():
                raise ValueError('A Fedora disk already exists; recover it explicitly instead of overwriting it.')
            import_fedora_disk(path, disk, self.event)
            seed = fedora_seed(self.root, record['uuid'])
            self.run('set', record['uuid'], '--device-del', 'hdd0')
            self.run('set', record['uuid'], '--device-add', 'hdd', '--image', disk, '--iface', 'nvme')
            self.run('set', record['uuid'], '--device-set', 'cdrom0', '--image', seed, '--connect')
            tools = Path('/Applications/Parallels Desktop.app/Contents/Resources/Tools/prl-tools-lin-arm.iso')
            self.run('set', record['uuid'], '--device-add', 'cdrom', '--image', tools)
            self.run('set', record['uuid'], '--device-set', 'cdrom1', '--connect')
            record.update(cloud_initialized=True, media=str(path), media_sha256=digest, state='first-boot-required',
                          recipe=dict(kind='fedora-cloud', media=str(path), sha256=digest))
            save_json(self.record, record)
        return self.status()

    def requirements(self):
        return 'Fedora ARM64, Parallels Tools, Python ≥3.12, Git, venv/pip and a desktop session. Android needs a separate acceleration check.'

    def probe(self, uid):
        code = "import json,platform,shutil,sys;print(json.dumps(dict(system=platform.system(),architecture=platform.machine(),python=sys.version,python_version=list(sys.version_info[:3]),git=shutil.which('git'),kvm=__import__('os').access('/dev/kvm',6))))"
        return json.loads(self.client.execute(uid, ['python3', '-c', code]))


class WindowsVM(VM):
    kind, distribution, memory = 'Windows', 'win-11', 6144

    def initialize(self, media, sha256):
        return super().initialize(media, sha256)

    def initialize_unattended(self, media, sha256):
        from .vm_bootstrap import windows_seed
        self.ensure(restore=False)
        with workspace_lock(self.root / '.provision.lock'):
            record, row = self.selected()
            if record.get('windows_initialized'):
                return self.status()
            if row['status'] != 'stopped' or record.get('ever_started'):
                raise ValueError('Unattended disk installation is only allowed on a new, never-started guest.')
        self.initialize(media, sha256)
        with workspace_lock(self.root / '.provision.lock'):
            record, row = self.selected()
            if row['status'] != 'stopped' or record.get('ever_started'):
                raise ValueError('Guest changed while preparing setup; installation stopped.')
            seed = windows_seed(self.root)
            self.run('set', record['uuid'], '--device-add', 'cdrom', '--image', seed)
            self.run('set', record['uuid'], '--device-set', 'cdrom1', '--connect')
            self.run('set', record['uuid'], '--device-bootorder', 'cdrom0 hdd0')
            record.update(windows_initialized=True, state='first-boot-required',
                          recipe=dict(kind='windows', media=record['media'], sha256=record['media_sha256']))
            save_json(self.record, record)
        return self.status()

    def requirements(self):
        return 'Windows 11 ARM64, completed Windows setup/license, Parallels Tools, Python ≥3.12, Git and an interactive test user. Nested Android acceleration is a separate gate.'

    def probe(self, uid):
        script = "$ErrorActionPreference='Stop';$v=& python -c 'import json,platform,sys;print(json.dumps(dict(system=platform.system(),architecture=platform.machine(),python=sys.version,python_version=list(sys.version_info[:3]))))';if($LASTEXITCODE -ne 0){throw 'Python unavailable'};$r=$v|ConvertFrom-Json;$r|Add-Member git (Get-Command git -ErrorAction Stop).Source;$r|ConvertTo-Json -Compress"
        return json.loads(self.client.powershell(uid, script))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind', choices=('linux', 'windows'))
    parser.add_argument('action', choices=('status', 'ensure', 'initialize', 'initialize-cloud', 'initialize-windows', 'start', 'stop', 'readiness'))
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--media', type=Path)
    parser.add_argument('--sha256', default='')
    args = parser.parse_args(argv)
    try:
        vm = (LinuxVM if args.kind == 'linux' else WindowsVM)(args.checkout)
        if args.action in ('initialize', 'initialize-cloud', 'initialize-windows'):
            if not args.media:
                raise ValueError('Select installer media and its vendor checksum.')
            if args.action == 'initialize-cloud' and not isinstance(vm, LinuxVM) or args.action == 'initialize-windows' and not isinstance(vm, WindowsVM):
                raise ValueError('Initialization method does not match the selected OS.')
            method = {'initialize': vm.initialize, 'initialize-cloud': getattr(vm, 'initialize_cloud', None),
                      'initialize-windows':getattr(vm, 'initialize_unattended', None)}[args.action]
            result = method(args.media, args.sha256)
        elif args.action in ('start', 'stop'):
            result = vm.power(args.action)
        else:
            result = getattr(vm, args.action)()
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print(Redactor()(str(error)), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
