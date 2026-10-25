"""Trusted adapters run in project processes, never in the manager interpreter."""
import json
import os
from pathlib import Path
import subprocess
import sys

from .models import Plan
from .redaction import Redactor


class ProjectBridge:
    def __init__(self, registry, key=None):
        self.registry, self.key = registry, key
        self.row, self.descriptor = registry.resolve(key)
        self.root = Path(self.row['root'])
        capabilities = self.descriptor['capabilities']
        self.platforms = tuple(capabilities['platforms'])
        self.operations = tuple(capabilities['operations'])
        self.description = f"{self.descriptor['name']} · {self.root} · source/destination shown in each plan"
        self.runner_directory = Path(__file__).resolve().parents[2]
        self.interpreter = sys.executable
        self.results_directory = self.root / self.descriptor.get('results', 'test-results/build-manager')
        if not self.results_directory.resolve().is_relative_to(self.root):
            raise ValueError('Result storage must remain project-owned.')
        self.run_options = self.descriptor.get('run_options', {})
        self.workflow_presets = self.descriptor.get('presets', {})

    def operations_for(self, target):
        return tuple(self.descriptor['capabilities'].get('operations_by_target', {}).get(target, self.operations))

    def backend_options(self, target, operation='Test'):
        capabilities = self.descriptor['capabilities']
        backends = capabilities.get('host_backends', {}).get(sys.platform, capabilities.get('backends', {}))
        options = backends.get(target, ('Local',))
        if isinstance(options, dict):options = options.get(operation, ())
        return tuple(options)

    def call(self, action, **values):
        row, descriptor = self.registry.resolve(self.key, trusted=True)
        if row['root'] != str(self.root) or descriptor != self.descriptor:
            raise ValueError('Adapter registration changed; select this project again.')
        interpreter = descriptor['interpreter']
        if isinstance(interpreter, dict):
            interpreter = interpreter[sys.platform]
        python = self.root / interpreter
        script = self.root / descriptor['bridge']
        if not python.is_file():
            raise ValueError('Project interpreter is missing; set up its own environment before running.')
        if not script.is_file():
            raise ValueError('Adapter bridge is missing; initialize the project dependencies.')
        environment = dict(os.environ)
        for key in ('PYTHONPATH', 'PYTHONHOME'):
            environment.pop(key, None)
        from .settings import SettingsStore
        account_defaults = SettingsStore(self.registry.directory).account_defaults(
            descriptor['project_id'], descriptor.get('account_fields', {}))
        result = subprocess.run([str(python), str(script)], cwd=self.root,
            input=json.dumps(dict(schema=1, action=action, values=values, account_defaults=account_defaults)), text=True,
            capture_output=True, timeout=300, env=environment)
        redact = Redactor(environment.get(name) for name in ('GH_TOKEN','GITHUB_TOKEN','FIREBASE_TOKEN'))
        if result.returncode:
            raise ValueError(redact(result.stderr[-3000:] or 'Project bridge failed.'))
        data = json.loads(result.stdout)
        if data.get('schema') != 1 or 'result' not in data:
            raise ValueError('Unsupported adapter response.')
        return data['result']

    def make_plan(self, operation, target, backend, **values):
        if operation not in self.operations_for(target) or target not in self.platforms or backend not in self.backend_options(target, operation):
            raise ValueError('Unsupported project operation, platform or backend.')
        from dataclasses import replace
        plan = Plan.from_data(self.call('plan', operation=operation, target=target, backend=backend, **values))
        return replace(plan, adapter=dict(api=1,project_id=self.descriptor['project_id'],
            descriptor_sha256=self.row['descriptor'],checkout=str(self.root)))

    def settings_view(self):
        from .providers import settings_rows
        return dict(self.call('settings'), **settings_rows(self.platforms))

    def save_settings(self, values):
        return self.call('save_settings', changes=values)

    def verification_plan(self):
        return Plan.from_data(self.call('verification'))
