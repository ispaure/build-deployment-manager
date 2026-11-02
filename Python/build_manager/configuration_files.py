"""Publish a private, editable configuration tree from legacy data exactly once."""
from pathlib import Path
import os
import re
from tempfile import TemporaryDirectory

from commonUtils.persistence import atomic_write_bytes
from .device_catalog import recipient_platforms_by_field
from .locking import workspace_lock
from .profiles import load_profile, save_profile
from .run_fields import parse_multiselect_ids


def check_registry(data):
    if set(data) - {'projects', 'selected'} or not isinstance(data.get('projects', {}), dict):
        raise ValueError('Invalid registry project map.')
    for row in data.get('projects', {}).values():
        if not isinstance(row, dict) or any(not isinstance(row.get(key), str)
                for key in ('root', 'project_id', 'name', 'descriptor')):
            raise ValueError('Invalid project registration.')


def collect_saved_recipient_ids(catalogs, registration):
    from .registry import read_project_descriptor
    try:
        descriptor, _ = read_project_descriptor(registration['root'])
    except (ValueError, OSError):
        return  # A disconnected checkout must remain registered and relocatable.
    if descriptor['project_id'] != registration['project_id']:
        return
    for field, platform in recipient_platforms_by_field(descriptor).items():
        for choices in [registration.get('selections', {}), *registration.get('presets', {}).values()]:
            value = choices.get('run_overrides', {}).get(field)
            if value:
                try:
                    catalogs[platform].update(parse_multiselect_ids(value))
                except ValueError:
                    continue  # Preserve historical inputs verbatim in the registration.


def ensure_configuration(directory):
    from .settings import normalize_and_validate_shared_settings
    target = directory / 'configuration'
    if target.is_dir():
        return
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        directory.chmod(0o700)
    with workspace_lock(directory / 'registry.lock', timeout=5):
        if target.is_dir():
            return
        with workspace_lock(directory / 'settings.lock', timeout=5):
            legacy = load_profile(directory / 'registry.json')
            check_registry(legacy)
            settings = load_profile(directory / 'settings.json')
            normalize_and_validate_shared_settings(settings, directory / 'settings.json')
            with TemporaryDirectory(dir=directory) as temporary:
                tree = Path(temporary) / 'configuration'
                rows = legacy.get('projects', {})
                catalogs = {'ios': set(), 'android': set()}
                for row in rows.values():
                    collect_saved_recipient_ids(catalogs, row)
                write_named_projects(tree / 'projects', legacy, rows, directory)
                save_profile(tree / 'shared-settings.json', settings,
                             allowed={'accounts', 'machines', 'projects', 'migrations'})
                devices = tree / 'devices'
                devices.mkdir(mode=0o700)
                for platform, ids in catalogs.items():
                    body = '# One paired device per line: exact ID = display name\n[devices]\n'
                    body += ''.join(f'{key} = {key}\n' for key in sorted(ids))
                    atomic_write_bytes(devices / (platform + '.ini'), body.encode(), file_mode=0o600)
                tree.rename(target)


def folder_name(name):
    """A portable folder component that can also serve as a picker label."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', name).strip().rstrip('. ')[:80].rstrip('. ')
    if not name:
        name = 'Project'
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'{p}{i}' for p in ('COM', 'LPT') for i in range(1, 10))}:
        name = '_' + name
    return name


def ensure_named_projects(directory):
    """Switch all registration and adapter-profile paths in a single rename."""
    config = directory / 'configuration'
    target = config / 'projects'
    if target.is_dir():
        return
    ensure_configuration(directory)
    with workspace_lock(directory / 'registry.lock', timeout=5):
        if target.is_dir():
            return
        source = config / 'index.json'
        if not source.is_file():
            raise ValueError(f'Missing registration index: {source}')
        index = load_profile(source)
        names = index.get('projects')
        if not isinstance(names, dict) or set(index) - {'projects', 'selected'}:
            raise ValueError('Invalid registration index.')
        rows = {}
        for key, filename in names.items():
            if (not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', key) or not isinstance(filename, str)
                    or not re.fullmatch(r'[A-Za-z0-9_-]+\.json', filename)):
                raise ValueError('Invalid registration index.')
            rows[key] = load_profile(config / 'checkouts' / filename)
        check_registry(dict(index, projects=rows))
        with TemporaryDirectory(dir=config) as tmp:
            tree = Path(tmp) / 'projects'
            write_named_projects(tree, index, rows, directory)
            tree.rename(target)


def write_named_projects(tree, index, rows, directory):
    used = {'index.json'}
    paths = {}
    for key, row in rows.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', key):
            raise ValueError('Invalid registration ID.')
        base = folder_name(row['name'])
        name = base
        if name.casefold() in used:
            root = Path(row['root'])
            hint = root.parent.name if root.name.casefold() == base.casefold() else root.name
            if hint.casefold().startswith(base.casefold() + '-'):
                hint = hint[len(base)+1:]
            suffix = folder_name(hint)[:40]
            name = folder_name(f'{base[:35]} - {suffix}')
            candidate = name
            number = 2
            while name.casefold() in used:
                name = f'{candidate[:72]} {number}'
                number += 1
        used.add(name.casefold())
        row['name'] = name
        paths[key] = f'{name}/registration.json'
        save_profile(tree / paths[key], row, allowed=row.keys())
        profile = directory / 'projects' / key / 'profile.json'
        if profile.is_file():
            atomic_write_bytes(tree / name / 'profile.json', profile.read_bytes(), file_mode=0o600)
    save_profile(tree / 'index.json', dict(index, projects=paths), allowed={'projects','selected'})
