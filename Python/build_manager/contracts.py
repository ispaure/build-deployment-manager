"""Run every generic contract module in its own interpreter, without importing Qt here."""
from pathlib import Path
import os
import subprocess
import sys


def run_modules(tests, *, runner=subprocess.run, python=sys.executable):
    """A Qt fixture cannot outlive its module into a later executor thread pool.

    Keep the parent headless and propagate every abnormal child exit. The outer
    manager phase owns the aggregate deadline and all child processes; modules
    are never retried, omitted or accepted from partial success text.
    """
    tests = Path(tests).resolve()
    environment = dict(os.environ)
    environment['PYTHONPATH'] = os.pathsep.join(filter(None, (str(tests.parent), os.environ.get('PYTHONPATH', ''))))
    modules = sorted(Path(tests).glob('test*.py'))
    if not modules:
        raise ValueError('No manager contract modules discovered.')
    failed = []
    for module in modules:
        print('Manager contract module: ' + module.name, flush=True)
        result = runner([python, '-m', 'unittest', 'discover', '-s', str(tests),
                         '-p', module.name, '-v'], env=environment)
        if result.returncode:
            failed.append((module.name, result.returncode))
            print(f'Manager module failed: {module.name} (exit {result.returncode})', flush=True)
    return failed


def main():
    tests = Path(__file__).resolve().parents[2] / 'Python/tests'
    if not tests.is_dir():
        raise SystemExit('Manager contracts require its Git checkout installation.')
    return int(bool(run_modules(tests)))


if __name__ == '__main__':
    sys.exit(main())
