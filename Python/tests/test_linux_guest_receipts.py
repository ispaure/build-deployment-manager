"""An uncertain transport must never duplicate a guest command."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest

if os.name == 'posix':
    from build_manager import guest


@unittest.skipUnless(os.name == 'posix' and os.getuid() != 0, 'Normal POSIX guest account')
class LinuxInvocationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / ('a' * 32)
        self.root.mkdir()
        (self.root / 'source').mkdir()
        (self.root / '.manager-owned.json').write_text(json.dumps(dict(token=self.root.name)))
        self.invocation = 'b' * 32
        self.count = self.root / 'count'

    def command(self, script):
        return dict(argv=[sys.executable, '-c', script, str(self.count)], environment={})

    def start(self, command, invocation=None):
        payload = base64.b64encode(json.dumps(command).encode())
        process = subprocess.Popen([sys.executable, guest.__file__, str(self.root),
            self.root.name, str(os.getuid()), '--invocation', invocation or self.invocation],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        process.stdin.write(payload)
        process.stdin.close()
        process.stdin = None
        return process

    def test_concurrent_admissions_and_later_replay_execute_once(self):
        command = self.command("import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); p.write_text(p.read_text()+'x' if p.exists() else 'x'); time.sleep(.3); sys.exit(7)")
        first, second = self.start(command), self.start(command)
        self.assertEqual(first.communicate(timeout=5)[1], b'')
        self.assertEqual(second.communicate(timeout=5)[1], b'')
        self.assertEqual((first.returncode, second.returncode), (7, 7))
        replay = self.start(command)
        replay.communicate(timeout=5)
        self.assertEqual(replay.returncode, 7)
        self.assertEqual(self.count.read_text(), 'x')
        self.assertFalse((self.root / 'active.json').exists())

    def test_changed_command_cannot_reuse_a_completed_admission(self):
        command = self.command("import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('first')")
        original = self.start(command)
        original.communicate(timeout=5)
        self.assertEqual(original.returncode, 0)
        changed = dict(command, environment=dict(EXTRA='different'))
        replay = self.start(changed)
        _, error = replay.communicate(timeout=5)
        self.assertNotEqual(replay.returncode, 0)
        self.assertIn(b'differs from the admitted command', error)
        self.assertEqual(self.count.read_text(), 'first')

    def test_supervisor_loss_waits_for_child_and_refuses_unknown_completion(self):
        command = self.command("import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); p.write_text(p.read_text()+'x' if p.exists() else 'x'); time.sleep(.7)")
        original = self.start(command)
        deadline = time.monotonic() + 5
        while not (self.count.exists() and (self.root / 'active.json').exists()):
            if time.monotonic() > deadline:
                original.kill(); original.communicate(); self.fail('Guest child did not start')
            time.sleep(.01)
        original.terminate()
        original.wait(timeout=5)
        replay = self.start(command)
        time.sleep(.05)
        self.assertIsNone(replay.poll(), "The original child must retain its admission lock")
        _, error = replay.communicate(timeout=5)
        original.communicate(timeout=5)
        self.assertNotEqual(replay.returncode, 0)
        self.assertIn(b'no verified completion; refusing replay', error)
        self.assertEqual(self.count.read_text(), 'x')

    def test_wrong_workspace_owner_rejects_before_launch(self):
        (self.root / '.manager-owned.json').write_text(json.dumps(dict(token='foreign')))
        process = self.start(self.command("import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('wrong')"))
        process.communicate(timeout=5)
        self.assertNotEqual(process.returncode, 0)
        self.assertFalse(self.count.exists())

    def test_cleanup_waits_for_completion_writer_and_leaves_no_late_report(self):
        from build_manager.parallels import REMOVE
        command = self.command("import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); p.write_text('started'); time.sleep(.4)")
        original = self.start(command)
        deadline = time.monotonic() + 5
        while not self.count.exists():
            if time.monotonic() > deadline:
                original.kill(); original.communicate(); self.fail('Guest child did not start')
            time.sleep(.01)
        cleanup = subprocess.Popen([sys.executable, '-c', REMOVE, str(self.root), self.root.name],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(.05)
        self.assertTrue((self.root / '.manager-owned.json').exists())
        self.assertIsNone(cleanup.poll())
        original.communicate(timeout=5)
        _, error = cleanup.communicate(timeout=5)
        self.assertEqual(cleanup.returncode, 0, error)
        time.sleep(.05)
        self.assertFalse(self.root.exists())
