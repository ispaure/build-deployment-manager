"""First-failure evidence and existing bounded cleanup for owned test fixtures."""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys


def _owned_executable(root, target):
    root, target = Path(root).absolute(), Path(target).absolute()
    expected = root / '.venv/Scripts/python.exe'
    if target != expected:
        return False
    for path in (*root.parents, root, root / '.venv', root / '.venv/Scripts', expected):
        information = path.lstat()
        if stat.S_ISLNK(information.st_mode) or getattr(information, 'st_file_attributes', 0) & 0x400:
            return False  # FILE_ATTRIBUTE_REPARSE_POINT, including junctions.
        if not (stat.S_ISREG(information.st_mode) if path == expected else stat.S_ISDIR(information.st_mode)):
            return False
    return root.resolve() == root and expected.is_file()


def _owned_fixture_identity(root, target):
    if not _owned_executable(root, target):
        raise ValueError('Owned fixture path check failed.')
    root = Path(root).absolute()
    identity = tuple((info.st_dev, info.st_ino) for info in
                     (path.lstat() for path in (root, root / '.venv', root / '.venv/Scripts', Path(target))))
    if any(inode <= 0 for device, inode in identity):
        raise ValueError('Owned fixture identity is unavailable.')
    return identity


def _cleanup_receipt(**receipt):
    # Recovery must leave the original failure visible even when removal succeeds.
    print('Private interpreter cleanup: ' + json.dumps(receipt, sort_keys=True), file=sys.stderr, flush=True)


def _resource_owners(path, library=None):
    class UniqueProcess(c.Structure):
        _fields_ = [('pid', w.DWORD), ('started', w.FILETIME)]
    class ProcessInfo(c.Structure):
        _fields_ = [('process', UniqueProcess), ('app', w.WCHAR * 256),
                   ('service', w.WCHAR * 64), ('kind', w.UINT), ('status', w.ULONG),
                   ('session', w.DWORD), ('restartable', w.BOOL)]
    library = library if library is not None else c.WinDLL('rstrtmgr', use_last_error=True)
    declarations = {
        'RmStartSession': [c.POINTER(w.DWORD), w.DWORD, w.LPWSTR],
        'RmRegisterResources': [w.DWORD, w.UINT, c.POINTER(w.LPCWSTR), w.UINT,
                                c.POINTER(UniqueProcess), w.UINT, c.POINTER(w.LPCWSTR)],
        'RmGetList': [w.DWORD, c.POINTER(w.UINT), c.POINTER(w.UINT),
                      c.POINTER(ProcessInfo), c.POINTER(w.DWORD)],
        'RmEndSession': [w.DWORD],
    }
    for name, arguments in declarations.items():
        function = getattr(library, name)
        function.argtypes, function.restype = arguments, w.DWORD
    session = w.DWORD()
    status = library.RmStartSession(c.byref(session), 0, c.create_unicode_buffer(33))
    if status:
        return dict(stage='start', query_error=status)
    try:
        status = library.RmRegisterResources(session, 1, (w.LPCWSTR * 1)(str(path)), 0, None, 0, None)
        if status:
            return dict(stage='register', query_error=status)
        needed, count, reasons = w.UINT(), w.UINT(), w.DWORD()
        status = library.RmGetList(session, c.byref(needed), c.byref(count), None, c.byref(reasons))
        if status == 0:
            return dict(query_error=0, owners=[])
        if status != 234 or not 0 < needed.value <= 32:
            return dict(stage='list', query_error=status, needed=needed.value)
        count.value = needed.value
        rows = (ProcessInfo * count.value)()
        status = library.RmGetList(session, c.byref(needed), c.byref(count), rows, c.byref(reasons))
        if status:
            return dict(stage='list_bounded', query_error=status, needed=needed.value)
        return dict(query_error=0, owners=[dict(pid=row.process.pid,
            creation_time=(row.process.started.dwHighDateTime << 32) | row.process.started.dwLowDateTime)
            for row in rows[:count.value]])
    finally:
        library.RmEndSession(session)


