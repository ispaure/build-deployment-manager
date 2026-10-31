"""Declarative local commands; source membership and commands remain project policy."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
from uuid import uuid4

from .models import Phase, Plan


def relative(value):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value
            or '\x00' in value or PurePosixPath(value).is_absolute()
            or '..' in PurePosixPath(value).parts):
        raise ValueError('Use a checkout-relative POSIX path without parent traversal.')
    return value


def normalize(descriptor):
    """Derive capabilities from one operation catalog; never execute project code."""
    if not all(isinstance(descriptor.get(k), str) and descriptor[k] for k in ('name', 'project_id')):
        raise ValueError('Declare a nonempty project name and ID.')
    relative(descriptor.get('results', 'test-results/build-manager'))
    spec = descriptor['commands']
    if not isinstance(spec, dict) or set(spec) != {'source', 'operations'}:
        raise ValueError('Commands require source and operations.')
    if not isinstance(spec['source'], list):
        raise ValueError('Command source must be an explicit list of files/directories.')
    for name in spec['source']:
        relative(name)
        if name == '.' or any(p in {'.git', '.venv', 'test-results', '__pycache__'} for p in PurePosixPath(name).parts):
            raise ValueError('Select public source explicitly, excluding environments and generated outputs.')
    operations = spec['operations']
    if not isinstance(operations, dict) or not operations:
        raise ValueError('Declare at least one command operation.')
    for name, rows in operations.items():
        if not isinstance(name, str) or not name or not isinstance(rows, list) or not rows:
            raise ValueError('Each named operation needs steps.')
        phases = []
        for row in rows:
            allowed = {'id', 'argv', 'effect', 'dependencies', 'timeout', 'artifacts', 'artifact_types', 'cwd', 'environment'}
            if not isinstance(row, dict) or set(row) - allowed:
                raise ValueError('Unsupported command step field.')
            if not isinstance(row.get('effect'), str) or row.get('effect') not in {'test', 'build', 'inspect'}:
                raise ValueError('Command projects support explicit test/build/inspect effects; delivery needs an adapter.')
            if not isinstance(row.get('argv'), list):
                raise ValueError('Commands use argument arrays, never shell strings.')
            environment = row.get('environment', {})
            if not isinstance(environment, dict) or any(not isinstance(k, str) or not k or not isinstance(v, str) for k, v in environment.items()):
                raise ValueError('Command environment must map names to text values.')
            if not isinstance(row.get('artifacts', []), list) or not isinstance(row.get('artifact_types', {}), dict):
                raise ValueError('Artifacts must be a list with an optional type mapping.')
            if not isinstance(row.get('dependencies', []), list) or any(not isinstance(v, str) for v in row.get('dependencies', [])):
                raise ValueError('Dependencies must be a list of step IDs.')
            if type(row.get('timeout', 600)) not in (int, float):
                raise ValueError('Command timeout must be a number.')
            if not isinstance(row.get('id'), str):
                raise ValueError('Command steps require an ID.')
            relative(row.get('cwd', '.'))
            for path in row.get('artifacts', []):
                relative(path)
            if any(v not in ('file', 'junit') for v in row.get('artifact_types', {}).values()):
                raise ValueError('Command artifact types must be file or junit.')
            if set(row.get('artifact_types', {})) - set(row.get('artifacts', [])):
                raise ValueError('Artifact types must name declared artifacts.')
            phases.append(Phase(**dict(row, cwd=row.get('cwd', '.'))))
        Plan(descriptor['name'], name, {}, tuple(phases), 'workspace')
    from .credentials import reject_secrets
    reject_secrets(spec)
    if any(key in descriptor for key in ('bridge', 'interpreter', 'journey', 'test_suites', 'run_fields')):
        raise ValueError('Command projects cannot also declare a custom adapter or selectable suites/fields.')
    expected = dict(platforms=['host'], operations=list(operations), backends={'host': ['Local']})
    if 'capabilities' in descriptor and descriptor['capabilities'] != expected:
        raise ValueError('Command capabilities are derived from operations; remove conflicting capabilities.')
    return dict(descriptor, capabilities=expected)


def inventory(root, names, *, public_only=True):
    """Reject links and escapes before creating a workspace, including linked parents."""
    root = Path(root).resolve()
    files = {}
    for name in names:
        relative(name)
        path = root / name
        candidates = [path, *path.rglob('*')] if path.is_dir() and not path.is_symlink() else [path]
        for item in candidates:
            if any(p.is_symlink() for p in (item, *item.parents) if p != root and root in p.parents):
                raise ValueError('Source cannot contain symbolic links: ' + str(item))
            if not item.resolve().is_relative_to(root):
                raise ValueError('Source escapes project.')
            if not item.exists():
                raise ValueError('Declared source is missing: ' + name)
            if item.is_file():
                rel = item.relative_to(root).as_posix()
                if public_only and any(p in {'.git', '.venv', 'test-results', '__pycache__'} for p in item.relative_to(root).parts):
                    raise ValueError('Declared source contains private/runtime/generated directories: ' + rel)
                files[rel] = item
            elif not item.is_dir():
                raise ValueError('Source must contain ordinary files and directories.')
    return files


def make_plan(root, descriptor, values, cancelled=lambda: False):
    allowed = {'operation', 'target', 'backend', 'revision', 'suite', 'pattern', 'release_tag', 'run_overrides', 'build_override'}
    if (set(values) - allowed or values.get('revision', 'working-tree') != 'working-tree'
            or any(values.get(k) for k in ('suite', 'pattern', 'release_tag', 'run_overrides', 'build_override'))):
        raise ValueError('Command projects support complete working-tree operations only.')
    operation = values.get('operation')
    if (values.get('target') != 'host' or values.get('backend') != 'Local'
            or operation not in descriptor['commands']['operations']):
        raise ValueError('Unsupported command operation/target/backend.')
    root = Path(root).resolve()
    files = inventory(root, descriptor['commands']['source'])
    output_root = root / relative(descriptor.get('results', 'test-results/build-manager'))
    if not output_root.resolve().is_relative_to(root) or any(p.is_symlink() for p in (output_root, *output_root.parents) if root in p.parents):
        raise ValueError('Results must remain inside the project without links.')
    workspace = output_root / ('prepared-' + uuid4().hex)
    snapshot, output = workspace / 'source', workspace / 'artifacts'
    snapshot.mkdir(parents=True)
    output.mkdir()
    try:
        hashes = {}
        for name, path in files.items():
            if cancelled():
                raise ValueError('Project request cancelled.')
            # Recheck immediately before copying; snapshot hashes describe copied bytes.
            inventory(root, [name])
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            from commonUtils.runtime.streams import file_sha256
            hashes[name] = file_sha256(target)
        def expand(text):
            return text.replace('{source}', str(snapshot)).replace('{output}', str(output)).replace('{project}', str(root))
        phases = []
        for row in descriptor['commands']['operations'][operation]:
            cwd = snapshot / row.get('cwd', '.')
            if not cwd.is_dir():
                raise ValueError('Command working directory is absent from captured source.')
            artifacts = tuple(str(output / p) for p in row.get('artifacts', []))
            phases.append(Phase(**dict(row, argv=tuple(expand(v) for v in row['argv']), cwd=str(cwd),
                environment={'PYTHONPATH': '', 'PYTHONHOME': '', **{k: expand(v) for k, v in row.get('environment', {}).items()}},
                artifacts=artifacts, artifact_types={str(output / k): v for k, v in row.get('artifact_types', {}).items()})))
        return Plan(descriptor['name'], operation, {'files_sha256': hashes, 'selection': 'captured working-tree',
            'commands_sha256': hashlib.sha256(json.dumps(descriptor['commands'], sort_keys=True).encode()).hexdigest()},
            tuple(phases), str(workspace), backend='Local', effect='build' if any(p.effect == 'build' for p in phases) else 'test')
    except BaseException:
        shutil.rmtree(workspace)
        raise


def call(root, descriptor, action, values, cancelled=lambda: False):
    if cancelled():
        raise ValueError('Project request cancelled.')
    if action == 'plan':
        return make_plan(root, descriptor, values, cancelled).data()
    if action in {'settings', 'run_defaults', 'run_choices'}:
        return {}
    if action == 'save_settings' and not values.get('changes'):
        return {}
    raise ValueError('Command project does not support action: ' + action)
