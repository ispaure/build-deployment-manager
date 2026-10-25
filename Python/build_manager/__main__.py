"""Execute an explicitly selected trusted local plan; adapters own its policy."""
import argparse
import json
from pathlib import Path
import signal
from threading import Event, Thread

from .executor import Executor
from .models import Plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--confirm', action='store_true')
    parser.add_argument('--cancel-file', type=Path, help='Owned cancellation request marker from a local UI')
    args = parser.parse_args()
    cancelled = Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: cancelled.set())
    stopped = Event()
    if args.cancel_file:
        if args.cancel_file.exists():
            cancelled.set()
        def watch():
            while not stopped.wait(.05):
                if args.cancel_file.exists():
                    cancelled.set()
                    return
        Thread(target=watch, daemon=True).start()
    def event(value):
        print(json.dumps(value), flush=True)
    try:
        report = Executor(cancelled=cancelled, event=event).run(
            Plan.load(args.plan), args.output, confirmed=args.confirm)
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps(dict(type='error', error=str(error))), flush=True)
        return 1
    finally:
        stopped.set()
    return int(report['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
