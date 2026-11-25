# Copyright (c) 2026 ispaure
# SPDX-License-Identifier: MIT

"""Reviewed cleanup delegates only current selections to the real storage owners."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, nullcontext
import json
import os
from pathlib import Path
from subprocess import CompletedProcess
import sys
from tempfile import TemporaryDirectory
from threading import Event
from time import time
import unittest
from unittest.mock import patch

from build_manager import Phase, Plan, retention
from build_manager.bridge import ProjectBridge
from build_manager.locking import workspace_lock
from build_manager.registry import Registry
from build_manager.storage_cleanup import execute, prepare_preview, recommended_caches
from build_manager.storage_inventory import normalize, read_owned_inventory


def owned(path):
    return (path / '.fixture-owned').is_file()


class FixtureProject:
    def __init__(self, root):
        self.root = root / 'project'
        self.root.mkdir()
        self.results_directory = self.root / 'runs'
        self.results_directory.mkdir()
        self.archive = self.root / 'archive'
        self.archive.mkdir()
        self.descriptor = dict(schema=1, adapter_api=1, project_id='storage-fixture',
                               name='Storage fixture', interpreter='.venv/bin/python',
                               bridge='fixture.py', capabilities=dict(platforms=['Host'],
                               operations=['Check']), test_evidence=['archive'])
        self.write_descriptor(self.descriptor)
        self.registry = Registry(root / 'registry')
        self.key = self.registry.add(self.root)
        self.groups = {'Build outputs': self.root / 'outputs'}
        self.groups['Build outputs'].mkdir()
        self.inventory_calls = 0
        self.duplicate_rows = False
        self.calls = []
        self.before_delete = lambda selection: None

    def write_descriptor(self, descriptor):
        (self.root / 'build-project.json').write_text(json.dumps(descriptor), encoding='utf-8')

    def output(self, name, *, group='Build outputs'):
        path = self.groups[group] / name
        path.mkdir()
        (path / '.fixture-owned').touch()
        (path / 'payload').write_bytes(b'fixture output')
        return path

    def storage_inventory(self):
        self.inventory_calls += 1
        rows = [dict(row, group=group, category=group)
                for group, root in self.groups.items()
                for row in retention.owned_entries(root, eligible=owned,
                                                   protection=retention.nested_workflow_hold_reason)]
        return rows + rows if self.duplicate_rows else rows

    def delete_storage(self, selections):
        self.calls.append(selections)
        with self.before_delete(selections) or nullcontext():
            result = dict(removed=[], skipped=[])
            for group, names in selections.items():
                outcome = retention.delete_owned(self.groups[group], names, eligible=owned,
                                                 protection=retention.nested_workflow_hold_reason)
                result['removed'].extend(outcome['removed'])
                result['skipped'].extend(outcome['skipped'])
            return result

    def saved_run(self, name, *, status='passed'):
        run = self.results_directory / name
        run.mkdir()
        plan = Plan('Storage fixture', 'Check', {},
                    (Phase('check', (sys.executable, '-V'), str(run)),), str(self.root / 'workspace'))
        plan.save(run / 'plan.json')
        report = dict(schema=1, plan_identity=plan.identity, status=status,
                      phases=[dict(id='check', status=status)])
        (run / 'result.json').write_text(json.dumps(report), encoding='utf-8')
        for filename in ('check.log', 'screen.png', 'junit.xml', 'receipt.json'):
            (run / filename).write_bytes(filename.encode())
        return run

    def loose_evidence(self, name):
        path = self.archive / name
        path.write_bytes(b'fixture evidence')
        past = time() - 2 * 86400
        os.utime(path, (past, past))
        return path


class StorageCleanupTests(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory(prefix='storage-cleanup-contract-')
        self.addCleanup(scratch.cleanup)
        self.project = FixtureProject(Path(scratch.name).resolve())

    def selection(self, *paths):
        current = normalize(*read_owned_inventory(self.project))
        rows = {row['path']: row for row in current['by_key'].values()}
        return [rows[str(path)] for path in paths]

    def preview(self, *paths, action='outputs'):
        return prepare_preview(self.project, self.selection(*paths), action)

    def assert_stopped(self, result, *, removed=()):
        self.assertTrue(result['cancelled'], result)
        self.assertEqual(result['removed'], [str(path) for path in removed])
        self.assertEqual(result['failed'], [])

    def test_preview_is_read_only_and_only_reviewed_output_is_removed(self):
        selected = self.project.output('selected')
        unselected = self.project.output('unselected')
        unowned = selected.parent / 'unowned'
        unowned.mkdir()
        preview = self.preview(selected)
        self.assertEqual([row['path'] for row in preview.rows], [str(selected)])
        self.assertFalse(preview.skipped)
        self.assertTrue(selected.exists())
        self.assertEqual(self.project.calls, [])

        result = execute(self.project, preview)
        self.assertEqual(result['removed'], [str(selected)])
        self.assertFalse(result['skipped'] or result['failed'] or result['cancelled'])
        self.assertEqual(self.project.calls, [{'Build outputs': ['selected']}])
        self.assertFalse(selected.exists())
        self.assertTrue(unselected.is_dir())
        self.assertTrue(unowned.is_dir())

    def test_api1_inventory_retries_the_workspace_lock_diagnostic(self):
        project = self.project
        project.write_descriptor(dict(project.descriptor, adapter_actions=['storage_inventory']))
        interpreter = project.root / project.descriptor['interpreter']
        interpreter.parent.mkdir(parents=True)
        interpreter.touch()
        (project.root / project.descriptor['bridge']).touch()
        bridge = ProjectBridge(project.registry, project.key)
        busy = CompletedProcess([], 1, '', 'Earlier diagnostic\nAnother operation owns this workspace.\n')
        success = CompletedProcess([], 0, '{"schema":1,"result":[]}', '')
        with patch('build_manager.bridge_process.run', side_effect=[busy, success]) as run:
            self.assertEqual(read_owned_inventory(bridge)[0], ())
        self.assertEqual(run.call_count, 2)

        failure = CompletedProcess([], 1, '', 'Unrelated adapter failure\n')
        with patch('build_manager.bridge_process.run', return_value=failure) as run:
            with self.assertRaisesRegex(ValueError, 'Unrelated adapter failure'):
                read_owned_inventory(bridge)
        run.assert_called_once()

    def test_cleanup_retries_a_transient_retention_lock_before_deleting(self):
        candidate = self.project.output('candidate')
        preview = self.preview(candidate)
        with ExitStack() as held:
            held.enter_context(workspace_lock(candidate.parent / '.retention.lock'))

            def release_on_retry(_done, _total, message):
                if 'Retrying inventory' in message:
                    self.assertTrue(candidate.is_dir())
                    self.assertEqual(self.project.calls, [])
                    held.close()

            result = execute(self.project, preview, report=release_on_retry)
        self.assertEqual(result['removed'], [str(candidate)])
        self.assertFalse(candidate.exists())

    def test_cleanup_stops_safely_if_inventory_stays_locked(self):
        paths = [self.project.output(name) for name in ('a-first', 'b-second', 'c-third')]
        preview = self.preview(*paths)
        lock = paths[0].parent / '.retention.lock'
        with patch('build_manager.storage_inventory._INVENTORY_LOCK_WAIT', 0):
            with workspace_lock(lock):
                result = execute(self.project, preview)
                self.assertIn('Another operation is using project storage', result['blocked'])
                self.assertEqual(result['removed'], [])
                self.assertEqual(self.project.calls, [])

            with ExitStack() as held:
                def occupy_after_first(_done, _total, message):
                    if message.startswith('Checking item 2 of 3'):
                        held.enter_context(workspace_lock(lock))

                result = execute(self.project, preview, report=occupy_after_first)
            self.assertIn('Another operation is using project storage', result['blocked'])
            self.assertEqual(result['removed'], [str(paths[0])])
            self.assertEqual(self.project.calls, [{'Build outputs': ['a-first']}])
            self.assertTrue(all(path.is_dir() for path in paths[1:]))

    def test_stop_cancels_a_busy_inventory_before_retrying_or_deleting(self):
        candidate = self.project.output('candidate')
        preview = self.preview(candidate)
        stop = Event()
        reads = self.project.inventory_calls

        def stop_on_retry(_done, _total, message):
            if 'Retrying inventory' in message:
                stop.set()

        with workspace_lock(candidate.parent / '.retention.lock'):
            result = execute(self.project, preview, cancelled=stop.is_set, report=stop_on_retry)
        self.assert_stopped(result)
        self.assertEqual(self.project.inventory_calls, reads + 1)
        self.assertEqual(self.project.calls, [])
        self.assertTrue(candidate.is_dir())

    def test_cache_shortcut_keeps_a_build_declared_inside_a_reviewed_cache(self):
        cache_root = self.project.root / 'caches'
        cache_root.mkdir()
        self.project.groups['Rebuildable caches'] = cache_root
        cache = self.project.output('cache', group='Rebuildable caches')
        inventory = normalize(*read_owned_inventory(self.project))
        preview = prepare_preview(self.project, recommended_caches(self.project, inventory), 'caches')
        self.assertEqual([row['path'] for row in preview.rows], [str(cache)])

        self.project.groups['Nested builds'] = cache
        package = self.project.output('package', group='Nested builds')
        result = execute(self.project, preview)
        self.assertEqual(result['removed'], [])
        self.assertEqual(self.project.calls, [])
        self.assertTrue(package.is_dir())
        inventory = normalize(*read_owned_inventory(self.project))
        self.assertEqual(recommended_caches(self.project, inventory), [])

    def test_repeated_alias_of_same_owner_is_reviewed_and_removed_once(self):
        candidate = self.project.output('duplicate')
        self.project.duplicate_rows = True
        row, = self.selection(candidate)
        preview = prepare_preview(self.project, [row, row], 'outputs')
        self.assertEqual(len(preview.rows), 1)
        self.assertEqual(preview.estimated_bytes, row['allocated_bytes'])
        self.assertFalse(preview.skipped)
        result = execute(self.project, preview)
        self.assertEqual(result['removed'], [str(candidate)])
        self.assertEqual(self.project.calls, [{'Build outputs': ['duplicate']}])

    def test_cache_preview_explains_specific_loss_retention_and_measurement(self):
        self.project.groups['Rebuildable caches'] = self.project.root / 'cache'
        self.project.groups['Rebuildable caches'].mkdir()
        path = self.project.output('compile', group='Rebuildable caches')
        row, = self.selection(path)
        row.update(measurement='indexed', stale=False, scanned_at=12345)
        preview = prepare_preview(self.project, [row], 'outputs')
        self.assertIn('rebuildable cache folders', preview.consequence)
        self.assertIn('saved-run records remain', preview.consequence)
        self.assertIn('protected data remain', preview.consequence)
        self.assertEqual(preview.measurement_summary, 'Sizes measured during this scan')
        self.assertEqual(preview.rows[0]['scanned_at'], 12345)

    def test_same_path_with_conflicting_adapter_owners_is_excluded(self):
        candidate = self.project.output('shared')
        self.project.groups['Other owner'] = candidate.parent
        preview = self.preview(candidate)
        self.assertFalse(preview.rows)
        self.assertEqual(len(preview.skipped), 1)
        result = execute(self.project, preview)
        self.assertEqual(result['removed'], [])
        self.assertEqual(self.project.calls, [])
        self.assertTrue(candidate.is_dir())

    def test_output_and_saved_run_claiming_same_path_are_excluded(self):
        run = self.project.saved_run('shared')
        (run / '.fixture-owned').touch()
        self.project.groups['Run adapter alias'] = run.parent
        for action in ('outputs', 'runs', 'bulky'):
            with self.subTest(action=action):
                preview = self.preview(run, action=action)
                self.assertFalse(preview.rows)
                self.assertEqual(len(preview.skipped), 1)
                self.assertEqual(execute(self.project, preview)['removed'], [])
        self.assertEqual(self.project.calls, [])
        self.assertTrue((run / 'check.log').exists())
        self.assertTrue((run / 'result.json').exists())

    def test_nested_selection_is_removed_via_ancestor_once(self):
        parent = self.project.output('workspace')
        nested_root = parent / 'build-cache'
        nested_root.mkdir()
        self.project.groups['Build cache'] = nested_root
        nested = self.project.output('cache', group='Build cache')
        preview = self.preview(nested, parent)
        self.assertEqual([row['path'] for row in preview.rows], [str(parent)])
        self.assertEqual(preview.estimated_bytes, retention.allocated_bytes(parent))
        result = execute(self.project, preview)
        self.assertEqual(result['removed'], [str(parent)])
        self.assertEqual(self.project.calls, [{'Build outputs': ['workspace']}])
        self.assertFalse(nested.exists())

    def test_late_nested_hold_withholds_parent(self):
        parent = self.project.output('workspace')
        nested_root = parent / 'build-cache'
        nested_root.mkdir()
        self.project.groups['Build cache'] = nested_root
        nested = self.project.output('cache', group='Build cache')
        preview = self.preview(parent, nested)
        retention.set_workflow_hold(nested, 'fixture saved run')
        result = execute(self.project, preview)
        self.assertEqual(result['removed'], [])
        self.assertEqual(len(result['skipped']), 1)
        self.assertEqual(self.project.calls, [])
        self.assertTrue((nested / 'payload').is_file())

    def test_separately_owned_cache_can_be_removed_from_held_parent(self):
        parent = self.project.output('workspace')
        nested_root = parent / 'build-cache'
        nested_root.mkdir()
        self.project.groups['Build cache'] = nested_root
        nested = self.project.output('cache', group='Build cache')
        retention.set_workflow_hold(parent, 'fixture saved run')

        preview = self.preview(parent, nested)
        self.assertEqual([row['path'] for row in preview.rows], [str(nested)])
        self.assertEqual(len(preview.skipped), 1)
        result = execute(self.project, preview)
        self.assertEqual(result['removed'], [str(nested)])
        self.assertEqual(self.project.calls, [{'Build cache': ['cache']}])
        self.assertTrue((parent / 'payload').is_file())
        self.assertTrue(retention.protection_reason(parent))

    def test_preflight_refuses_late_pin_lease_and_hold(self):
        project = self.project
        for change in ('pin', 'lease', 'hold'):
            with self.subTest(change=change), ExitStack() as stack:
                candidate = project.output(change)
                preview = self.preview(candidate)
                if change == 'pin':
                    (candidate / '.keep').touch()
                elif change == 'lease':
                    stack.enter_context(retention.lease(candidate))
                else:
                    retention.set_workflow_hold(candidate, 'fixture saved run')
                result = execute(project, preview)
                self.assertEqual(result['removed'], [])
                self.assertEqual(len(result['skipped']), 1)
                self.assertEqual(project.calls, [])
                self.assertTrue((candidate / 'payload').is_file())

    def test_owner_refuses_protection_added_after_preflight(self):
        project = self.project
        for change in ('pin', 'lease', 'hold'):
            with self.subTest(change=change):
                candidate = project.output(change)
                preview = self.preview(candidate)

                def protect(_selection):
                    if change == 'lease':
                        return retention.lease(candidate)
                    if change == 'pin':
                        (candidate / '.keep').touch()
                    else:
                        retention.set_workflow_hold(candidate, 'fixture saved run')

                project.before_delete = protect
                result = execute(project, preview)
                self.assertEqual(result['removed'], [])
                self.assertEqual(len(result['skipped']), 1)
                self.assertFalse(result['failed'])
                self.assertEqual(project.calls[-1], {'Build outputs': [change]})
                self.assertTrue((candidate / 'payload').is_file())

    def test_replaced_output_invalidates_full_preview_even_with_equal_size_and_name(self):
        first = self.project.output('a-first')
        replaced = self.project.output('b-replaced')
        preview = self.preview(first, replaced)
        old = self.project.root / 'previous-output'
        replaced.rename(old)
        self.project.output(replaced.name)
        self.assertNotEqual(old.stat().st_ino, replaced.stat().st_ino)
        self.assertEqual(retention.allocated_bytes(old), retention.allocated_bytes(replaced))
        result = execute(self.project, preview)
        self.assertEqual(result['removed'], [])
        self.assertEqual(len(result['skipped']), 2)
        self.assertEqual(self.project.calls, [])
        self.assertTrue((first / 'payload').exists())
        self.assertTrue((replaced / 'payload').exists())
        self.assertTrue((old / 'payload').exists())

    def test_replaced_remaining_output_during_first_action_is_never_admitted(self):
        first = self.project.output('a-first')
        second = self.project.output('b-second')
        preview = self.preview(first, second)
        old = self.project.root / 'previous-second'

        def replace_remaining(selection):
            if selection == {'Build outputs': ['a-first']}:
                second.rename(old)
                self.project.output(second.name)

        self.project.before_delete = replace_remaining
        result = execute(self.project, preview)
        self.assertEqual(result['removed'], [str(first)])
        self.assertEqual(len(result['skipped']), 1)
        self.assertFalse(result['failed'])
        self.assertEqual(self.project.calls, [{'Build outputs': ['a-first']}])
        self.assertTrue((second / 'payload').is_file())
        self.assertTrue((old / 'payload').is_file())

    def test_changed_registered_descriptor_refuses_old_preview(self):
        candidate = self.project.output('candidate')
        preview = self.preview(candidate)
        descriptor = dict(self.project.descriptor, test_evidence=['relocated-evidence'])
        self.project.write_descriptor(descriptor)
        with self.assertRaisesRegex(ValueError, '(?i)project.*changed'):
            execute(self.project, preview)
        # A reopened project with the new descriptor cannot reuse the old confirmation.
        self.project.descriptor = descriptor
        with self.assertRaisesRegex(ValueError, '(?i)project.*changed'):
            execute(self.project, preview)
        self.assertEqual(self.project.calls, [])
        self.assertTrue((candidate / 'payload').exists())

    def test_bulky_cleanup_keeps_run_history_and_whole_run_cleanup_removes_it(self):
        run = self.project.saved_run('completed')
        unknown = self.project.saved_run('unknown-delivery', status='unknown')
        loose = self.project.loose_evidence('old.log')
        bulky = self.preview(run, loose, unknown, action='bulky')
        self.assertEqual({row['path'] for row in bulky.rows}, {str(run), str(loose)})
        self.assertEqual(len(bulky.skipped), 1)
        self.assertGreater(bulky.estimated_bytes, 0)
        result = execute(self.project, bulky)
        self.assertEqual(set(result['removed']), {str(run), str(loose)})
        self.assertEqual(len(result['skipped']), 1)
        self.assertFalse(loose.exists())
        self.assertFalse((run / 'check.log').exists())
        self.assertFalse((run / 'screen.png').exists())
        for filename in ('plan.json', 'result.json', 'junit.xml', 'receipt.json'):
            self.assertTrue((run / filename).is_file())
        self.assertTrue((unknown / 'check.log').is_file())
        self.assertEqual(json.loads((unknown / 'result.json').read_text())['status'], 'unknown')

        other_loose = self.project.loose_evidence('other.log')
        whole = self.preview(run, other_loose, unknown, action='runs')
        self.assertEqual([row['path'] for row in whole.rows], [str(run)])
        self.assertEqual(len(whole.skipped), 2)
        result = execute(self.project, whole)
        self.assertEqual(result['removed'], [str(run)])
        self.assertEqual(len(result['skipped']), 2)
        self.assertTrue(other_loose.exists())
        self.assertFalse((run / 'result.json').exists())
        self.assertFalse((run / 'plan.json').exists())
        self.assertFalse((run / 'receipt.json').exists())
        self.assertTrue((unknown / 'result.json').is_file())
        self.assertEqual(self.project.calls, [])

    def test_evidence_owner_refuses_file_replaced_after_preflight(self):
        loose = self.project.loose_evidence('old.log')
        preview = self.preview(loose, action='bulky')
        previous = self.project.root / 'previous.log'

        def replace_on_admission_report(_done, _total, message):
            if message.startswith('Removing '):
                loose.rename(previous)
                self.project.loose_evidence(loose.name)

        result = execute(self.project, preview, report=replace_on_admission_report)
        self.assertNotEqual(loose.stat().st_ino, previous.stat().st_ino)
        self.assertEqual(result['removed'], [])
        self.assertEqual(len(result['skipped']), 1)
        self.assertFalse(result['failed'])
        self.assertTrue(loose.is_file())
        self.assertTrue(previous.is_file())

    def test_partial_failures_preserve_completed_owner_outcomes(self):
        project = self.project
        removed = project.output('a-completed')
        skipped = project.output('b-owner-kept')
        failed = project.output('c-owner-error')
        final = project.output('d-next-completed')
        preview = self.preview(removed, skipped, failed, final)

        def intervene(selection):
            name, = selection['Build outputs']
            if name == skipped.name:
                (skipped / '.keep').touch()
            elif name == failed.name:
                raise OSError('fixture adapter failed')

        project.before_delete = intervene
        progress = []
        result = execute(project, preview, report=lambda *update: progress.append(update))
        self.assertEqual(progress[0], (0, 4, 'Checking confirmed selection · Reading owned build files…'))
        self.assertIn((1, 4, 'Checking item 2 of 4 · b-owner-kept · Reading owned build files…'), progress)
        self.assertIn((3, 4, 'Removing d-next-completed…'), progress)
        self.assertEqual(progress[-1], (4, 4, 'Cleanup finished'))
        self.assertEqual(result['removed'], [str(removed), str(final)])
        self.assertEqual(len(result['skipped']), 1)
        self.assertIn('Pinned by .keep', result['skipped'][0])
        self.assertEqual(len(result['failed']), 1)
        self.assertIn('fixture adapter failed', result['failed'][0])
        self.assertFalse(result['cancelled'])
        self.assertTrue((skipped / 'payload').is_file())
        self.assertTrue((failed / 'payload').is_file())
        self.assertFalse(removed.exists())
        self.assertFalse(final.exists())

    def test_cancelled_before_start_never_reopens_inventory(self):
        candidate = self.project.output('candidate')
        preview = self.preview(candidate)
        reads = self.project.inventory_calls
        result = execute(self.project, preview, cancelled=lambda: True)
        self.assert_stopped(result)
        self.assertEqual(self.project.inventory_calls, reads)
        self.assertEqual(self.project.calls, [])
        self.assertTrue(candidate.is_dir())

    def test_cancellation_during_inventory_report_never_admits_action(self):
        candidate = self.project.output('candidate')
        preview = self.preview(candidate)
        stop = Event()

        def report(_done, _total, _message):
            stop.set()

        result = execute(self.project, preview, cancelled=stop.is_set, report=report)
        self.assertTrue(stop.is_set())
        self.assert_stopped(result)
        self.assertEqual(self.project.calls, [])
        self.assertTrue(candidate.is_dir())

    def test_cancellation_at_removal_report_never_admits_action(self):
        candidate = self.project.output('candidate')
        preview = self.preview(candidate)
        stop = Event()

        def report(_done, _total, message):
            if message.startswith('Removing '):
                stop.set()

        result = execute(self.project, preview, cancelled=stop.is_set, report=report)
        self.assertTrue(stop.is_set())
        self.assert_stopped(result)
        self.assertEqual(self.project.calls, [])
        self.assertTrue(candidate.is_dir())

    def test_cancellation_inside_first_admitted_action_finishes_only_that_action(self):
        first = self.project.output('a-first')
        second = self.project.output('b-second')
        preview = self.preview(first, second)
        entered = Event()
        release = Event()
        stop = Event()

        def wait_for_release(_selection):
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError('Fixture did not release the admitted action')

        self.project.before_delete = wait_for_release
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(execute, self.project, preview, cancelled=stop.is_set)
            try:
                self.assertTrue(entered.wait(timeout=5))
                stop.set()
                self.assertFalse(pending.done())
                self.assertTrue((first / 'payload').is_file())
                self.assertTrue((second / 'payload').is_file())
            finally:
                release.set()
            result = pending.result(timeout=5)
        self.assert_stopped(result, removed=(first,))
        self.assertEqual(self.project.calls, [{'Build outputs': ['a-first']}])
        self.assertFalse(first.exists())
        self.assertTrue((second / 'payload').exists())

    def test_cancellation_inside_only_action_reports_the_completed_removal(self):
        candidate = self.project.output('candidate')
        preview = self.preview(candidate)
        stop = Event()
        self.project.before_delete = lambda _selection: stop.set()

        result = execute(self.project, preview, cancelled=stop.is_set)
        self.assert_stopped(result, removed=(candidate,))
        self.assertEqual(self.project.calls, [{'Build outputs': ['candidate']}])
        self.assertFalse(candidate.exists())
