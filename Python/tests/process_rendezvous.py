"""Real child-process rendezvous for concurrency contracts, without startup races."""
from pathlib import Path
import sys


def rendezvous_argv(root, name, peer):
    """Both children must enter before either finishes; serial admission fails."""
    root = Path(root)
    code = f'''import json,time
from pathlib import Path
started=time.time()
Path({str(root / (name + '.started'))!r}).touch()
deadline=time.monotonic()+5
while not Path({str(root / (peer + '.started'))!r}).is_file():
    if time.monotonic() >= deadline:
        raise RuntimeError('Independent work was not admitted concurrently')
    time.sleep(.01)
Path({str(root / (name + '.json'))!r}).write_text(json.dumps([started,time.time()]))
'''
    return (sys.executable, '-c', code)
