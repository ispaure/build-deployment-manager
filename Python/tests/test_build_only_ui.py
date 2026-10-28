"""Build intent uses project preparation without tests or external effects."""
from dataclasses import replace
import unittest
from unittest.mock import Mock

from build_manager import Phase, Plan
from build_manager.ui import ManagerPanel
from build_manager.workflows import require_build_only
import test_ui as fixtures
from test_journeys import CAPABILITY


class BuildOnlyTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ManagerUITests.setUpClass.__func__)
    setUp = fixtures.ManagerUITests.setUp
    inspect = fixtures.ManagerUITests.inspect
    finish = fixtures.ManagerUITests.finish

    def panel(self, effect='build'):
        project = fixtures.OtherProject(self.root, effect=effect)
        project.operations = ('Test', 'Build')
        project.journey_capability = CAPABILITY
        project.make_plan = Mock(wraps=project.make_plan)
        project.make_journey = Mock(side_effect=AssertionError('Build is not a delivery journey'))
        panel = ManagerPanel(project)
        self.addCleanup(panel.close)
        panel.configuration.choose_goal('build')
        return panel

    def test_build_selection_ignores_remembered_delivery_and_survives_restore(self):
        panel = self.panel()
        panel.destination_checks['firebase'].setChecked(True)
        panel.pattern.setText('old-test-filter.py')
        choices = panel.choices()
        self.assertEqual(choices['goal'], 'build')
        self.assertEqual(choices['operation'], 'Build')
        self.assertEqual(choices['suite'], '')
        panel.configuration.choose_goal('deliver')
        panel.configuration.restore_choices(choices)
        self.assertEqual(panel.choices(), choices)
        self.assertTrue(panel.configuration.guided.isHidden())
        self.assertFalse(panel.configuration.legacy.isHidden())
        self.assertTrue(panel.configuration.sections['delivery'].isHidden())
        self.assertIn('without running tests', panel.readiness.text())
        self.inspect(panel)
        args, kwargs = panel.project.make_plan.call_args
        self.assertEqual(args[0], 'Build')
        self.assertEqual(kwargs['pattern'], '')
        self.assertNotIn('suite', kwargs)
        panel.project.make_journey.assert_not_called()
        self.assertEqual(panel.start.text(), 'Start build')
        panel.run_plan()
        self.assertEqual(self.finish(panel)['status'], 'passed')

    def test_review_rejects_effects_outside_build_and_inspect(self):
        for effect in ('test', 'deploy', 'upload', 'publish', 'dispatch'):
            with self.subTest(effect=effect):
                panel = self.panel(effect)
                self.inspect(panel)
                self.assertIsNone(panel.plan)
                self.assertFalse(panel.start.isEnabled())
                self.assertIn('Build only requires', panel.status.text())

    def test_guard_checks_explicit_and_inherited_effects(self):
        phase = Phase('build', ('fixture',), str(self.root))
        plan = Plan('Fixture', 'Build', {}, (phase,), str(self.root), effect='build')
        require_build_only(plan)
        for effect in ('test', 'deploy', 'upload', 'publish', 'dispatch'):
            with self.subTest(effect=effect), self.assertRaises(ValueError):
                require_build_only(replace(plan, phases=(phase, replace(phase, id='other', effect=effect))))
        require_build_only(replace(plan, phases=(phase, replace(phase, id='inspect', effect='inspect'))))
