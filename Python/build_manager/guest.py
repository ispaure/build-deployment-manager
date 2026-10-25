"""Owned Linux guest child lifetime; callable through a provider transport."""
import argparse
import base64
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('token')
    parser.add_argument('uid', type=int)
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
    process = subprocess.Popen(command['argv'], cwd=root / 'source', env=environment, start_new_session=True)
    record = root / 'active.json'
    record.write_text(json.dumps(dict(pid=process.pid, token=args.token)))
    try:
        return process.wait()
    finally:
        record.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as error:
        print('Guest execution failed: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
