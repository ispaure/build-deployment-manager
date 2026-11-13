"""Portable storage accounting against real disposable scopes and the pinned index."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from commonUtils.filesystem import FolderStats
from commonUtils.filesystem.index import DirectoryCache, directory_index_path
from commonUtils.filesystem.index.allocation import allocated_size
from commonUtils.runtime.operations import OperationCancelled

from build_manager.models import Phase, Plan
from build_manager.storage_inventory import (
    BUILDS, CACHES, SAVED_RUNS, gather, invalidate, normalize, read_owned_inventory,
)
from link_fixtures import directory_link


def output(path, group='Build outputs', *, value=None, protected=''):
    return dict(group=group, name=path.name, path=str(path), protected=protected, allocated_bytes=value)


class Project:
    def __init__(self, root, rows=()):
        self.root = root
        self.results_directory = root / 'runs'
        self.descriptor = {'test_evidence': ['test-evidence']}
        self.rows = rows

    def storage_inventory(self):
        return self.rows


class RecordingCache(DirectoryCache):
    def __init__(self):
        super().__init__()
        self.peeks, self.scans, self.invalidated = [], [], []

    def peek(self, root, **options):
        self.peeks.append(root)
        return super().peek(root, **options)

    def get(self, root, **options):
        self.scans.append(root)
        return super().get(root, **options)

    def invalidate(self, root=None):
        self.invalidated.append(root)
        return super().invalidate(root)


class StorageInventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        settings = patch.dict(os.environ, COMMONUTILS_STORAGE_ROOT=str(self.root / 'commonutils'))
        settings.start()
        self.addCleanup(settings.stop)
        self.cache = RecordingCache()
        self.addCleanup(self.cache.close)

    def file(self, name, size):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x' * size)
        return path

    def directory(self, name):
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def saved_run(self, *, holds=()):
        run = self.directory('runs/recorded')
        plan = Plan('Fixture', 'Test', {},
                    (Phase('check', (sys.executable, '-V'), str(run)),), str(run))
        plan.save(run / 'plan.json')
        (run / 'result.json').write_text(json.dumps(dict(
            schema=1, plan_identity=plan.identity, operation='Test', status='passed',
            phases=[dict(id='check', status='passed')], holds=list(holds))))
        return run, self.file('runs/recorded/check.log', 101)

    def by_path(self, snapshot):
        return {row['path']: row for row in snapshot['rows']}

    def assert_conserved(self, snapshot):
        self.assertEqual(snapshot['allocated_bytes'], sum(value for _, value in snapshot['chart']))
        for category, totals in snapshot['categories'].items():
            self.assertEqual(totals['allocated_bytes'] or 0, sum(
                row['accounted_bytes'] or 0 for row in snapshot['rows'] if row['category'] == category))

    def test_index_partitions_owned_nested_trees_and_loose_evidence(self):
        build = self.file('generated/owned/artifact', 200)
        compiler = self.file('generated/owned/intermediates/object', 300)
        cache = compiler.parent
        parent = build.parent
        run, log = self.saved_run(holds=[str(parent)])
        loose = self.file('test-evidence/loose.log', 125)
        old = time.time() - 90000
        os.utime(loose, (old, old))
        outside = self.file('unclassified/secret', 20000)
        self.file('generated/unclassified/other', 30000)
        self.file('test-evidence/ignore.bin', 30000)
        directory_link(parent / 'link', outside.parent)
        alias = dict(output(parent), path=str(parent.parent) + '/./' + parent.name)
        project = Project(self.root, [output(parent, protected='Kept for a later run'),
                                      dict(alias, protected='Kept for a later run'),
                                      output(cache, 'Snapshot build caches / fixture')])
        published = []
        snapshot = gather(project, cache=self.cache, publish_cached=published.append)
        self.assertEqual(self.cache.database, directory_index_path())
        self.assertEqual(set(self.cache.scans), {parent, run})
        self.assertEqual(set(self.cache.peeks), {parent, run})
        self.assertEqual(len(published), 1)
        rows = self.by_path(snapshot)
        self.assertEqual(set(rows), {str(path) for path in (parent, cache, run, loose)})
        self.assertEqual(rows[str(cache)]['category'], CACHES)
        self.assertFalse(rows[str(cache)]['protected'])
        self.assertEqual(rows[str(cache)]['parent_key'], rows[str(parent)]['key'])
        self.assertEqual(len(rows[str(parent)]['owners']), 2)
        self.assertEqual(rows[str(parent)]['logical_bytes'], 500)
        self.assertEqual(rows[str(cache)]['logical_bytes'], 300)
        self.assertEqual(rows[str(loose)]['logical_bytes'], 125)
        self.assertEqual(rows[str(loose)]['measurement'], 'file')
        evidence = next(row for row in read_owned_inventory(project)[1] if row['path'] == str(run))
        self.assertEqual(rows[str(run)]['bulky_bytes'], evidence['bulky_bytes'])
        # Held parents do not hide a separately removable cache. Saved evidence
        # offers bulky files only, not its entire history allocation.
        self.assertEqual(snapshot['categories'][CACHES]['reviewable_bytes'], rows[str(cache)]['allocated_bytes'])
        self.assertEqual(snapshot['categories'][BUILDS]['reviewable_bytes'], 0)
        self.assertEqual(snapshot['categories'][SAVED_RUNS]['reviewable_bytes'], rows[str(loose)]['bulky_bytes'])
        self.assertEqual(snapshot['workflows'][0]['holds'], 1)
        if all(allocated_size(path, path.lstat()) >= 0 for path in (build, compiler, loose, log)):
            self.assertEqual(rows[str(parent)]['accounted_bytes'], allocated_size(build, build.lstat()))
            self.assertEqual(rows[str(cache)]['allocated_bytes'], allocated_size(compiler, compiler.lstat()))
            self.assertFalse(snapshot['estimated'])
            self.assertFalse(snapshot['partial'])
        self.assert_conserved(snapshot)

    def test_exact_alias_conflicts_and_ambiguous_action_identities_are_protected(self):
        first = self.directory('first')
        second = self.directory('second')
        declaration = output(first, value=1024)
        duplicate = dict(declaration, path=str(self.root) + '/./first')
        for order in ((declaration, duplicate), (duplicate, declaration)):
            snapshot = normalize(order)
            row, = snapshot['rows']
            self.assertEqual(row['path'], str(first))
            self.assertEqual(row['allocated_bytes'], 1024)
            self.assertEqual(len(row['owners']), 2)
            self.assertFalse(row['protected'])
            self.assertTrue(snapshot['estimated'])
        same_owner_new_path = dict(declaration, path=str(second))
        snapshot = normalize([declaration, same_owner_new_path])
        self.assertTrue(all(row['shared'] and row['protected'] for row in snapshot['rows']))
        evidence = dict(path=str(first), name='first', kind='run', protected='Held', allocated_bytes=1024)
        snapshot = normalize([declaration], [evidence])
        row, = snapshot['rows']
        self.assertTrue(row['shared'])
        self.assertIn('Held', row['protected'])
        self.assertEqual(set(source for source, _ in row['owners']), {'output', 'evidence'})
        self.assertEqual(snapshot['allocated_bytes'], 1024)

    def test_cross_source_descendants_block_enclosing_cleanup(self):
        run, _ = self.saved_run()
        project = Project(self.root, [output(run.parent)])
        result = normalize(*read_owned_inventory(project))
        rows = self.by_path(result)
        self.assertTrue(rows[str(run.parent)]['protected_descendant'])
        self.assertFalse(rows[str(run)]['protected'])

    def test_unknown_partial_and_inconsistent_totals_keep_known_disjoint_bytes(self):
        parent = self.directory('owned')
        cache = self.directory('owned/cache')
        other = self.directory('other')
        for value, cache_value, expected in ((100, 150, 150), (100, None, None), (None, 20, 20)):
            with self.subTest(parent=value, cache=cache_value):
                snapshot = normalize([output(parent, value=value), output(cache, 'Build caches', value=cache_value),
                                      output(other)])
                self.assertTrue(snapshot['partial'])
                self.assertEqual(snapshot['allocated_bytes'], expected)
                self.assertIsNone(snapshot['categories'][BUILDS]['allocated_bytes'])
                self.assertEqual(snapshot['categories'][CACHES]['allocated_bytes'], cache_value)
                if expected is not None:
                    self.assert_conserved(snapshot)
                else:
                    self.assertEqual(snapshot['chart'], ())
        self.assertEqual(normalize(())['allocated_bytes'], 0)
        zero = normalize([output(other, value=0)])
        self.assertEqual(zero['allocated_bytes'], 0)
        self.assertFalse(zero['partial'])
        self.assertEqual(zero['reviewable_bytes'], 0)
        self.assertEqual(zero['reviewable_unknown'], 0)

    def test_reported_metrics_do_not_claim_exact_indexed_allocation(self):
        parent = self.directory('owned')
        cache = self.directory('owned/cache')
        unrelated = self.directory('build-cache-by-path')
        project = Project(self.root, [output(parent, value=100),
                                      output(cache, 'Build cache', value=25),
                                      output(unrelated, 'Cached release snapshots', value=5)])
        def unavailable(root, **options):
            raise OSError('fixture unavailable')
        with patch.object(self.cache, 'get', side_effect=unavailable):
            snapshot = gather(project, cache=self.cache)
        self.assertEqual(snapshot['allocated_bytes'], 30)
        self.assertIsNone(self.by_path(snapshot)[str(parent)]['accounted_bytes'])
        self.assertTrue(snapshot['partial'])
        self.assertTrue(snapshot['estimated'])
        self.assertEqual(self.by_path(snapshot)[str(unrelated)]['category'], BUILDS)
        self.assert_conserved(snapshot)

    def test_warm_peek_is_stale_and_final_refresh_is_independent(self):
        initial = self.file('scope/start', 30)
        project = Project(self.root, [output(initial.parent)])
        gather(project, cache=self.cache)
        extra = self.file('scope/new', 250)
        cached = []
        updated = gather(project, cache=self.cache, publish_cached=cached.append)
        old, = cached
        self.assertTrue(old['stale'])
        self.assertEqual(old['rows'][0]['logical_bytes'], 30)
        self.assertEqual(updated['rows'][0]['logical_bytes'], 280)
        self.assertFalse(updated['stale'])
        self.assertFalse(tuple(self.cache._readers))
        invalidate(self.cache, updated, [extra])
        self.assertIn(initial.parent, self.cache.invalidated)

    def test_linked_ancestors_relative_and_missing_scopes_never_reach_index(self):
        outside = self.directory('outside/child')
        directory_link(self.root / 'linked', outside.parent)
        rows = [output(self.root / 'linked' / 'child', value=25),
                output(self.root / 'missing', value=100), output(Path('relative'), value=25)]
        snapshot = gather(Project(self.root, rows), cache=self.cache, publish_cached=lambda value: None)
        self.assertEqual(snapshot['scan_roots'], ())
        self.assertFalse(self.cache.scans or self.cache.peeks)
        self.assertTrue(snapshot['partial'])
        self.assertIsNone(snapshot['allocated_bytes'])
        self.assertTrue(all(row['protected'] and row['identity'] is None for row in snapshot['rows']))

    def test_link_swap_after_peek_is_refused_before_indexing(self):
        owned = self.directory('owned')
        outside = self.directory('outside')
        self.file('outside/secret', 100)
        project = Project(self.root, [output(owned, value=3)])
        def swap_scope(value):
            owned.rmdir()
            directory_link(owned, outside)
        snapshot = gather(project, cache=self.cache, publish_cached=swap_scope)
        self.assertFalse(self.cache.scans)
        row, = snapshot['rows']
        self.assertIsNone(row['identity'])
        self.assertIn('changed', row['protected'])
        self.assertIsNone(row['allocated_bytes'])
        self.assertTrue(snapshot['partial'])

    def test_unknown_index_allocation_is_explicit(self):
        root = self.directory('scope')
        self.file('scope/data', 150)
        project = Project(self.root, [output(root, value=200)])
        snapshot = self.cache.get(root)
        with patch.object(self.cache, 'get', return_value=snapshot), patch.object(
                type(snapshot), 'folder_stats',
                return_value={root: FolderStats(size=150, files=1, disk_unknown=1)}):
            result = gather(project, cache=self.cache)
        row, = result['rows']
        self.assertEqual(row['measurement'], 'indexed')
        self.assertEqual(row['logical_bytes'], 150)
        self.assertIsNone(row['allocated_bytes'])
        self.assertFalse(result['estimated'])
        self.assertTrue(result['partial'])

    def test_index_failure_is_partial_and_explained_on_the_affected_row(self):
        root = self.directory('scope')
        self.file('scope/data', 150)
        with patch.object(self.cache, 'get', side_effect=PermissionError('fixture unreadable')):
            result = gather(Project(self.root, [output(root, value=200)]), cache=self.cache)
        row, = result['rows']
        self.assertTrue(result['partial'])
        self.assertIn('fixture unreadable', row['scan_issue'])
        self.assertTrue(result['issues'])

    def test_cancelled_request_has_own_bridge_and_stops_index_refresh(self):
        owned = self.directory('owned')
        parent = self
        class RequestProject(Project):
            def with_cancellation(self, cancelled):
                class Request:
                    def storage_inventory(self):
                        parent.assertIs(cancelled, is_cancelled)
                        return [output(owned)]
                return Request()

        stopping = False
        def is_cancelled():
            return stopping

        def stop_after_cached(value):
            nonlocal stopping
            stopping = True

        with self.assertRaises(OperationCancelled):
            gather(RequestProject(self.root), cache=self.cache, cancelled=is_cancelled,
                   publish_cached=stop_after_cached)
        self.assertEqual(self.cache.peeks, [owned])
        self.assertFalse(self.cache.scans)

    def test_headless_import_does_not_import_qt(self):
        check = subprocess.run([sys.executable, '-c', '''
import sys
from build_manager.storage_inventory import gather, normalize
from build_manager.storage_cleanup import prepare_preview, execute
assert not any(name.split('.')[0] in {'PySide6', 'PyQt6', 'logistics_build'} for name in sys.modules)
'''], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stderr)
