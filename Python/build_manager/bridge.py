"""Trusted adapters run in project processes, never in the manager interpreter."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

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
        self.test_suites = self.descriptor.get('test_suites', [])
        self.run_fields = self.descriptor.get('run_fields', [])
        from .journeys import for_host
        self.journey_capability = for_host(self.descriptor.get('journey'))

    def operations_for(self, target):
        return tuple(self.descriptor['capabilities'].get('operations_by_target', {}).get(target, self.operations))

    def backend_options(self, target, operation='Test'):
        capabilities = self.descriptor['capabilities']
        backends = capabilities.get('host_backends', {}).get(sys.platform, capabilities.get('backends', {}))
        options = backends.get(target, ('Local',))
        if isinstance(options, dict):options = options.get(operation, ())
        return tuple(options)

    def call(self, action, *, cancelled=lambda: False, timeout=300, **values):
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
        payload = json.dumps(dict(schema=1, action=action, values=values, account_defaults=account_defaults))
        from .credentials import reject_secrets
        reject_secrets(values)
        if cancelled():
            raise ValueError('Project request cancelled.')
        with subprocess.Popen([str(python), str(script)], cwd=self.root, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment) as process:
            deadline = time.monotonic() + timeout
            try:
                while True:
                    if cancelled():
                        raise ValueError('Project request cancelled.')
                    if time.monotonic() >= deadline:
                        raise ValueError('Project request timed out. Check the project interpreter and adapter.')
                    try:
                        stdout, stderr = process.communicate(payload, timeout=.1)
                        break
                    except subprocess.TimeoutExpired:
                        payload = None
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        redact = Redactor(environment.get(name) for name in ('GH_TOKEN','GITHUB_TOKEN','FIREBASE_TOKEN'))
        if process.returncode:
            raise ValueError(redact(stderr[-3000:] or 'Project bridge failed.'))
        data = json.loads(stdout)
        if data.get('schema') != 1 or 'result' not in data:
            raise ValueError('Unsupported adapter response.')
        return data['result']

    def make_plan(self, operation, target, backend, **values):
        self.check_run_overrides(values)
        if operation not in self.operations_for(target) or target not in self.platforms or backend not in self.backend_options(target, operation):
            raise ValueError('Unsupported project operation, platform or backend.')
        suite = values.get('suite')
        if suite and not any(row['id'] == suite and target in row['platforms']
                             and operation in row['operations'] for row in self.test_suites):
            raise ValueError('Unsupported test suite for this operation and platform.')
        from dataclasses import replace
        plan = Plan.from_data(self.call('plan', operation=operation, target=target, backend=backend, **values))
        identity = dict(api=1, project_id=self.descriptor['project_id'],
                        descriptor_sha256=self.row['descriptor'], checkout=str(self.root), platform=target)
        if suite:
            identity['test_suite'] = suite
        return replace(plan, adapter=identity)

    def settings_view(self):
        from .providers import settings_rows
        return dict(self.call('settings'), **settings_rows(self.platforms))

    def make_journey(self, goal, platforms, destinations, **options):
        from dataclasses import replace
        from .journeys import request, validate_plan
        self.check_run_overrides(options)
        backends = options.pop('backends', None)
        intent = request(self.journey_capability, goal, platforms, destinations, backends=backends)
        for target in platforms:
            row = self.journey_capability['platforms'][target]
            backend = (backends or {}).get(target, row['backend'])
            if backend not in self.backend_options(target, row['operation']):
                raise ValueError(target + ': configured execution host is unavailable. Open test-machine setup.')
        plan = Plan.from_data(self.call('journey_plan', intent=intent, **options))
        validate_plan(plan, intent)
        if plan.project != self.descriptor['name']:
            raise ValueError('Prepared journey belongs to a different project.')
        return replace(plan, adapter=dict(api=1, project_id=self.descriptor['project_id'],
            descriptor_sha256=self.row['descriptor'], checkout=str(self.root)))

    def check_run_overrides(self, options):
        if 'run_overrides' in options:
            from .run_fields import validate_overrides
            options['run_overrides'] = validate_overrides(self.run_fields, options['run_overrides'])

    def run_defaults(self, *, cancelled=lambda: False):
        rows = self.load_settings(cancelled=cancelled)
        return {field['id']:rows[field['id']]['value'] for field in self.run_fields if field['id'] in rows}

    def save_settings(self, values):
        return self.store_settings(values)

    def load_settings(self, *, cancelled=lambda: False):
        from .providers import settings_rows
        return dict(self.call('settings', cancelled=cancelled, timeout=30), **settings_rows(self.platforms))

    def store_settings(self, values, *, cancelled=lambda: False):
        from .credentials import reject_secrets, validate_settings_changes
        reject_secrets(values)
        # Validate against the declared schema before invoking the writer.
        rows = self.load_settings(cancelled=cancelled)
        validate_settings_changes(rows, values, self.root)
        return self.call('save_settings', changes=values, cancelled=cancelled, timeout=30)

    def verification_plan(self):
        return Plan.from_data(self.call('verification'))
