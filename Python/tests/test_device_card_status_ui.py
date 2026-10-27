"""A successful recipient stays successful while another device reconnects."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import json
import sys
from tempfile import TemporaryDirectory
import unittest

from PySide6.QtWidgets import QApplication, QLabel
from build_manager import Phase, Plan
from build_manager.run_ui import RunView


class DeviceCardStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_retained_device_success_does_not_include_other_recipient_wait(self):
        with TemporaryDirectory() as directory:
            phases = [Phase('build', (sys.executable, '-V'), directory, effect='build',
                            label='Build APK', kind='build')]
            recipients = {}
            for identity, label in [('boox-id', 'NoteAir5C'), ('samsung-id', 'SM-G955W')]:
                connect, install = identity + '.connect', identity + '.install'
                phases += [Phase(connect, (sys.executable, '-V'), directory,
                                 effect='inspect', kind='connection', dependencies=('build',)),
                           Phase(install, (sys.executable, '-V'), directory,
                                 effect='deploy', approval_required=False, dependencies=('build', connect))]
                recipients[identity] = dict(label=label, steps=[connect, install])
            plan = Plan('Fixture', 'devices',
                dict(effective_settings=dict(values=dict(ids=json.dumps(list(recipients))))),
                tuple(phases), directory,
                journey=dict(schema=1, goal='deliver', platforms={}, destinations=dict(devices=dict(
                    identity='Selected devices', platforms=[], testing_optional=True,
                    steps=['boox-id.install', 'samsung-id.install'], recipients=recipients))))
            # A retained plan's actual policy must win over missing/new descriptor defaults.
            capability = dict(schema=1, platforms={}, destinations=dict(devices=dict(
                label='Android devices', platforms=['android'], testing_optional=True, recipient_field='ids')))
            view = RunView()
            self.addCleanup(view.close)
            view.reset(plan, capability=capability)
            for key in ('build', 'boox-id.connect', 'boox-id.install'):
                view.update_phase(dict(id=key, status='passed', seconds=1))
            view.update_phase(dict(id='samsung-id.connect', status='retrying', seconds=2))
            grouped = view.run_choices.flow
            self.assertEqual(grouped.canvas.states['deliver.devices.0'][0], 'passed')
            self.assertEqual(grouped.canvas.states['deliver.devices.1'][0], 'retrying')
            self.assertFalse(grouped.canvas.cards['deliver.devices.0'][0].findChild(QLabel, 'approvalBadge'))
            self.assertFalse(grouped.canvas.cards['deliver.devices.1'][0].findChild(QLabel, 'approvalBadge'))
            grouped.open_group('deliver.devices.0')
            self.assertEqual(set(view.run_choices.rows), {'boox-id.connect', 'boox-id.install'})
            self.assertEqual(grouped.group_keys('deliver.devices.0'), ('boox-id.connect', 'boox-id.install'))
            grouped.open_group('deliver.devices.1')
            self.assertEqual(set(view.run_choices.rows), {'samsung-id.connect', 'samsung-id.install'})
