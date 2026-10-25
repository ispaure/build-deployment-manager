"""Private registrations; reading a descriptor never imports project code."""
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import uuid4

from .locking import workspace_lock
from .profiles import load_profile, save_profile


def config_directory():
    if sys.platform == 'darwin':
        base = Path.home() / 'Library/Application Support'
    elif os.name == 'nt':
        base = Path(os.environ.get('APPDATA', Path.home() / 'AppData/Roaming'))
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    return base / 'BuildDeploymentManager'


def inspect(root):
    root = Path(root).expanduser().resolve()
    path = root / 'build-project.json'
    if not path.is_file():
        raise ValueError('Project descriptor is missing; locate a checkout containing build-project.json.')
    raw = path.read_bytes()
    data = json.loads(raw)
    if data.get('schema') != 1 or data.get('adapter_api') != 1:
        raise ValueError('Unsupported project/adapter schema; API 1 is required.')
    if not all(isinstance(data.get(k), str) and data[k] for k in ('project_id', 'name', 'bridge')):
        raise ValueError('Project identity, interpreter and bridge must be declared.')
    interpreter = data.get('interpreter')
    if isinstance(interpreter, dict):
        interpreter = interpreter.get(sys.platform)
    if not isinstance(interpreter, str) or not interpreter:
        raise ValueError('No project interpreter is declared for this host.')
    for value in (data['bridge'], interpreter):
        candidate = Path(value)
        if candidate.is_absolute() or '..' in candidate.parts:
            raise ValueError('Descriptor paths must be checkout-relative.')
    if not isinstance(data.get('capabilities'), dict):
        raise ValueError('Project capabilities must be declared.')
    return data, hashlib.sha256(raw).hexdigest()


class Registry:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else config_directory()
        self.path = self.directory / 'registry.json'

    def read(self):
        data = load_profile(self.path)
        data.setdefault('projects', {})
        return data

    def mutate(self, action):
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        if os.name!='nt':self.directory.chmod(0o700)
        with workspace_lock(self.directory / 'registry.lock'):
            data = self.read()
            result = action(data)
            save_profile(self.path, data, allowed={'projects', 'selected'})
            return result

    def add(self, root):
        root = str(Path(root).expanduser().resolve())
        descriptor, digest = inspect(root)
        def update(data):
            for key, row in data['projects'].items():
                if row['root'] == root:
                    return key
            key = str(uuid4())
            data['projects'][key] = dict(root=root, project_id=descriptor['project_id'],
                name=descriptor['name'], descriptor=digest, trusted=False, selections={})
            data.setdefault('selected', key)
            return key
        return self.mutate(update)

    def locate(self, key, root):
        descriptor, digest = inspect(root)
        def update(data):
            row = data['projects'][key]
            if descriptor['project_id'] != row['project_id']:
                raise ValueError('The located checkout has a different project identity.')
            resolved = str(Path(root).expanduser().resolve())
            if any(k != key and r['root'] == resolved for k,r in data['projects'].items()):
                raise ValueError('That checkout is already registered.')
            row.update(root=resolved, descriptor=digest, trusted=False)
        self.mutate(update)

    def trust(self, key):
        def update(data):
            row = data['projects'][key]
            descriptor, digest = inspect(row['root'])
            if descriptor['project_id'] != row['project_id']:
                raise ValueError('Project identity changed; remove and register this checkout again.')
            row.update(trusted=True, descriptor=digest)
        self.mutate(update)

    def select(self, key, *, active=False):
        if active:
            raise ValueError('Wait for the active run to finish before switching projects.')
        def update(data):
            if key not in data['projects']:
                raise ValueError('Unknown project registration.')
            data['selected'] = key
        self.mutate(update)

    def selections(self, key, choices):
        allowed = {'operation', 'platform', 'backend', 'revision', 'pattern', 'release_tag'}
        if set(choices) - allowed or any(not isinstance(value, str) for value in choices.values()):
            raise ValueError('Invalid project selections.')
        def update(data):
            data['projects'][key]['selections'] = dict(choices)
        self.mutate(update)

    def remove(self, key):
        def update(data):
            data['projects'].pop(key)
            if data.get('selected') == key:
                data['selected'] = next(iter(data['projects']), None)
        self.mutate(update)

    def resolve(self, key=None, *, trusted=False):
        data = self.read()
        row = dict(data['projects'][key or data.get('selected')])
        descriptor, digest = inspect(row['root'])
        if descriptor['project_id'] != row['project_id']:
            raise ValueError('Project identity changed; register the intended checkout.')
        if trusted and (not row['trusted'] or digest != row['descriptor']):
            raise ValueError('Review the descriptor and explicitly trust this adapter before running it.')
        return row, descriptor