def _executable_hash(path):
    try:
        with Path(path).open('rb') as stream:
            digest, remaining = hashlib.sha256(), 16 * 1024 * 1024
            while data := stream.read(min(65536, remaining + 1)):
                remaining -= len(data)
                if remaining < 0:
                    return dict(error='size_limit')
                digest.update(data)
        return dict(sha256=digest.hexdigest())
    except OSError as error:
        return dict(error=type(error).__name__, winerror=getattr(error, 'winerror', None))


def _collect_failure(root, target):
    if not _owned_executable(root, target):
        return dict(error='owned_path_check_failed')
    return dict(schema=1, system=platform.system(), windows_version=platform.win32_ver(),
        machine=platform.machine(), python_bits=8 * c.sizeof(c.c_void_p),
        python=sys.version, compiler=platform.python_compiler(),
        build=platform.python_build(), executable=sys.executable, base_executable=sys._base_executable,
        base_hash=_executable_hash(sys._base_executable), fixture_hash=_executable_hash(target),
        attributes=getattr(Path(target).stat(), 'st_file_attributes', None),
        resource_owners=_resource_owners(target))


def _diagnose_failure(root, target):
    # The child imports only stdlib, queries one exact fixture resource, and
    # cannot outlive the three-second bound. Limit accepted evidence to 16 KiB
    # after capture of this fixed child's small schema; never forward stderr.
    result = subprocess.run([sys.executable, '-I', '-B', str(Path(__file__).resolve()),
        str(root), str(target)], capture_output=True, text=True, timeout=3)
    if result.returncode or len(result.stdout) > 16384:
        return dict(error='diagnostic_child_failed', exit_code=result.returncode)
    return json.loads(result.stdout)


def cleanup_private_interpreter(temporary):
    """Diagnose the first failure before applying the existing owned-tree policy."""
    try:
        return temporary.cleanup()
    except PermissionError as error:
        if os.name == 'nt' and getattr(error, 'winerror', None) in (5, 32, 33) and error.filename:
            identity = None
            try:
                identity = _owned_fixture_identity(temporary.name, error.filename)
                evidence = _diagnose_failure(temporary.name, error.filename)
                note = json.dumps(evidence, sort_keys=True)
            except Exception as diagnostic_error:
                note = json.dumps(dict(error=type(diagnostic_error).__name__))
            try:
                error.add_note('Private interpreter cleanup evidence: ' + note)
            except Exception:
                pass  # Diagnostic annotation must not replace cleanup failure.
            if identity is not None:
                try:
                    _cleanup_receipt(stage='first_failure', error=type(error).__name__,
                                     errno=error.errno, winerror=error.winerror,
                                     failed_path=error.filename, evidence=json.loads(note))
                    if _owned_fixture_identity(temporary.name, error.filename) != identity:
                        raise ValueError('Owned fixture identity changed during diagnosis.')
                    from build_manager.retention import remove_tree
                    remove_tree(Path(temporary.name))
                    try:
                        Path(temporary.name).lstat()
                    except FileNotFoundError:
                        pass
                    else:
                        raise ValueError('Owned fixture removal did not finish.')
                    _cleanup_receipt(stage='bounded_outcome', outcome='removed', policy_seconds=3)
                except Exception as recovery_error:
                    try:
                        outcome = dict(stage='bounded_outcome', outcome='failed', policy_seconds=3,
                                       error=type(recovery_error).__name__,
                                       winerror=getattr(recovery_error, 'winerror', None))
                        error.add_note('Private interpreter cleanup outcome: ' + json.dumps(outcome, sort_keys=True))
                        _cleanup_receipt(**outcome)
                    except Exception:
                        pass
                else:
                    return None
        raise


if __name__ == '__main__':
    if os.name != 'nt' or len(sys.argv) != 3:
        raise SystemExit('Windows owned-fixture diagnostic only')
    print(json.dumps(_collect_failure(*sys.argv[1:])))
