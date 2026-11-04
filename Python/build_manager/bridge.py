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
        self.registry, self.key = registry, registry.project_key(key)
        self.row, self.descriptor = registry.resolve(self.key)
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
        from .journeys import resolve_host_backends
        self.journey_capability = resolve_host_backends(self.descriptor.get('journey'))

    def supports_action(self, action):
        if 'commands' in self.descriptor:
            return action in {'plan', 'settings', 'save_settings', 'run_defaults', 'run_choices'}
        declared = self.descriptor.get('adapter_actions')
        return action in declared if declared is not None else action in {'plan', 'settings', 'save_settings', 'verification'}

    def storage_inventory(self):
        if not self.supports_action('storage_inventory'):
            raise ValueError('This adapter does not declare storage inventory.')
        return self.call('storage_inventory', timeout=600)

    def delete_storage(self, selections):
        if not self.supports_action('delete_storage'):
            raise ValueError('This adapter does not declare storage deletion.')
        return self.call('delete_storage', selections=selections, timeout=600)

    def enroll_storage(self, kind, location):
        return self.call('enroll_storage', kind=kind, location=location, timeout=60)

    def operations_for(self, target):
        from .adapter_sdk import operations_for
        return operations_for(self.descriptor, target)

    def backend_options(self, target, operation='Test'):
        from .adapter_sdk import backend_options
        return backend_options(self.descriptor, target, operation)

    def call(self, action, *, cancelled=lambda: False, timeout=300, **values):
        row, descriptor = self.registry.resolve(self.key, trusted=True)
        if row['root'] != str(self.root) or descriptor != self.descriptor:
            raise ValueError('Adapter registration changed; select this project again.')
        if 'commands' in descriptor:
            from .command_project import call
            return call(self.root, descriptor, action, values, cancelled)
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
        payload = json.dumps(dict(schema=1, action=action, values=values, account_defaults=account_defaults,
            settings_profile=str(self.registry.path.parent / row['name'] / 'profile.json'),
            manager_checkout=str(self.runner_directory)))
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
        context = f"{descriptor['name']} adapter action {action!r} ({script})"
        if process.returncode:
            raise ValueError(redact(f'{context} exited with code {process.returncode}: '
                                    + (stderr[-3000:] or 'No diagnostic output.')))
        try:
            data = json.loads(stdout)
        except ValueError as error:
            # Do not echo stdout: it can contain private settings. Diagnostics
            # belong on stderr; stdout must contain one protocol object.
            raise ValueError(f'{context} returned invalid JSON. '
                             'Write diagnostics to stderr and one schema-1 response to stdout.') from error
        if not isinstance(data, dict) or data.get('schema') != 1 or 'result' not in data:
            raise ValueError(f'{context} returned an unsupported adapter response. '
                             'Expected an object with schema=1 and result.')
        return data['result']

    def make_plan(self, operation, target, backend, **values):
        platform = target  # API-1 adapter requests use the target key.
        self.normalize_run_overrides(values)
        if operation not in self.operations_for(platform) or platform not in self.platforms or backend not in self.backend_options(platform, operation):
            raise ValueError('Unsupported project operation, platform or backend.')
        suite = values.get('suite')
        if suite and not any(row['id'] == suite and platform in row['platforms']
                             and operation in row['operations'] for row in self.test_suites):
            raise ValueError('Unsupported test suite for this operation and platform.')
        from dataclasses import replace
        plan = Plan.from_data(self.call('plan', operation=operation, target=platform, backend=backend, timeout=600, **values))
        identity = dict(api=1, project_id=self.descriptor['project_id'],
                        descriptor_sha256=self.row['descriptor'], checkout=str(self.root), platform=platform)
        if suite:
            identity['test_suite'] = suite
        return replace(plan, adapter=identity)

    def settings_view(self):
        return self.load_settings(timeout=300)

    def make_journey(self, goal, platforms, destinations, **options):
        from dataclasses import replace
        from .journeys import build_journey_intent, validate_plan
        self.normalize_run_overrides(options)
        backends = options.pop('backends', None)
        intent = build_journey_intent(self.journey_capability, goal, platforms, destinations, backends=backends)
        for platform in platforms:
            row = self.journey_capability['platforms'][platform]
            backend = (backends or {}).get(platform, row['backend'])
            if backend not in self.backend_options(platform, row['operation']):
                raise ValueError(platform + ': configured execution host is unavailable. Open test-machine setup.')
        plan = Plan.from_data(self.call('journey_plan', intent=intent, timeout=600, **options))
        validate_plan(plan, intent)
        if plan.project != self.descriptor['name']:
            raise ValueError('Prepared journey belongs to a different project.')
        return replace(plan, adapter=dict(api=1, project_id=self.descriptor['project_id'],
            descriptor_sha256=self.row['descriptor'], checkout=str(self.root)))

    def normalize_run_overrides(self, options):
        if 'run_overrides' in options:
            from .run_fields import validate_overrides
            options['run_overrides'] = validate_overrides(self.run_fields, options['run_overrides'])

    def run_defaults(self, *, cancelled=lambda: False):
        if self.descriptor.get('dynamic_run_inputs') is True:
            return self.call('run_defaults', cancelled=cancelled, timeout=30)
        rows = self.load_settings(cancelled=cancelled)
        return {field['id']:rows[field['id']]['value'] for field in self.run_fields if field['id'] in rows}

    def run_choices(self, *, cancelled=lambda: False):
        if not any(row.get('kind') == 'multiselect' for row in self.run_fields):
            return {}
        from .device_catalog import recipient_platforms_by_field, merge_recipient_choices
        rows = self.call('run_choices', cancelled=cancelled, timeout=30)
        fields = recipient_platforms_by_field(self.descriptor)
        return merge_recipient_choices(self.registry.directory, fields, rows) if fields else rows

    def set_app_version(self, value):
        """Explicit tracked-source edit; version policy stays with the adapter."""
        if not isinstance(value, str) or not value or len(value) > 100:
            raise ValueError('Supply a project app version.')
        return self.call('set_app_version', version=value, timeout=30)

    def store_settings(self, values, *, cancelled=lambda: False):
        return self.save_settings(values, cancelled=cancelled)

    def load_settings(self, *, cancelled=lambda: False, timeout=30):
        from .providers import unimplemented_distribution_rows
        return dict(self.call('settings', cancelled=cancelled, timeout=timeout), **unimplemented_distribution_rows(self.platforms))

    def save_settings(self, values, *, cancelled=lambda: False):
        from .credentials import reject_secrets, validate_settings_changes
        reject_secrets(values)
        # Validate against the declared schema before invoking the writer.
        rows = self.load_settings(cancelled=cancelled)
        validate_settings_changes(rows, values, self.root)
        return self.call('save_settings', changes=values, cancelled=cancelled, timeout=30)

    def verification_plan(self):
        return Plan.from_data(self.call('verification'))
