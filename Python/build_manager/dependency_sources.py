"""Exact committed manager/dependency transfer; callers own pins and scratch policy."""
import io
import hashlib
import json
import os
import shutil
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile

def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True, timeout=60).strip()


def verify(checkout, pin, *, pinned_source=False, working_tree=False):
    checkout = Path(checkout).resolve()
    if not isinstance(pin, str) or not re.fullmatch(r'[0-9a-f]{40}', pin):
        raise ValueError('Dependency pin must be a full Git commit.')
    if (not pinned_source or working_tree) and git(checkout, 'rev-parse', 'HEAD') != pin:
        raise ValueError('Explicit manager checkout does not match the project dependency pin.')
    try:
        if git(checkout, 'cat-file', '-t', pin) != 'commit':
            raise ValueError('Declared manager pin is not a commit.')
        shared = git(checkout, 'ls-tree', pin, 'Python/commonUtils').split()[2]
        git(checkout/'Python/commonUtils', 'cat-file', '-e', shared+'^{commit}')
    except (subprocess.CalledProcessError, IndexError) as error:
        raise ValueError('Explicit manager sources lack the declared project/dependency commits.') from error
    if not pinned_source and git(checkout/'Python/commonUtils', 'rev-parse', 'HEAD') != shared:
        raise ValueError('Manager commonUtils does not match its real pinned submodule.')
    for folder in (checkout, checkout/'Python/commonUtils'):
        if working_tree and folder == checkout:
            continue
        if git(folder, 'status', '--porcelain', '--untracked-files=no'):
            raise ValueError('Commit manager/dependency edits before guest transfer.')
    return pin, shared


def archive(checkout, pin, kind, workspace, *, working_tree=None):
    if kind not in {'zip', 'tar'}:
        raise ValueError('Choose zip or tar manager transfer.')
    checkout = Path(checkout).resolve()
    pin, shared = verify(checkout, pin, pinned_source=True, working_tree=bool(working_tree))
    stream = io.BytesIO()
    source = Path(workspace)/'manager'
    if source.exists():
        raise ValueError('Dependency transfer requires an unused scratch directory.')
    for target, origin, revision in ((source, checkout, pin),
            (source/'Python/commonUtils', checkout/'Python/commonUtils', shared)):
        target.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', 'init', '--quiet', str(target)], check=True, timeout=30)
        subprocess.run(['git', '-C', str(target), 'fetch', '--quiet', '--depth', '1', '--no-tags', origin.as_uri(), revision], check=True, timeout=120)
        subprocess.run(['git', '-C', str(target), 'checkout', '--quiet', '--detach', 'FETCH_HEAD'], check=True, timeout=60)
    if working_tree:
        manifest = local_test_identity(checkout, pin)
        if manifest['fingerprint'] != working_tree:
            raise ValueError('Local manager test source changed after planning.')
        for name, expected in manifest['files'].items():
            origin, target = checkout / name, source / name
            if expected is None:
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, target)
        if local_test_identity(checkout, pin) != manifest:
            raise ValueError('Local manager test source changed during capture.')
        (source / LOCAL_TEST_MANIFEST).write_text(json.dumps(manifest, sort_keys=True) + '\n')
        verify_local_test_source(source, pin, working_tree)
    if kind == 'zip':
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as output:
            for path in sorted(source.rglob('*')):
                output.write(path, path.relative_to(source).as_posix())
    elif kind == 'tar':
        with tarfile.open(fileobj=stream, mode='w:gz') as output:
            for path in sorted(source.iterdir()): output.add(path, arcname=path.name)
    else:
        raise ValueError('Choose zip or tar manager transfer.')
    return stream.getvalue()



LOCAL_TEST_MANIFEST = '.build-manager-local-tests.json'


def _public_test_files(checkout):
    """Tracked files plus new public source/tests, never arbitrary private files."""
    checkout = Path(checkout).resolve()
    tracked = subprocess.check_output(['git', '-C', str(checkout), 'ls-files', '-z'])
    added = subprocess.check_output(['git', '-C', str(checkout), 'ls-files', '-z',
        '--others', '--exclude-standard', '--', 'Python/build_manager', 'Python/tests', 'Scripts', 'docs'])
    names = {os.fsdecode(value) for value in (tracked + added).split(b'\0') if value}
    files = {}
    for name in sorted(names):
        if name == 'Python/commonUtils' or name.startswith('Python/commonUtils/'):
            continue
        path = checkout / name
        if path.is_symlink() or not path.resolve().is_relative_to(checkout):
            raise ValueError('Local manager test source must not contain linked inputs: ' + name)
        if path.exists() and not path.is_file():
            raise ValueError('Unsupported local manager test source: ' + name)
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return files


def local_test_identity(checkout, pin):
    """An opt-in local validation overlay; never substitutes for a release pin."""
    _, shared = verify(checkout, pin, working_tree=True)
    data = dict(schema=1, purpose='local-tests-only', commit=pin, commonUtils_commit=shared,
                files=_public_test_files(checkout))
    data['fingerprint'] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return data


def verify_local_test_source(checkout, pin, expected):
    if not re.fullmatch(r'[0-9a-f]{64}', expected or ''):
        raise ValueError('Local manager testing requires an exact reviewed content identity.')
    path = Path(checkout) / LOCAL_TEST_MANIFEST
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Missing bounded local manager test capture manifest.')
    recorded = json.loads(path.read_text())
    actual = local_test_identity(checkout, pin)
    if recorded != actual or actual['fingerprint'] != expected:
        raise ValueError('Local manager test capture differs from the reviewed source.')
    return actual
