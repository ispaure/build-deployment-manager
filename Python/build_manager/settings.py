"""Versioned non-secret settings layers and explicit legacy migration."""
from dataclasses import dataclass
import hashlib
import os
import re
from pathlib import Path

from .locking import workspace_lock
from .profiles import load_profile, save_profile
from .registry import config_directory
from .credentials import reject_secrets, protected_reference


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


def reference_status(path):
    if not path:return 'missing'
    return 'configured (not verified)' if Path(path).expanduser().is_file() else 'missing reference'


class SettingsStore:
    def __init__(self,directory=None):
        self.directory=Path(directory) if directory else config_directory()
        self.path=self.directory/'settings.json'

    def read(self):
        values=load_profile(self.path)
        values.setdefault('accounts',{})
        values.setdefault('machines',{})
        values.setdefault('projects',{})
        return values

    def save(self,values):
        reject_secrets(values)
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        if os.name!='nt':self.directory.chmod(0o700)
        with workspace_lock(self.directory/'settings.lock'):
            load_profile(self.path) # Unknown schemas cannot be overwritten.
            save_profile(self.path,values,allowed={'accounts','machines','projects','migrations'})

    def account(self,key,*,provider,reference,kind):
        if provider not in {'github','firebase','testflight'}:
            raise ValueError('Unsupported account reference provider.')
        if kind not in {'protected-file','credential-helper','environment-name','firebase-cli'}:
            raise ValueError('Unsupported credential reference kind.')
        if kind=='environment-name' and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',reference):
            raise ValueError('Enter an environment variable name, never its token value.')
        reject_secrets(reference)
        if kind=='protected-file':
            protected_reference(reference)
        values=self.read()
        values['accounts'][key]=dict(provider=provider,reference=reference,kind=kind,status='configured; not verified')
        self.save(values)

    def select_account(self,project,key):
        values=self.read();account=values['accounts'][key]
        selected=values['projects'].setdefault(project,{}).setdefault('accounts',{})
        selected[account['provider']]=key;self.save(values)

    def account_defaults(self,project,fields):
        values=self.read();selected=values['projects'].get(project,{}).get('accounts',{})
        defaults={}
        for provider,key in selected.items():
            row=values['accounts'].get(key)
            if row and provider in fields:
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
        values=self.read();migrations=values.setdefault('migrations',{})
        previous=migrations.get(project)
        if previous:
            if previous['sha256']!=digest:
                raise ValueError('Legacy settings changed after import; resolve authority explicitly.')
            return values['projects'][project]
        imported=load_profile(legacy)
        reject_secrets(imported);validate(imported)
        values['projects'].setdefault(project,{}).update(values=imported,origin='explicit legacy import')
        migrations[project]=dict(sha256=digest,source=str(legacy),authority='legacy until explicitly selected')
        self.save(values)
        return values['projects'][project]
