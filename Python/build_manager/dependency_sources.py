"""Exact committed manager/dependency transfer; callers own pins and scratch policy."""
import io
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile

def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True, timeout=60).strip()


def verify(checkout, pin, *, pinned_source=False):
    checkout = Path(checkout).resolve()
    if not isinstance(pin, str) or not re.fullmatch(r'[0-9a-f]{40}', pin):
        raise ValueError('Dependency pin must be a full Git commit.')
    if not pinned_source and git(checkout, 'rev-parse', 'HEAD') != pin:
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
        if git(folder, 'status', '--porcelain', '--untracked-files=no'):
            raise ValueError('Commit manager/dependency edits before guest transfer.')
    return pin, shared


def archive(checkout, pin, kind, workspace):
    if kind not in {'zip', 'tar'}:
        raise ValueError('Choose zip or tar manager transfer.')
    checkout = Path(checkout).resolve()
    pin, shared = verify(checkout, pin, pinned_source=True)
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

