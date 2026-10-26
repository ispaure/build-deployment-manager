"""Declarative project-owned test inventory; discovery never imports project code."""
import json
from pathlib import Path
import re
import subprocess

from .models import Phase

MANIFEST = 'build-tests.json'


def _inside(root, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError('Test paths must be relative to their owning checkout.')
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_dir():
        raise ValueError('Test directory is missing or escapes its owning checkout: ' + value)
    return path


def discover(root, group):
    """Resolve a selected group's transitive prerequisites in stable execution order.

    Consumers explicitly opt dependency suites into their policy. Dependency owners
    must be tracked gitlinks within this checkout; siblings and symlink escapes are
    never searched. The adapter remains responsible for its captured source pin.
    """
    root = Path(root).resolve()
    path = root / MANIFEST
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
        raise ValueError('Test manifest must be a bounded regular checkout file.')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('schema') != 1 or not isinstance(data.get('suites'), list):
        raise ValueError('Expected test manifest schema 1 with suites.')
    rows = {}
    for original in data['suites']:
        if not isinstance(original, dict):
            raise ValueError('Test suite must be an object.')
        row = dict(original)
        key = row.get('id')
        if not isinstance(key, str) or not re.fullmatch(r'[a-zA-Z0-9][\w.-]*', key) or key in rows:
            raise ValueError('Test suite IDs must be stable and unique.')
        for field in ('groups', 'after'):
            values = row.get(field, [])
            if not isinstance(values, list) or any(not isinstance(v, str) or not v for v in values):
                raise ValueError('Test suite ' + field + ' must be a list of names.')
            row[field] = values
        owner = root
        if row.get('owner', '.') != '.':
            owner = _inside(root, row['owner'])
            relative = owner.relative_to(root).as_posix()
            result = subprocess.run(['git', '-C', str(root), 'ls-files', '--stage', '--', relative],
                                    capture_output=True, text=True, check=True, timeout=10)
            pins = [line.split()[1] for line in result.stdout.splitlines()
                    if line.startswith('160000 ') and line.split('\t')[-1] == relative]
            if len(pins) != 1:
                raise ValueError('Dependency tests must belong to a pinned Git submodule: ' + relative)
            actual = subprocess.run(['git', '-C', str(owner), 'rev-parse', '--show-toplevel', 'HEAD'],
                                    capture_output=True, text=True, check=True, timeout=10).stdout.splitlines()
            if len(actual) != 2 or Path(actual[0]).resolve() != owner or actual[1] != pins[0]:
                raise ValueError('Initialize the dependency at its pinned commit before testing: ' + relative)
        directory = row.get('directory')
        if directory is None:
            candidates = [name for name in ('Python/tests', 'tests') if (owner / name).is_dir()]
            if len(candidates) != 1:
                raise ValueError('Declare a test directory when conventional roots are missing or ambiguous.')
            directory = candidates[0]
        row['directory'] = _inside(owner, directory).relative_to(root).as_posix()
        timeout = row.get('timeout', 900)
        if type(timeout) is not int or timeout <= 0:
            raise ValueError('Test timeout must be positive seconds.')
        row['timeout'] = timeout
        interpreter = row.get('interpreter', 'project')
        if not isinstance(interpreter, str) or not interpreter:
            raise ValueError('Test interpreter must name an adapter-owned environment.')
        row['interpreter'] = interpreter
        rows[key] = row
    ordered, visiting, visited = [], set(), set()
    def visit(key):
        if key not in rows:
            raise ValueError('Unknown test prerequisite: ' + key)
        if key in visiting:
            raise ValueError('Cyclic test prerequisites: ' + key)
        if key in visited:
            return
        visiting.add(key)
        for dependency in rows[key]['after']:
            visit(dependency)
        visiting.remove(key); visited.add(key); ordered.append(rows[key])
    # Validate the entire manifest, even if a broken suite is not selected today.
    for key in rows:
        visit(key)
    ordered.clear(); visited.clear()
    for key, row in rows.items():
        if group in row['groups']:
            visit(key)
    if not ordered:
        raise ValueError('No test suites declared for group: ' + group)
    return ordered


def phases(root, group, interpreters, runner, *, environment=None):
    """Use the project's isolated runner and explicit interpreters; install nothing."""
    root = Path(root).resolve()
    if (not isinstance(runner, (list, tuple)) or not runner
            or any(not isinstance(arg, str) or not arg for arg in runner)
            or runner.count('{directory}') != 1):
        raise ValueError('Declare runner arguments with exactly one {directory} argument.')
    rows = discover(root, group)
    result = []
    for row in rows:
        interpreter = interpreters.get(row['interpreter'])
        if not interpreter:
            raise ValueError('Configure the test interpreter: ' + row['interpreter'])
        result.append(Phase(row['id'], (str(interpreter), *(row['directory'] if arg == '{directory}' else arg for arg in runner)),
            str(root), timeout=row['timeout'], dependencies=tuple(row['after']),
            environment=dict(environment or {}), effect='test'))
    return tuple(result)
