# Copyright (c) 2026 ispaure
# SPDX-License-Identifier: MIT

"""Structured CoreDevice commands, usable with Xcode's standard-library Python."""
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


def device_json(arguments, *, env=None, cwd=None, timeout=60):
    """Run one devicectl command and return its successful result object."""
    with TemporaryDirectory(prefix='build-manager-device-') as directory:
        output = Path(directory) / 'result.json'
        subprocess.run(
            ['xcrun', 'devicectl', *arguments, '--timeout', str(timeout), '--json-output', str(output)],
            env=env, cwd=cwd, stdout=subprocess.DEVNULL, check=True, timeout=timeout + 10,
        )
        try:
            data = json.loads(output.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, ValueError) as error:
            raise RuntimeError('Xcode device operation returned no readable JSON result.') from error
        info = data.get('info') if isinstance(data, dict) else None
        if not isinstance(info, dict) or info.get('outcome') != 'success':
            raise RuntimeError('Xcode device operation did not report success.')
        result = data.get('result')
        if not isinstance(result, dict):
            raise RuntimeError('Xcode device operation returned an invalid result.')
        return result
