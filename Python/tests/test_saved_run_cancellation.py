"""Requests reach the existing scheduler without process discovery/signals."""
import os
import subprocess
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread
import time
import unittest
from unittest.mock import patch
from build_manager import Phase, Plan
from build_manager.cancellation import CAPABILITY, LOCK, cancellable_attempt, read_control, request_cancellation, request_path
from build_manager.executor import Executor
from build_manager.profiles import save_json

ENGINE = {'manager': {'commit': 'a' * 40}, 'commonUtils': {'commit': 'b' * 40}}


class CancellationTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.output = self.root / 'run'
        self.output.mkdir()
        self.plan = Plan('Cancellation contract', 'test', {},
            (Phase('work', (sys.executable, '-c', 'pass'), str(self.root)),), str(self.root / 'workspace'))
        self.plan.save(self.output / 'plan.json')
        save_json(self.output / 'result.json', dict(schema=1, status='running', phases=[],
            plan_identity=self.plan.identity, engine=ENGINE))

    def request_file(self):
        return request_path(self.output, read_control(self.output / CAPABILITY)['attempt'])

    def request(self, **options):
        return request_cancellation(self.output, expected_identity=self.plan.identity, confirmed=True, **options)

    def test_only_exact_live_attempt_consumed_reports_untouched_and_terminal_rejected(self):
        original = (self.output / 'result.json').read_bytes()
        cancelled = Event()
        with cancellable_attempt(self.output, self.plan.identity, ENGINE, cancelled) as poll:
            self.assertEqual(self.request()['status'], 'requested')
            self.assertFalse(cancelled.is_set())
            poll()
            self.assertTrue(cancelled.is_set())
            self.assertEqual((self.output / 'result.json').read_bytes(), original)
        with self.assertRaisesRegex(ValueError, 'no longer cancellable'):
            self.request()

    def test_resumed_attempt_ignores_old_request_and_rejects_stale_expected_nonce(self):
        with cancellable_attempt(self.output, self.plan.identity, ENGINE, Event()):
            old = self.request()['attempt']
        cancelled = Event()
        with cancellable_attempt(self.output, self.plan.identity, ENGINE, cancelled) as poll:
            poll()
            self.assertFalse(cancelled.is_set())
            with self.assertRaisesRegex(ValueError, 'attempt changed'):
                self.request(expected_attempt=old)
            self.request()
            poll()
            self.assertTrue(cancelled.is_set())

    def test_stale_publisher_cannot_clobber_acknowledged_resumed_request(self):
        entered, release, errors = Event(), Event(), []
        from build_manager import cancellation
        original_save = cancellation.save_json
        old_path = None
        def paused_save(path, value):
            if path == old_path:
                entered.set()
                if not release.wait(3):
                    raise AssertionError('Interleaving fixture did not release its own publisher')
            return original_save(path, value)
        def stale_requester():
            try:
                self.request()
            except BaseException as error:
                errors.append(error)
        with patch('build_manager.cancellation.save_json', side_effect=paused_save):
            with cancellable_attempt(self.output, self.plan.identity, ENGINE, Event()):
                old_path = self.request_file()
                publisher = Thread(target=stale_requester)
                publisher.start()
                self.assertTrue(entered.wait(2))
            cancelled = Event()
            try:
                with cancellable_attempt(self.output, self.plan.identity, ENGINE, cancelled) as poll:
                    current_path = self.request_file()
                    self.assertNotEqual(current_path, old_path)
                    self.assertEqual(self.request()['status'], 'requested')
                    acknowledged = current_path.read_bytes()
                    release.set()
                    publisher.join(2)
                    self.assertFalse(publisher.is_alive())
                    self.assertEqual(len(errors), 1)
                    self.assertIsInstance(errors[0], ValueError)
                    self.assertTrue(old_path.exists())
                    self.assertEqual(current_path.read_bytes(), acknowledged)
                    poll()
                    self.assertTrue(cancelled.is_set())
            finally:
                release.set()
                publisher.join(3)

    def test_confirmation_wrong_identity_changed_engine_terminal_rejected(self):
        with self.assertRaisesRegex(ValueError, 'confirmation'):
            request_cancellation(self.output, expected_identity=self.plan.identity)
        with cancellable_attempt(self.output, self.plan.identity, ENGINE, Event()):
            with self.assertRaisesRegex(ValueError, 'identity does not match'):
                request_cancellation(self.output, expected_identity='f' * 64, confirmed=True)
            report = read_control(self.output / 'result.json')
            report['engine'] = {'manager': {'commit': 'c' * 40}}
            save_json(self.output / 'result.json', report)
            with self.assertRaisesRegex(ValueError, 'engine'):
                self.request()
            report.update(engine=ENGINE, status='passed')
            save_json(self.output / 'result.json', report)
            with self.assertRaisesRegex(ValueError, 'active cancellable'):
                self.request()
            self.assertEqual(list(self.output.glob('cancel-request-*.json')), [])

    def test_legacy_or_not_yet_admitted_actionable(self):
        with self.assertRaisesRegex(ValueError, 'not yet admitted.*older SDK'):
            self.request()
        self.assertEqual(list(self.output.glob('cancel-request-*.json')), [])

    def test_malformed_oversize_and_wrong_nonce_requests_never_cancel(self):
        cancelled = Event()
        with cancellable_attempt(self.output, self.plan.identity, ENGINE, cancelled) as poll:
            for raw in ('[]', '{', 'x' * 16385, '{"attempt":"wrong"}'):
                self.request_file().write_text(raw)
                poll()
                self.assertFalse(cancelled.is_set())

    @unittest.skipIf(os.name == 'nt', 'Symlink creation needs Windows privilege')
    def test_linked_directory_control_and_evidence_refused(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.output, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'unlinked'):
            request_cancellation(alias, expected_identity=self.plan.identity, confirmed=True)
        foreign = self.root / 'foreign'
        foreign.write_text('untouched')
        (self.output / LOCK).symlink_to(foreign)
        with self.assertRaisesRegex(ValueError, 'linked'):
            with cancellable_attempt(self.output, self.plan.identity, ENGINE, Event()):
                self.fail('linked lock admitted')
        (self.output / LOCK).unlink()
        with cancellable_attempt(self.output, self.plan.identity, ENGINE, Event()):
            for name in (self.request_file().name, CAPABILITY, 'result.json', 'plan.json'):
                target = self.output / name
                saved = target.read_bytes() if target.exists() else None
                target.unlink(missing_ok=True)
                target.symlink_to(foreign)
                try:
                    with self.assertRaisesRegex(ValueError, 'linked'):
                        self.request()
                    self.assertEqual(foreign.read_text(), 'untouched')
                finally:
                    target.unlink()
                    if saved is not None:
                        target.write_bytes(saved)

    def test_unknown_capability_protocol_rejected_without_request(self):
        with cancellable_attempt(self.output, self.plan.identity, ENGINE, Event()):
            value = read_control(self.output / CAPABILITY)
            value['schema'] = 2
            save_json(self.output / CAPABILITY, value)
            with self.assertRaisesRegex(ValueError, 'Unrecognized cancellation capability'):
                self.request()
            self.assertEqual(list(self.output.glob('cancel-request-*.json')), [])

    def test_public_cli_returns_requested_not_finished(self):
        from build_manager.api import ManagerAPI
        from build_manager.cli import execute, parser_for_cli
        api = ManagerAPI(self.root / 'registry')
        args = parser_for_cli().parse_args(['cancel', str(self.output), '--expect-identity', self.plan.identity, '--confirm'])
        with cancellable_attempt(self.output, self.plan.identity, ENGINE, Event()):
            result = execute(args, api)
        self.assertEqual(result['status'], 'requested')
        self.assertNotIn('finished', result)

    def test_separate_controller_process_accepts_only_its_run_request(self):
        output = self.root / 'process-run'
        plan = Plan('Separate controller', 'test', {}, (
            Phase('work', (sys.executable, '-c',
                "from pathlib import Path; import time; Path('process-started').touch(); time.sleep(3)"),
                str(self.root), timeout=4),
            Phase('cleanup', (sys.executable, '-c', "from pathlib import Path; Path('process-cleaned').touch()"),
                str(self.root), dependencies=('work',), always=True)), str(self.root / 'process-workspace'))
        plan_path = self.root / 'process-plan.json'
        plan.save(plan_path)
        # Use the same loaded package paths as this fixture, including its overlay.
        import build_manager
        code = ("import build_manager, importlib; build_manager.__path__[:]=%r; "
                "importlib.reload(build_manager.executor); "
                "from build_manager.executor import Executor; from build_manager.models import Plan; "
                "Executor(resource_directory=%r).run(Plan.load(%r),%r)") % (
                    list(build_manager.__path__), str(self.root / 'process-resources'), str(plan_path), str(output))
        child = subprocess.Popen((sys.executable, '-c', code), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 8
            while not (self.root / 'process-started').exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue((self.root / 'process-started').exists())
            result = request_cancellation(output, expected_identity=plan.identity, confirmed=True)
            self.assertEqual(result['status'], 'requested')
            stdout, stderr = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, stderr.decode())
            self.assertTrue((self.root / 'process-cleaned').exists())
            self.assertEqual(read_control(output / 'result.json')['status'], 'cancelled')
        finally:
            # The real phase's own four-second limit bounds fixture retirement.
            child.communicate(timeout=10)

    def test_real_owned_child_cancelled_and_always_cleanup_completed(self):
        output = self.root / 'real-run'
        started, retired = self.root / 'started', self.root / 'cleanup'
        plan = Plan('Real cancellation', 'test', {}, (
            Phase('work', (sys.executable, '-c',
                "from pathlib import Path; import time; Path('started').write_text('ready'); time.sleep(60)"),
                str(self.root), timeout=15),
            Phase('cleanup', (sys.executable, '-c', "from pathlib import Path; Path('cleanup').write_text('retired')"),
                str(self.root), dependencies=('work',), always=True)), str(self.root / 'real-workspace'))
        cancelled, report, errors = Event(), [], []
        def control():
            try:
                report.append(Executor(cancelled=cancelled, resource_directory=self.root / 'resources').run(plan, output))
            except BaseException as error:
                errors.append(error)
        with patch('build_manager.identity.capture_engine_source_identity', return_value=ENGINE):
            controller = Thread(target=control)
            controller.start()
            try:
                deadline = time.monotonic() + 8
                while not started.exists() and controller.is_alive() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(started.exists(), errors)
                self.assertTrue((output / CAPABILITY).exists())
                self.assertEqual(request_cancellation(output, expected_identity=plan.identity, confirmed=True)['status'], 'requested')
                controller.join(10)
                self.assertFalse(controller.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(report[0]['status'], 'cancelled')
                rows = {row['id']: row for row in report[0]['phases']}
                self.assertEqual(rows['work']['status'], 'cancelled')
                self.assertEqual(rows['cleanup']['status'], 'passed')
                self.assertEqual(retired.read_text(), 'retired')
            finally:
                cancelled.set()
                controller.join(20)
        self.assertFalse(controller.is_alive())


if __name__ == '__main__':
    unittest.main()
