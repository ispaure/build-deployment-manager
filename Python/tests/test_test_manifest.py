"""Declarative discovery, dependency ordering and isolated interpreter contracts."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from build_manager.test_manifest import discover, phases


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'Python/tests').mkdir(parents=True)
        (self.root / 'vendor/shared/tests').mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        owner = self.root / 'vendor/shared'
        subprocess.run(['git', 'init', '-q', str(owner)], check=True)
        subprocess.run(['git', '-C', str(owner), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture', '--allow-empty'], check=True)
        pin = subprocess.check_output(['git', '-C', str(owner), 'rev-parse', 'HEAD'], text=True).strip()
        subprocess.run(['git', '-C', str(self.root), 'update-index', '--add', '--cacheinfo',
                        '160000,' + pin + ',vendor/shared'], check=True)
        self.rows = [dict(id='app', groups=['mobile'], after=['shared']),
                     dict(id='shared', owner='vendor/shared', interpreter='host')]
        self.save()

    def save(self):
        (self.root / 'build-tests.json').write_text(json.dumps(dict(schema=1, suites=self.rows)))

    def test_transitive_prerequisites_are_discovered_before_consumer_with_explicit_environments(self):
        rows = discover(self.root, 'mobile')
        self.assertEqual([row['id'] for row in rows], ['shared', 'app'])
        self.assertEqual([row['directory'] for row in rows], ['vendor/shared/tests', 'Python/tests'])
        plan = phases(self.root, 'mobile', {'host': '/host/python', 'project': '/project/python'},
                      ('runner.py', '{directory}', '--junit'))
        self.assertEqual(plan[0].argv, ('/host/python', 'runner.py', 'vendor/shared/tests', '--junit'))
        self.assertEqual(plan[1].dependencies, ('shared',))
        with self.assertRaisesRegex(ValueError, 'interpreter'):
            phases(self.root, 'mobile', {}, ('runner.py', '{directory}'))
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            phases(self.root, 'mobile', {'project': sys.executable}, 'runner.py')

    def test_cycles_unknown_dependencies_and_unpinned_owners_are_rejected(self):
        self.rows[1]['after'] = ['app']; self.save()
        with self.assertRaisesRegex(ValueError, 'Cyclic'):
            discover(self.root, 'mobile')
        self.rows[1]['after'] = ['missing']; self.save()
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            discover(self.root, 'mobile')
        self.rows[1]['after'] = []; self.rows[1]['owner'] = 'Python'; self.save()
        with self.assertRaisesRegex(ValueError, 'pinned Git submodule'):
            discover(self.root, 'mobile')

    def test_dependency_checkout_must_match_declared_pin(self):
        subprocess.run(['git', '-C', str(self.root), 'update-index', '--cacheinfo',
                        '160000,' + 'a' * 40 + ',vendor/shared'], check=True)
        with self.assertRaisesRegex(ValueError, 'pinned commit'):
            discover(self.root, 'mobile')

    def test_paths_do_not_escape_checkout_or_follow_siblings(self):
        self.rows[0]['directory'] = '../outside'; self.save()
        with self.assertRaises(ValueError):
            discover(self.root, 'mobile')
        self.rows[0]['directory'] = '/tmp'; self.save()
        with self.assertRaises(ValueError):
            discover(self.root, 'mobile')
        self.rows[0]['directory'] = 'escape'; (self.root / 'escape').symlink_to('/tmp'); self.save()
        with self.assertRaises(ValueError):
            discover(self.root, 'mobile')

    def test_structure_checker_precedes_smoke_and_all_broad_suites(self):
        data = dict(schema=1, suites=[dict(row, smoke_args=['--profile', 'smoke']) for row in self.rows],
                    test_structure=dict(command=['-m', 'project.check_tests', '--check'], interpreter='host'))
        (self.root / 'build-tests.json').write_text(json.dumps(data))
        result = phases(self.root, 'mobile', {'host': '/host/python', 'project': '/project/python'},
                        ('runner.py', '{directory}'))
        self.assertEqual([p.id for p in result], ['test-structure','shared.smoke','app.smoke','shared','app'])
        self.assertEqual(result[0].kind, 'setup')
        self.assertEqual(result[0].argv, ('/host/python','-m','project.check_tests','--check'))
        self.assertIn('test-structure', result[1].dependencies)
        self.assertIn('shared.smoke', result[2].dependencies)
        for phase in result[3:]:
            self.assertTrue({'test-structure','shared.smoke','app.smoke'} <= set(phase.dependencies))

    def test_invalid_structure_contract_and_missing_checker_interpreter_fail_planning(self):
        data = dict(schema=1, suites=self.rows, test_structure={'command':'not argv','interpreter':'host'})
        (self.root / 'build-tests.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'test_structure'):
            discover(self.root, 'mobile')
        data['test_structure'] = dict(command=['validator.py'], interpreter='missing')
        (self.root / 'build-tests.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'structure checker interpreter'):
            phases(self.root, 'mobile', {'host':'host','project':'project'}, ('runner','{directory}'))

    def test_headless_discovery_imports_no_application_or_qt(self):
        result = subprocess.run([sys.executable, '-c', 'import sys; import build_manager.test_manifest; '
            'assert not any(x.startswith(("PySide6", "Scripts", "mobile")) for x in sys.modules)'],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
