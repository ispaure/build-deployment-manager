"""Generic local interpreter prerequisite inspection; projects supply packages."""
import json
from pathlib import Path
import subprocess


def inspect_python(executable, distributions=()):
    path = Path(executable)
    if not path.is_file():
        raise ValueError('Configured Python is missing: ' + str(path))
    script = '''import json,platform,sys
from importlib.metadata import version
names=json.loads(sys.argv[1])
print(json.dumps(dict(python=sys.version, executable=sys.executable, system=platform.system(),
architecture=platform.machine(), os=platform.platform(), packages={name:version(name) for name in names})))
'''
    result = subprocess.run([str(path), '-c', script, json.dumps(list(distributions))],
                            text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError('Configured Python cannot load the required package metadata; repair its environment: '
                         + ', '.join(distributions))
    return json.loads(result.stdout)
