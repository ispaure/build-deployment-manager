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
    if path.stat().st_size > 262144:raise ValueError('Project descriptor is too large.')
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data,dict):raise ValueError('Project descriptor must be a JSON object.')
    if data.get('schema') != 1 or data.get('adapter_api') != 1:
        raise ValueError('Unsupported project/adapter schema; API 1 is required.')
    if type(data.get('dynamic_run_inputs', False)) is not bool:
        raise ValueError('Dynamic run inputs must be explicitly enabled or disabled.')
    if not all(isinstance(data.get(k), str) and data[k] for k in ('project_id', 'name', 'bridge')):
        raise ValueError('Project identity, interpreter and bridge must be declared.')
    interpreter = data.get('interpreter')
    if isinstance(interpreter, dict):
        interpreter = interpreter.get(sys.platform)
    if not isinstance(interpreter, str) or not interpreter:
        raise ValueError('No project interpreter is declared for this host.')
    for value in (data['bridge'], interpreter):
        candidate = Path(value)
        if candidate.is_absolute() or '..' in candidate.parts or '\\' in value or ':' in value:
            raise ValueError('Descriptor paths must be checkout-relative.')
    capabilities=data.get('capabilities')
    if not isinstance(capabilities,dict):raise ValueError('Project capabilities must be declared.')
    for key in ('platforms','operations'):
        if not isinstance(capabilities.get(key),list) or not capabilities[key] or any(not isinstance(v,str) or not v for v in capabilities[key]):
            raise ValueError('Declare a nonempty list of project '+key+'.')
    from .test_results import validate_suites
    validate_suites(data.get('test_suites', []), capabilities)
    from .journeys import validate_capability
    validate_capability(data.get('journey'), capabilities)
    from .run_fields import validate_fields
    validate_fields(data.get('run_fields', []), capabilities, data.get('journey'))
    if not (root/data['bridge']).resolve().is_relative_to(root):
        raise ValueError('Project bridge must remain inside its checkout.')
    return data, hashlib.sha256(raw).hexdigest()


class Registry:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else config_directory()
        self.path = self.directory / 'registry.json'

    def read(self):
        data = load_profile(self.path)
        data.setdefault('projects', {})
        if not isinstance(data['projects'],dict):raise ValueError('Invalid registry project map; preserve and repair the private registry.')
        for row in data['projects'].values():
            if not isinstance(row,dict) or any(not isinstance(row.get(key),str) for key in ('root','project_id','name','descriptor')):
                raise ValueError('Invalid project registration; locate or repair the private registry.')
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
                    if descriptor['project_id'] != row['project_id']:
                        raise ValueError('Project identity changed; remove and register this checkout again.')
                    row.update(name=descriptor['name'], descriptor=digest, trusted=True)
                    return key
            key = str(uuid4())
            data['projects'][key] = dict(root=root, project_id=descriptor['project_id'],
                name=descriptor['name'], descriptor=digest, trusted=True, selections={})
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
            row.update(root=resolved, descriptor=digest, trusted=True)
        self.mutate(update)

    def trust(self, key, *, expected_digest=None):
        def update(data):
            row = data['projects'][key]
            descriptor, digest = inspect(row['root'])
            if descriptor['project_id'] != row['project_id']:
                raise ValueError('Project identity changed; remove and register this checkout again.')
            if expected_digest is not None and digest != expected_digest:
                raise ValueError('The descriptor changed during review. Review it again.')
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

    @staticmethod
    def validate_selections(choices):
        from .credentials import reject_secrets
        lists = {'selected_platforms', 'selected_destinations'}
        mappings = {'platform_backends', 'run_overrides', 'run_options'}
        allowed = {'operation', 'platform', 'backend', 'revision', 'pattern', 'release_tag',
                   'suite', 'goal', 'build_override'} | lists | mappings
        def valid(name, value):
            if name == 'build_override':
                return type(value) is int and 0 <= value <= 2147483647
            if name in mappings:
                expected = bool if name == 'run_options' else str
                return isinstance(value, dict) and all(isinstance(k, str) and type(v) is expected
                                                       for k, v in value.items())
            return (isinstance(value, list) and all(isinstance(item, str) for item in value)
                    if name in lists else isinstance(value, str))
        if not isinstance(choices, dict) or set(choices) - allowed or not all(valid(name, value) for name, value in choices.items()):
            raise ValueError('Invalid project selections.')
        reject_secrets(choices)

    def selections(self, key, choices):
        self.validate_selections(choices)
        def update(data):
            data['projects'][key]['selections'] = dict(choices)
        self.mutate(update)

    def save_preset(self, key, name, choices):
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError('Enter a preset name of 1–100 characters.')
        self.validate_selections(choices)
        def update(data):
            data['projects'][key].setdefault('presets', {})[name.strip()] = dict(choices)
        self.mutate(update)

    def delete_preset(self, key, name):
        def update(data):
            data['projects'][key].setdefault('presets', {}).pop(name, None)
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
        # Registration authorizes this checkout, including older registrations
        # and descriptor updates. Inspection and identity checks still apply.
        row['trusted'] = True
        row['descriptor'] = digest
        return row, descriptor
