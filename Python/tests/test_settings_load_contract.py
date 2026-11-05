"""Clock controls distinguish external bridge completion from Qt rendering."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

from build_manager.bridge import ProjectBridge
from build_manager import bridge_process
from settings_load_contract import (BridgeRetirement, TaskCompletions, TimedEvent, budgets,
                                    cleanup_fixture, completed_call, finish_cleanup, wait_for_event)


class Clock:
    def __init__(self):
        self.value = 0
    def monotonic(self):
        return self.value
    def sleep(self, seconds):
        self.value += seconds


def original_ui_wait():
    # The original five-second UI contract executes unchanged, without Qt/GUI.
    source = Path(importlib.util.find_spec('test_settings_async_ui').origin).read_text()
    tree = ast.parse(source)
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'SettingsAsyncTests')
    function = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'wait')
    return ast.Module(body=[function], type_ignores=[])


class SettingsLoadContractTests(unittest.TestCase):
    def limits(self):
        return budgets(ProjectBridge.load_settings, stop_grace=bridge_process.STOP_GRACE,
                       drain_timeout=bridge_process.DRAIN_TIMEOUT)

    def ui_wait(self, clock, dialog, ready):
        def pump():
            if clock.value >= ready:
                dialog.busy = False
        self.app = NS(processEvents=pump)
        scope = dict(time=clock)
        exec(compile(original_ui_wait(), 'original-settings-ui-wait', 'exec'), scope)
        return scope['wait'](self, dialog)

    def test_declared_request_and_real_retirement_paths_bound_the_worker(self):
        self.assertEqual(self.limits(), dict(request=30, retirement=40, worker=71))

    def test_old_coupled_five_seconds_fails_but_existing_request_budget_preserves_real_later_result(self):
        old = Clock()
        with self.assertRaises(AssertionError):
            self.ui_wait(old, NS(busy=True), ready=6.02)
        self.assertLess(old.value, 5.01)
        clock, dialog = Clock(), NS(busy=True)
        worker = TimedEvent(clock.monotonic)
        def progress():
            if clock.value >= 6:
                worker.set()
        wait_for_event(self, worker, self.limits()['worker'], progress,
                       stage='request', clock=clock.monotonic, pause=clock.sleep)
        self.ui_wait(clock, dialog, ready=6.02)
        self.assertFalse(dialog.busy)
        self.assertLess(clock.value, self.limits()['request'])

    def test_stalled_worker_still_fails_at_finite_declared_budget(self):
        clock = Clock()
        with self.assertRaisesRegex(AssertionError, 'request did not finish'):
            wait_for_event(self, TimedEvent(clock.monotonic), self.limits()['worker'], lambda: None,
                           stage='request', clock=clock.monotonic, pause=clock.sleep)
        self.assertGreaterEqual(clock.value, self.limits()['worker'])
        self.assertLess(clock.value, self.limits()['worker'] + .01)

    def test_finished_worker_does_not_relax_original_five_second_ui_deadline(self):
        clock = Clock()
        finished = TimedEvent(clock.monotonic); finished.set()
        wait_for_event(self, finished, self.limits()['worker'], lambda: None,
                       stage='request', clock=clock.monotonic, pause=clock.sleep)
        with self.assertRaises(AssertionError):
            self.ui_wait(clock, NS(busy=True), ready=float('inf'))
        self.assertGreaterEqual(clock.value, 5)
        self.assertLess(clock.value, 5.01)

    def test_real_delegate_return_or_exception_is_preserved_while_event_is_finalized(self):
        finished = TimedEvent()
        value = object()
        self.assertIs(completed_call(lambda: value, finished), value)
        self.assertTrue(finished.is_set())
        finished = TimedEvent()
        failure = RuntimeError('delegate failed')
        def fail():
            raise failure
        with self.assertRaises(RuntimeError) as caught:
            completed_call(fail, finished)
        self.assertIs(caught.exception, failure)
        self.assertTrue(finished.is_set())


    def test_unretired_worker_cleanup_is_finite_and_does_not_delete_fixture(self):
        from tempfile import TemporaryDirectory
        temporary = TemporaryDirectory(delete=False)
        self.addCleanup(temporary.cleanup)
        sentinel = Path(temporary.name) / 'fixture'
        sentinel.write_bytes(b'synthetic')
        clock = Clock()
        with self.assertRaisesRegex(AssertionError, 'retirement did not finish'):
            wait_for_event(self, TimedEvent(clock.monotonic), self.limits()['retirement'], lambda: None,
                           stage='retirement', clock=clock.monotonic, pause=clock.sleep)
        self.assertFalse(cleanup_fixture(temporary, attempted=True, task_finished=False,
                                       bridge_entered=True, bridge_retired=False))
        self.assertEqual(sentinel.read_bytes(), b'synthetic')
        self.assertLess(clock.value, self.limits()['retirement'] + .01)
        self.assertFalse(cleanup_fixture(temporary, attempted=True, task_finished=True,
                                       bridge_entered=True, bridge_retired=False))
        self.assertTrue(sentinel.exists())
        self.assertTrue(cleanup_fixture(temporary, attempted=True, task_finished=True,
                                      bridge_entered=True, bridge_retired=True))
        self.assertFalse(sentinel.exists())


    def test_completion_after_deadline_is_rejected_even_when_pump_sets_flag(self):
        clock = Clock()
        event = TimedEvent(clock.monotonic)
        def late_completion():
            clock.value = 2
            event.set()
        with self.assertRaisesRegex(AssertionError, 'completed after'):
            wait_for_event(self, event, 1, late_completion, stage='request',
                           clock=clock.monotonic, pause=clock.sleep)

    def test_timely_completion_survives_late_observer_and_is_never_retimestamped(self):
        clock = Clock()
        event = TimedEvent(clock.monotonic)
        def delayed_observation():
            clock.value = .5
            event.set()
            clock.value = 2
            event.set()
        wait_for_event(self, event, 1, delayed_observation, stage='request',
                       clock=clock.monotonic, pause=clock.sleep)
        self.assertEqual(event.completion_time(), .5)
        self.assertGreater(clock.value, 1)

    def test_cleanup_failure_preserves_any_original_primary_exception(self):
        from unittest.mock import Mock
        for phase in ('fixture setup', 'dialog construction', 'request', 'render'):
            primary = RuntimeError(phase)
            cleanup_error = PermissionError('cleanup denied')
            temporary = NS(cleanup=Mock(side_effect=cleanup_error))
            called = []
            def reject():
                called.append('reject')
                raise ValueError('dialog reject failed')
            def remove():
                return cleanup_fixture(temporary, attempted=True, task_finished=True,
                                       bridge_entered=True, bridge_retired=True)
            with self.subTest(phase=phase), self.assertRaises(RuntimeError) as caught:
                try:
                    raise primary
                except RuntimeError:
                    finish_cleanup(primary, [reject, remove])
                    raise
            self.assertIs(caught.exception, primary)
            self.assertEqual(called, ['reject'])
            temporary.cleanup.assert_called_once()
            self.assertEqual(len(primary.__notes__), 2)

    def test_sole_cleanup_failure_is_raised_after_other_owned_cleanup_is_attempted(self):
        from unittest.mock import Mock
        failure = PermissionError('cleanup denied')
        temporary = NS(cleanup=Mock(side_effect=failure))
        final = Mock()
        def remove():
            return cleanup_fixture(temporary, attempted=False, task_finished=False,
                                   bridge_entered=False, bridge_retired=False)
        with self.assertRaises(PermissionError) as caught:
            finish_cleanup(None, [remove, final])
        self.assertIs(caught.exception, failure)
        final.assert_called_once()


    def test_other_qrunnable_completion_cannot_retire_selected_task_in_either_order(self):
        from unittest.mock import Mock
        for reverse in (False, True):
            ledger = TaskCompletions()
            first, second = object(), object()
            if reverse:
                first, second = second, first
            first_event, second_event = ledger.event(first), ledger.event(second)
            self.assertIs(ledger.event(first), first_event)
            transport = Mock(return_value='unchanged')
            self.assertEqual(ledger.call(transport, second), 'unchanged')
            self.assertTrue(second_event.is_set())
            self.assertFalse(first_event.is_set())
            self.assertEqual(ledger.call(transport, first), 'unchanged')
            self.assertTrue(first_event.is_set())
            self.assertTrue(second_event.is_set())
            self.assertEqual([call.args[0] for call in transport.call_args_list], [second, first])

    def test_bridge_completion_requires_exact_owner_root_and_command_in_either_order(self):
        from unittest.mock import Mock
        for reverse in (False, True):
            left = BridgeRetirement('/fixture-a', ['/fixture-a/python', '/fixture-a/bridge.py'])
            right = BridgeRetirement('/fixture-b', ['/fixture-b/python', '/fixture-b/bridge.py'])
            if reverse:
                left, right = right, left
            actual = Mock(return_value='actual response')
            def global_call(argv, **kwargs):
                return left.call(lambda *args, **values: right.call(actual, *args, **values), argv, **kwargs)
            self.assertEqual(global_call(right.argv, cwd=right.root), 'actual response')
            self.assertTrue(right.retired.is_set())
            self.assertFalse(left.entered.is_set())
            self.assertFalse(left.retired.is_set())
            global_call(['/other/python', '/other/bridge.py'], cwd=left.root)
            self.assertFalse(left.entered.is_set())
            global_call(left.argv, cwd=right.root)
            self.assertFalse(left.entered.is_set())
            self.assertEqual(global_call(left.argv, cwd=left.root), 'actual response')
            self.assertTrue(left.entered.is_set())
            self.assertTrue(left.retired.is_set())

    def test_owned_bridge_failure_never_claims_retirement_or_marks_another_owner(self):
        own = BridgeRetirement('/fixture-a', ['/fixture-a/python', '/fixture-a/bridge.py'])
        other = BridgeRetirement('/fixture-b', ['/fixture-b/python', '/fixture-b/bridge.py'])
        failure = RuntimeError('actual transport failed')
        def actual(*args, **kwargs):
            raise failure
        with self.assertRaises(RuntimeError) as caught:
            own.call(actual, own.argv, cwd=own.root)
        self.assertIs(caught.exception, failure)
        self.assertTrue(own.entered.is_set())
        self.assertFalse(own.retired.is_set())
        self.assertFalse(other.entered.is_set())
        self.assertFalse(other.retired.is_set())


class OwnedSettingsErrorTests(unittest.TestCase):
    def test_actual_load_wrapper_preserves_error_before_completion_and_before_missing_control(self):
        # Read the real fixture wrapper without importing Qt or launching a child.
        source = Path(importlib.util.find_spec('test_accessible_flow').origin).read_text()
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AccessibleFlowTests')
        case = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'test_registered_settings_load_without_approval_popup')
        load = next(n for n in ast.walk(case) if isinstance(n, ast.FunctionDef) and n.name == 'load')
        guard = next(n for n in ast.walk(case) if isinstance(n, ast.If)
                     and isinstance(n.test, ast.Name) and n.test.id == 'load_errors')
        errors, publication = [], []
        finished = NS(set=lambda: publication.append(bool(errors)))
        failure, cause = ValueError('Synthetic owned transport failure'), TimeoutError('Synthetic inventory timeout')
        failure.receipt = dict(stage='session_inventory', error_class='TimeoutExpired', session_id=41)
        def fail(*args, **kwargs):
            raise failure from cause
        scope = dict(real_load=fail, finished=finished, load_errors=errors)
        exec(compile(ast.Module(body=[load], type_ignores=[]), 'actual-settings-load-wrapper', 'exec'), scope)
        with self.assertRaises(ValueError) as caught:
            scope['load']()
        self.assertIs(caught.exception, failure)
        self.assertEqual(publication, [True])
        self.assertEqual(errors, [failure])
        following = ast.parse("raise KeyError('sample')").body[0]
        with self.assertRaises(ValueError) as caught:
            exec(compile(ast.Module(body=[guard, following], type_ignores=[]),
                         'actual-settings-completion-guard', 'exec'), scope)
        self.assertIs(caught.exception, failure)
        self.assertIs(caught.exception.__cause__, cause)
        self.assertEqual(caught.exception.receipt,
                         dict(stage='session_inventory', error_class='TimeoutExpired', session_id=41))
