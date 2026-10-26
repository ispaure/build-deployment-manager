"""Checkout identity for reproducibility, without importing any project."""
import hashlib
from pathlib import Path
import subprocess

API_VERSION = 1


def checkout_identity(root):
    root = Path(root)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], timeout=30)
    try:
        commit = git('rev-parse', 'HEAD').decode().strip()
        digest = hashlib.sha256(commit.encode())
        status = git('status', '--porcelain', '-z')
        digest.update(git('diff', '--binary', 'HEAD'))
        for raw in sorted(set(git('ls-files', '-o', '--exclude-standard', '-z').split(b'\0'))):
            if not raw:
                continue
            path = root / raw.decode('utf-8', errors='surrogateescape')
            digest.update(raw)
            if path.is_file() and not path.is_symlink():
                digest.update(path.read_bytes())
        return dict(commit=commit, dirty=bool(status), fingerprint=digest.hexdigest())
    except (OSError, subprocess.SubprocessError):
        return dict(commit=None, dirty=None, fingerprint=None, installed=True)


def runtime_identity():
    root = Path(__file__).resolve().parents[2]
    return dict(api=API_VERSION, manager=checkout_identity(root),
                commonUtils=checkout_identity(root / 'Python/commonUtils'))


def engine_review_identity(previous, current):
    """Bind explicit continuation review to both exact engine identities."""
    import json
    return hashlib.sha256(json.dumps(dict(previous=previous, current=current),
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()
