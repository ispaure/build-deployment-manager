"""Retained approval scope, identity presentation and compact dialog behavior."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel

from build_manager.approval_summary import approval_cards
from build_manager.ui import EffectReviewDialog, ManagerPanel
from test_journeys import integrated
from test_ui import OtherProject


class ApprovalCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        original = integrated(self.root)
        self.plan = replace(original, source=dict(original.source, run_overrides={
            'devices': '["QA iPhone", "Release iPad"]', 'track': 'beta', 'notes': 'Technical only'}),
            journey=dict(original.journey, destinations={name: dict(row,
                platforms=['ios' if name == 'testflight' else 'android'])
                for name, row in original.journey['destinations'].items()}))
        self.fields = [dict(id='devices', label='Devices', kind='multiselect', destinations=['testflight'],
            operations=['deploy-build']),
            dict(id='track', label='Track', kind='choice', destinations=['firebase'],
                options={'beta': 'Beta testers'}, default='beta'),
            dict(id='notes', label='Release notes', kind='multiline')]
        self.artifact = dict(path='/retained/identity.json', original_path='/build/identity.json', sha256='a'*64)
        self.report = dict(phases=[dict(id='prepare', status='passed', artifacts=[self.artifact]),
            dict(id='unrelated', status='passed', artifacts=[dict(path='/wrong.zip', sha256='b'*64)])])
        self.previews = {'/retained/identity.json': dict(package='App.ipa', version='1.2.3', build_number=42,
            technical={'command': 'not a card identity'})}

    def dialog(self, steps=('firebase', 'testflight')):
        cards = approval_cards(self.plan, self.report, steps, self.fields, self.previews)
        dialog = EffectReviewDialog('Full paths, checksums and retained JSON', steps=steps,
            cards=cards, source='Latest commit · abc123')
        self.addCleanup(dialog.close)
        return dialog

    def test_exact_eligible_steps_scope_recipients_and_shared_build_identity(self):
        cards = approval_cards(self.plan, self.report, ('testflight',), self.fields, self.previews)
        self.assertEqual([card['step'] for card in cards], ['testflight'])
        card = cards[0]
        self.assertEqual(card['destinations'], ['testflight:fixture/app/testers'])
        self.assertEqual(card['recipients'], [('Devices', 'QA iPhone, Release iPad')])
        self.assertEqual(card['choices'], [])
        self.assertEqual([build['path'] for build in card['builds']], ['/retained/identity.json'])
        self.assertIn(('Version', '1.2.3'), card['builds'][0]['identity'])
        self.assertNotIn('technical', str(card['builds'][0]['identity']))

    def test_only_transitive_prerequisite_files_belong_to_each_action(self):
        plan = replace(self.plan, phases=(*self.plan.phases[:-1],
            replace(self.plan.phases[-1], dependencies=('ios',))))
        cards = approval_cards(plan, self.report, ('firebase', 'testflight'), self.fields)
        self.assertEqual(len(cards[0]['builds']), 1)
        self.assertEqual(cards[1]['builds'], [])
        self.assertEqual(cards[0]['choices'], [('Track', 'Beta testers')])
        self.assertEqual(cards[0]['recipients'], [])

    def test_cards_keep_explicit_selection_cancel_default_and_expandable_evidence(self):
        dialog = self.dialog()
        dialog.show()
        self.app.processEvents()
        buttons = dialog.findChild(QDialogButtonBox)
        approve = next(b for b in buttons.buttons() if b.text().startswith('Approve'))
        self.assertTrue(buttons.button(QDialogButtonBox.StandardButton.Cancel).isDefault())
        self.assertFalse(approve.isEnabled())
        self.assertFalse(approve.autoDefault())
        self.assertFalse(dialog.evidence.isVisible())
        dialog.evidence_toggle.click()
        self.assertTrue(dialog.evidence.isVisible())
        dialog.approvals['testflight'].setChecked(True)
        self.assertTrue(approve.isEnabled())
        self.assertEqual(approve.text(), 'Approve 1 selected action')
        self.assertFalse(dialog.approvals['firebase'].isChecked())
        self.assertTrue(dialog.cards['testflight'].property('selected'))
        dialog.evidence_toggle.click()
        self.assertFalse(dialog.evidence.isVisible())

    def test_small_dialog_keeps_footer_and_card_values_readable(self):
        dialog = self.dialog()
        dialog.setFont(QFont(dialog.font().family(), 14))
        dialog.resize(640, 540)
        dialog.show()
        self.app.processEvents()
        self.assertEqual(dialog.width(), 640)
        footer = dialog.findChild(QDialogButtonBox)
        self.assertLessEqual(footer.geometry().bottom(), dialog.height())
        text = '\n'.join(label.text() for label in dialog.cards['testflight'].findChildren(QLabel))
        for value in ('QA iPhone', 'Release iPad', 'App.ipa', '1.2.3', '42', 'ios'):
            self.assertIn(value, text)
        self.assertNotIn('Technical only', text)
        self.assertGreater(dialog.cards['testflight'].width(), 400)

    def test_manager_supplies_retained_redacted_values_instead_of_live_form(self):
        project = OtherProject(self.root)
        project.run_fields = self.fields
        panel = ManagerPanel(project)
        self.addCleanup(panel.close)
        identity = self.root / 'identity.json'
        identity.write_text('{"package":"App.ipa","version":"1.2.3","detail":"password=privatevalue"}')
        report = dict(phases=[dict(id='prepare', status='passed', artifacts=[dict(
            self.artifact, path=str(identity))])])
        with patch('build_manager.ui.EffectReviewDialog') as dialog:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            self.assertFalse(panel.confirm_continuation(self.plan, report, ('testflight',)))
        data = dialog.call_args.kwargs
        self.assertEqual(data['cards'][0]['recipients'], [('Devices', 'QA iPhone, Release iPad')])
        self.assertIn('fixed', data['source'])
        self.assertNotIn('privatevalue', str(dialog.call_args))
        self.assertIn(('Version', '1.2.3'), data['cards'][0]['builds'][0]['identity'])

    def test_legacy_dialog_never_invents_destinations_or_checks_actions(self):
        dialog = EffectReviewDialog('Retained evidence', steps=('legacy',))
        self.addCleanup(dialog.close)
        self.assertFalse(dialog.approvals['legacy'].isChecked())
        text = '\n'.join(label.text() for label in dialog.cards['legacy'].findChildren(QLabel))
        self.assertIn('Destination · Not declared', text)
        self.assertIn('No prerequisite artifacts recorded', text)


if __name__ == '__main__':
    unittest.main()
