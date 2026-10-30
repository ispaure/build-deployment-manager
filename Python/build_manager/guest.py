"""Owned Linux guest child lifetime; callable through a provider transport."""
import argparse
import hashlib
import base64
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
from contextlib import ExitStack


def write_receipt(path, values):
    """Publish one complete receipt before reporting completion to the host."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            json.dump(values, output)
            output.flush()
            os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('token')
    parser.add_argument('uid', type=int)
    parser.add_argument('--invocation', help='Token-bound invocation receipt; required for transport reconciliation')
    parser.add_argument('payload', nargs='?', default='-', help='Base64 JSON, or stdin when omitted')
    args = parser.parse_args()
    root = args.workspace
    if root.is_symlink() or root.resolve() != root or root.name != args.token:
        raise ValueError('Guest workspace ownership mismatch.')
    if json.loads((root / '.manager-owned.json').read_text())['token'] != args.token:
        raise ValueError('Guest workspace marker mismatch.')
    payload = sys.stdin.buffer.read() if args.payload == '-' else args.payload
    command = json.loads(base64.b64decode(payload, validate=True))
    account = pwd.getpwuid(args.uid)
    if account.pw_uid == 0:
        raise ValueError('Use a normal guest test account; native Qt protections remain enabled.')
    if os.getuid() == 0:
        os.initgroups(account.pw_name, account.pw_gid)
        os.setgid(account.pw_gid)
        os.setuid(account.pw_uid)
    if os.getuid() != args.uid:
        raise ValueError('Cannot execute as the selected normal guest account.')
    environment = dict(os.environ, HOME=account.pw_dir, USER=account.pw_name,
                       LOGNAME=account.pw_name, **command.get('environment', {}))
    with ExitStack() as lifetime:
        receipt = None
        request = None
        descriptor = None
        if args.invocation is not None:
            import fcntl
            import re
            if not re.fullmatch(r'[a-f0-9]{32}', args.invocation):
                raise ValueError('Invalid guest invocation token.')
            directory = root / '.manager-invocations'
            if directory.is_symlink():
                raise ValueError('Linked guest invocation directory is forbidden.')
            directory.mkdir(exist_ok=True, mode=0o700)
            descriptor = os.open(directory / (args.invocation + '.lock'),
                                 os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            lifetime.callback(os.close, descriptor)
            # The child inherits the lock. If its supervisor disappears, another
            # admission cannot launch it again while the original is still alive.
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            receipt = directory / (args.invocation + '.json')
            if receipt.is_symlink():
                raise ValueError('Linked guest invocation receipt is forbidden.')
            request = dict(token=args.token, invocation=args.invocation,
                           command_sha256=hashlib.sha256(json.dumps(command, sort_keys=True).encode()).hexdigest())
            if receipt.exists():
                saved = json.loads(receipt.read_text())
                if any(saved.get(key) != value for key, value in request.items()):
                    raise ValueError('Guest invocation receipt differs from the admitted command.')
                if saved.get('state') == 'completed' and type(saved.get('exit')) is int:
                    return saved['exit']
                raise ValueError('Guest invocation has no verified completion; refusing replay.')
            write_receipt(receipt, dict(request, state='admitted'))
        options = dict(pass_fds=(descriptor,)) if descriptor is not None else {}
        process = subprocess.Popen(command['argv'], cwd=root / 'source', env=environment,
                                   start_new_session=True, **options)
        record = root / 'active.json'
        write_receipt(record, dict(pid=process.pid, token=args.token, invocation=args.invocation))
        try:
            code = process.wait()
            if receipt is not None:
                write_receipt(receipt, dict(request, state='completed', exit=code))
            return code
        finally:
            record.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as error:
        print('Guest execution failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
