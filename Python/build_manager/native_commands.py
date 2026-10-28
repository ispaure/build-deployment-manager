"""Synchronous POSIX commands with owned descendant cleanup and caller policy."""
import subprocess
from .executor import stop_process


def interrupt(*_):
    raise KeyboardInterrupt


def command(argv, cwd, timeout=1200, *, stdout=None, stderr=None, check=True,
            failure='Command failed'):
    # This adapter deliberately preserves the POSIX session contract. Windows
    # plans use the executor's Windows job owner rather than this API.
    options = dict(cwd=cwd, start_new_session=True)
    if stdout is not None:
        options['stdout'] = stdout
    if stderr is not None:
        options['stderr'] = stderr
    process = subprocess.Popen(argv, **options)
    try:
        code = process.wait(timeout=timeout)
        if check and code:
            raise RuntimeError(f'{failure}: {code}')
        return code
    finally:
        # Retire descendants even if the immediate child already exited.
        stop_process(process)
