"""Private registrations; reading a descriptor never imports project code."""
import copy
import hashlib
import json
import re
import os
from pathlib import Path
import sys
from uuid import uuid4

from .configuration_files import check_registry, ensure_named_projects, folder_name
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


def read_project_descriptor(root):
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
    if 'adapter_actions' in data and (not isinstance(data['adapter_actions'], list) or any(not isinstance(v, str) or not v for v in data['adapter_actions'])):
        raise ValueError('Adapter actions must be a list of supported action names.')
    if 'commands' in data:
        from .command_project import normalize
        if not all(isinstance(data.get(k), str) and data[k] for k in ('project_id', 'name')):
            raise ValueError('Declare project identity and name.')
        return normalize(data), hashlib.sha256(raw).hexdigest()
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
        self.path = self.directory / 'configuration' / 'projects' / 'index.json'

    def _index(self):
        ensure_named_projects(self.directory)
        if not self.path.is_file():
            raise ValueError('Missing configuration/projects/index.json; restore the configuration backup.')
        index = load_profile(self.path)
        names = index.get('projects')
        if (set(index) - {'projects', 'selected'} or not isinstance(names, dict)
                or any(not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', key) for key in names)
                or any(not self._valid_path(path) for path in names.values())
                or len({path.split('/')[0].casefold() for path in names.values()}) != len(names)):
            raise ValueError('Invalid registration index.')
        return index

    @staticmethod
    def _valid_path(path):
        if not isinstance(path, str) or len(path.split('/')) != 2:
            return False
        name, filename = path.split('/')
        return (name == folder_name(name) and name.casefold() != 'index.json' and
                re.fullmatch(r'registration(?:-[a-f0-9]{32})?\.json', filename) is not None)

    def _registrations(self, index):
        rows = {}
        for key, name in index['projects'].items():
            path = self.path.parent / name
            if not path.is_file():
                raise ValueError(f'Missing checkout registration: {path}')
            rows[key] = load_profile(path)
            if rows[key].get('name') != path.parent.name:
                raise ValueError(f'Registration name must match its project folder: {path}')
        data = dict(index, projects=rows)
        check_registry(data)
        return data

    def read(self):
        return self._registrations(self._index())

    def mutate(self, action):
        ensure_named_projects(self.directory)
        with workspace_lock(self.directory / 'registry.lock'):
            index = self._index()
            before = self._registrations(index)
            data = copy.deepcopy(before)
            result = action(data)
            check_registry(data)
            names = {}
            used = {'index.json'}
            for key, row in data['projects'].items():
                name = row['name']
                if name != folder_name(name) or name.casefold() in used:
                    raise ValueError('Choose a unique project name suitable for a folder.')
                used.add(name.casefold())
                if key in before['projects'] and before['projects'][key]['name'] != name:
                    raise ValueError('An existing registration must keep its project folder name.')
                if key not in before['projects'] and (self.path.parent / name).exists():
                    raise ValueError('That project folder already exists. Choose a different registration name.')
                names[key] = index['projects'].get(key, f'{name}/registration.json')
            changed = {key: row for key, row in data['projects'].items()
                       if row != before['projects'].get(key)}
            updated = dict(data, projects=names)
            # One ordinary edit replaces its file in place. Compound mutations
            # stage existing rows under fresh names, then publish one index.
            compound = len(changed) > 1 or updated != index
            for key, row in changed.items():
                if compound and key in index['projects']:
                    names[key] = f"{row['name']}/registration-{uuid4().hex}.json"
                save_profile(self.path.parent / names[key], row, allowed=row.keys())
            if updated != index:
                save_profile(self.path, updated, allowed={'projects', 'selected'})
            return result

    def add(self, root, *, name=None):
        root = str(Path(root).expanduser().resolve())
        descriptor, descriptor_digest = read_project_descriptor(root)
        def update(data):
            for key, row in data['projects'].items():
                if row['root'] == root:
                    if descriptor['project_id'] != row['project_id']:
                        raise ValueError('Project identity changed; remove and register this checkout again.')
                    if name and name != row['name']:
                        raise ValueError('This checkout already has a registered name: ' + row['name'])
                    row.update(descriptor=descriptor_digest, trusted=True)
                    return key
            label = name if name is not None else folder_name(descriptor['name'])
            if label.casefold() in {r['name'].casefold() for r in data['projects'].values()}:
                raise ValueError('Project name already registered. Choose a distinct registration name for this checkout.')
            key = str(uuid4())
            data['projects'][key] = dict(root=root, project_id=descriptor['project_id'],
                name=label, descriptor=descriptor_digest, trusted=True, selections={})
            data.setdefault('selected', key)
            return key
        return self.mutate(update)

    def locate(self, key, root):
        descriptor, descriptor_digest = read_project_descriptor(root)
        def update(data):
            row = data['projects'][key]
            if descriptor['project_id'] != row['project_id']:
                raise ValueError('The located checkout has a different project identity.')
            resolved = str(Path(root).expanduser().resolve())
            if any(k != key and r['root'] == resolved for k,r in data['projects'].items()):
                raise ValueError('That checkout is already registered.')
            row.update(root=resolved, descriptor=descriptor_digest, trusted=True)
        self.mutate(update)

    def trust(self, key, *, expected_digest=None):
        def update(data):
            row = data['projects'][key]
            descriptor, descriptor_digest = read_project_descriptor(row['root'])
            if descriptor['project_id'] != row['project_id']:
                raise ValueError('Project identity changed; remove and register this checkout again.')
            if expected_digest is not None and descriptor_digest != expected_digest:
                raise ValueError('The descriptor changed during review. Review it again.')
            row.update(trusted=True, descriptor=descriptor_digest)
        self.mutate(update)

    def select(self, key, *, run_active=False, active=False):
        # Older automation calls use active for the same active-run guard.
        if run_active or active:
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

    def save_selections(self, key, choices):
        self.validate_selections(choices)
        def update(data):
            data['projects'][key]['selections'] = dict(choices)
        self.mutate(update)

    selections = save_selections  # Compatibility for ManagerAPI.registry callers.

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

    def project_key(self, selector=None):
        data = self.read()
        selector = selector or data.get('selected')
        if selector in data['projects']:
            return selector
        matches = [key for key, row in data['projects'].items()
                   if selector in (row['project_id'], row['name'], row['root'])]
        if len(matches) != 1:
            raise ValueError('Select a unique registered project ID, name or checkout path.')
        return matches[0]

    def resolve(self, key=None, *, trusted=False):
        data = self.read()
        row = dict(data['projects'][key or data.get('selected')])
        descriptor, descriptor_digest = read_project_descriptor(row['root'])
        if descriptor['project_id'] != row['project_id']:
            raise ValueError('Project identity changed; register the intended checkout.')
        # Registration authorizes this checkout, including older registrations
        # and descriptor updates. Inspection and identity checks still apply.
        row['trusted'] = True
        row['descriptor'] = descriptor_digest
        return row, descriptor
