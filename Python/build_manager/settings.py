"""Versioned non-secret settings layers and explicit legacy migration."""
from dataclasses import dataclass
from contextlib import contextmanager
import hashlib
import re
from pathlib import Path

from .configuration_files import ensure_configuration
from .locking import workspace_lock
from .profiles import load_profile, save_profile
from .registry import config_directory
from .credentials import reject_secrets, resolve_external_credential_path


@dataclass(frozen=True)
class Field:
    default: object
    account: bool = False
    machine: bool = False
    guarded: bool = False
    variable: str | None = None


def resolve(schema, *, account=None, machine=None, profile=None, environment=None, overrides=None):
    values = {key:field.default for key,field in schema.items()}
    origins = dict.fromkeys(values,'tracked project default')
    layers = [('selected account',account or {}),('selected machine',machine or {}),
              ('project profile',profile or {}),('environment',
               {key:environment[field.variable] for key,field in schema.items()
                if environment is not None and field.variable and field.variable in environment}),('run override',overrides or {})]
    for origin,layer in layers:
        for key,value in layer.items():
            if key not in schema:
                raise ValueError('Unknown settings field: '+key)
            field=schema[key]
            if origin=='selected account' and not field.account:
                raise ValueError('Shared accounts cannot supply project destinations: '+key)
            if origin=='selected machine' and not field.machine:
                raise ValueError('Machine defaults cannot supply project destinations: '+key)
            if field.guarded and value!=field.default:
                raise ValueError('Project identity is guarded: '+key)
            expected=type(field.default)
            if type(value) is not expected:
                if expected is int and isinstance(value,str) and value.isdecimal():value=int(value)
                elif expected is bool and isinstance(value,str) and value.lower() in ('true','false'):value=value.lower()=='true'
                else:raise ValueError('Wrong setting type: '+key)
            values[key],origins[key]=value,origin
    return values,origins


def setting_reset(name, row):
    """Return the adapter's declared fallback for a resettable profile field."""
    reset = row.get('reset')
    if (not isinstance(reset, dict) or row.get('read_only') or row.get('credential') or
            row.get('kind') == 'protected-file' or name.startswith(('auth.', 'signing.', 'testing.'))):
        return None
    if (type(reset.get('overridden')) is not bool or 'value' not in reset or
            type(reset['value']) is not type(row.get('value')) or
            not isinstance(reset.get('origin'), str) or not reset['origin'].strip()):
        return None
    return reset


def validate_settings_resets(rows, values, resets):
    if not isinstance(resets, (list, tuple)) or any(not isinstance(name, str) for name in resets):
        raise ValueError('Settings resets must name individual fields.')
    if len(set(resets)) != len(resets) or set(resets).intersection(values):
        raise ValueError('Supply one edit or reset per settings field.')
    for name in resets:
        if name not in rows or setting_reset(name, rows[name]) is None:
            raise ValueError('Settings field does not support reset: ' + name)


def reference_status(path):
    if not path:return 'missing'
    return 'configured (not verified)' if Path(path).expanduser().is_file() else 'missing reference'


def validate_account(provider, reference, kind):
    if not all(isinstance(value, str) for value in (provider, reference, kind)):
        raise ValueError('Account references need a provider, kind and text reference.')
    if provider not in {'github','firebase','testflight'}:
        raise ValueError('Unsupported account reference provider.')
    if kind not in {'protected-file','credential-helper','environment-name','firebase-cli'}:
        raise ValueError('Unsupported credential reference kind.')
    if kind=='environment-name' and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',reference):
        raise ValueError('Enter an environment variable name, never its token value.')
    reject_secrets(reference)
    if kind=='protected-file':
        resolve_external_credential_path(reference)


def normalize_and_validate_shared_settings(values, path):
    reject_secrets(values)
    for section in ('accounts', 'machines', 'projects'):
        if not isinstance(values.setdefault(section, {}), dict):
            raise ValueError(f'Expected an object for {section} in {path}.')
    for row in values['accounts'].values():
        if not isinstance(row, dict):
            raise ValueError(f'Invalid account reference in {path}.')
        validate_account(row.get('provider'), row.get('reference'), row.get('kind'))
    for project in values['projects'].values():
        if not isinstance(project, dict) or not isinstance(project.get('accounts', {}), dict):
            raise ValueError(f'Invalid project account binding in {path}.')


class SettingsStore:
    def __init__(self,directory=None):
        self.directory=Path(directory) if directory else config_directory()
        self.path=self.directory/'configuration'/'shared-settings.json'

    def read(self):
        ensure_configuration(self.directory)
        if not self.path.is_file():
            raise ValueError('Missing shared-settings.json; restore the configuration backup.')
        values=load_profile(self.path)
        normalize_and_validate_shared_settings(values, self.path)
        return values

    @contextmanager
    def _edit(self):
        ensure_configuration(self.directory)
        with workspace_lock(self.directory/'settings.lock', timeout=5):
            values = self.read()
            yield values
            normalize_and_validate_shared_settings(values, self.path)
            save_profile(self.path, values, allowed={'accounts','machines','projects','migrations'})

    def save(self,values):
        with self._edit() as current:
            current.clear()
            current.update(values)

    def save_account_reference(self,key,*,provider,reference,kind):
        validate_account(provider, reference, kind)
        with self._edit() as values:
            values['accounts'][key]=dict(provider=provider,reference=reference,kind=kind,status='configured; not verified')

    def bind_project_account(self,project,account_key):
        with self._edit() as values:
            account=values['accounts'][account_key]
            selected=values['projects'].setdefault(project,{}).setdefault('accounts',{})
            selected[account['provider']]=account_key

    account = save_account_reference

    def select_account(self, project, key):
        """Compatibility entry point for existing settings callers."""
        return self.bind_project_account(project, key)

    def account_defaults(self,project,fields):
        values=self.read();selected=values['projects'].get(project,{}).get('accounts',{})
        defaults={}
        for provider,key in selected.items():
            row=values['accounts'].get(key)
            if row and row['provider'] == provider and provider in fields:
                field=fields[provider]
                if isinstance(field,dict):
                    if set(field)!={'reference','kind'} or any(not name.startswith('auth.') for name in field.values()):
                        raise ValueError('Account mappings may supply protected reference fields only.')
                    defaults[field['reference']]=row['reference'];defaults[field['kind']]=row['kind']
                    continue
                if not field.startswith('auth.'):
                    raise ValueError('Account field mappings may supply protected auth references only.')
                if row['kind']=='protected-file':defaults[field]=row['reference']
        return defaults

    def migrate(self,legacy,project,validate):
        """Import once; caller changes its explicit authority only after validation.

        The original remains untouched. The migration receipt rejects a changed
        legacy source rather than merging two writable authorities implicitly.
        """
        legacy=Path(legacy)
        raw=legacy.read_bytes();digest=hashlib.sha256(raw).hexdigest()
        with self._edit() as values:
            migrations=values.setdefault('migrations',{})
            previous=migrations.get(project)
            if previous:
                if previous['sha256']!=digest:
                    raise ValueError('Legacy settings changed after import; resolve authority explicitly.')
                return values['projects'][project]
            imported=load_profile(legacy)
            reject_secrets(imported);validate(imported)
            values['projects'].setdefault(project,{}).update(values=imported,origin='explicit legacy import')
            migrations[project]=dict(sha256=digest,source=str(legacy),authority='legacy until explicitly selected')
            return values['projects'][project]
