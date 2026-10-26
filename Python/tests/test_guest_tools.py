"""Portable bootstrap contracts; no VM start or public tool download."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import call, patch

from build_manager.guest_tools import (
    LINUX_BOOTSTRAP, WINDOWS_PREPARE, linux_parameters, windows_parameters,
)


class GuestToolsTests(unittest.TestCase):
    def test_linux_bootstrap_uses_caller_pins_and_owned_environment(self):
        for python, uv in [('3.12.2', '0.12.18'), ('3.13.7', '0.11.1')]:
            with self.subTest(python=python), patch.object(subprocess, 'run') as run, \
                    patch.object(sys, 'argv', ['bootstrap', '/owned workspace', json.dumps(
                        linux_parameters(python=python, uv_version=uv))]):
                exec(compile(LINUX_BOOTSTRAP, '<guest-bootstrap>', 'exec'), {})
            bootstrap = Path('/owned workspace/bootstrap')
            environment = Path('/owned workspace/environment')
            self.assertEqual(run.call_args_list, [
                call([sys.executable, '-m', 'venv', str(bootstrap)], check=True, timeout=120),
                call([str(bootstrap / 'bin/python'), '-m', 'pip', 'install', 'uv==' + uv], check=True, timeout=300),
                call([str(bootstrap / 'bin/python'), '-m', 'uv', 'venv', '--python', python,
                      '--seed', str(environment)], check=True, timeout=600),
            ])

    def test_bootstrap_failure_stops_before_later_steps(self):
        with patch.object(subprocess, 'run', side_effect=subprocess.CalledProcessError(7, 'venv')) as run, \
                patch.object(sys, 'argv', ['bootstrap', '/owned', json.dumps(
                    linux_parameters(python='3.12.2', uv_version='0.12.18'))]):
            with self.assertRaises(subprocess.CalledProcessError):
                exec(compile(LINUX_BOOTSTRAP, '<guest-bootstrap>', 'exec'), {})
        self.assertEqual(run.call_count, 1)

    def test_windows_parameters_are_catalog_data_not_generated_shell(self):
        tools = {name: dict(url='https://github.com/example/tools/' + name + '.zip', sha256='a' * 64)
                 for name in ('uv', 'git')}
        options = dict(python='cpython-3.13.7-windows-x86_64', guest_architecture='ARM64', python_architecture='x86_64')
        values = windows_parameters('b' * 32, tools, **options)
        self.assertEqual(values, dict(token='b' * 32, tools=tools, **options))
        self.assertEqual(json.loads(json.dumps(values)), values)
        self.assertNotIn(options['python'], WINDOWS_PREPARE)
        self.assertIn('venv --python $p.python', WINDOWS_PREPARE)
        self.assertIn('$env:UV_PYTHON_ARCH=$p.python_architecture', WINDOWS_PREPARE)
        self.assertIn('$env:PROCESSOR_ARCHITECTURE -ne $p.guest_architecture', WINDOWS_PREPARE)
        self.assertIn('Get-FileHash -LiteralPath $zip -Algorithm SHA256', WINDOWS_PREPARE)
        self.assertIn('.manager-owned.json', WINDOWS_PREPARE)
        self.assertIn("throw 'Owned workspace already exists; inspect it before retry.'", WINDOWS_PREPARE)

    def test_bad_catalogs_and_selectors_are_rejected_before_transport(self):
        tools = {name: dict(url='https://github.com/example/tools/' + name + '.zip', sha256='a' * 64)
                 for name in ('uv', 'git')}
        options = dict(python='3.12.2', guest_architecture='ARM64', python_architecture='x86_64')
        for url, digest in [('http://github.com/tools.zip', 'a' * 64),
                            ('https://github.com.evil.invalid/tools.zip', 'a' * 64),
                            ('https://user:password@github.com/tools.zip', 'a' * 64),
                            ('https://github.com/tools.zip', 'bad')]:
            broken = copy.deepcopy(tools)
            broken['uv'].update(url=url, sha256=digest)
            with self.subTest(url=url), self.assertRaises(ValueError):
                windows_parameters('b' * 32, broken, **options)
        with self.assertRaises(ValueError):
            windows_parameters('../escape', tools, **options)
        with self.assertRaises(ValueError):
            windows_parameters('b' * 32, tools, **dict(options, python='3.12; command'))
        with self.assertRaises(ValueError):
            linux_parameters(python='3.12.2', uv_version='0.12 --extra-index-url example')
