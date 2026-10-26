"""Execute an explicitly selected trusted local plan; adapters own its policy."""
import argparse
import json
from pathlib import Path
import signal
from threading import Event, Thread, Lock

from .executor import Executor
from .models import Plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--confirm', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--approval-identity', action='append', default=[], help='Reviewed STEP=SHA256 identity; rechecked before continuation')
    parser.add_argument('--approve-step', action='append', default=[])
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
    event_lock = Lock()
    def event(value):
        with event_lock:
            print(json.dumps(value), flush=True)
    try:
        plan = Plan.load(args.plan)
        approvals = []
        identities = {}
        for value in args.approval_identity:
            step, separator, digest = value.partition('=')
            if not separator or not step or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
                raise ValueError('Invalid reviewed approval identity.')
            if step in identities or step not in args.approve_step:
                raise ValueError('Reviewed identity must name one approved step.')
            identities[step] = digest
        if args.approve_step:
            if not args.resume or not args.confirm:
                raise ValueError('Step approval needs --resume --confirm after artifact/destination review.')
            from .workflows import approve
            from .history import read_report
            previous = read_report(args.output/'result.json')
            approvals = [approve(plan, name, previous) for name in args.approve_step]
            if any(item.step in identities and identities[item.step] != item.identity for item in approvals):
                raise ValueError('Reviewed artifact identity changed; inspect and approve the current preparation.')
        report = Executor(cancelled=cancelled, event=event).run(
            plan, args.output, confirmed=args.confirm, resume=args.resume, approvals=approvals)
    except (OSError, ValueError, RuntimeError) as error:
        print(json.dumps(dict(type='error', error=str(error))), flush=True)
        return 1
    finally:
        stopped.set()
    return int(report['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
