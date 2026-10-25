"""Run generic contracts from an explicitly installed manager Git checkout."""
from pathlib import Path
import sys
import unittest


def main():
    root = Path(__file__).resolve().parents[2]
    tests = root / 'tests'
    if not tests.is_dir():
        raise SystemExit('Manager contracts require its Git checkout installation.')
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover(str(tests)))
    return int(not result.wasSuccessful())


if __name__ == '__main__':
    sys.exit(main())
