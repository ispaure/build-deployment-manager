"""Keyboard defaults, descriptive approval controls and narrow activity layouts."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox
from build_manager.approval_ui import EffectReviewDialog
from build_manager.history_ui import RunHistoryView
import test_running_states_ui as fixtures


class AccessibilityPassTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_approval_keyboard_selects_explicitly_and_escape_rejects(self):
        dialog = EffectReviewDialog('Retained evidence', steps=('deliver',), cards=[dict(step='deliver',
            title='Deliver build', destinations=['provider:' + 'long-name-'*25], platforms=['ios'],
            recipients=[('Devices', 'QA iPhone')], choices=[], builds=[])])
        self.addCleanup(dialog.close)
        dialog.setFont(QFont(dialog.font().family(), 14))
        dialog.resize(640, 540)
        dialog.show()
        self.app.processEvents()
        self.assertEqual(dialog.width(), 640)
        control = dialog.approvals['deliver']
        self.assertIn('QA iPhone', control.accessibleDescription())
        control.setFocus()
        QTest.keyClick(control, Qt.Key.Key_Space)
        self.assertTrue(control.isChecked())
        dialog.evidence_toggle.setFocus()
        QTest.keyClick(dialog.evidence_toggle, Qt.Key.Key_Space)
        self.assertFalse(dialog.evidence.isHidden())
        buttons = dialog.findChild(QDialogButtonBox)
        self.assertTrue(buttons.button(QDialogButtonBox.StandardButton.Cancel).isDefault())
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)

    def test_find_shortcut_is_scoped_and_preserves_search_text(self):
        view = RunHistoryView()
        self.addCleanup(view.close)
        view.show()
        view.search.setText('release')
        view.tree.setFocus()
        self.app.processEvents()
        self.assertEqual(view.find.key(), QKeySequence(QKeySequence.StandardKey.Find))
        view.find.activated.emit()
        self.assertEqual(view.search.selectedText(), 'release')
        self.assertEqual(view.find.context(), Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def test_activity_controls_wrap_instead_of_widening_a_small_window(self):
        case = fixtures.RunningStateTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        view = case.view
        view.setFont(QFont(view.font().family(), 14))
        for key, state in [('android', 'running'), ('ios', 'waiting_resource'), ('firebase', 'awaiting_review')]:
            view.update_phase(dict(id=key, status=state))
        view.resize(640, 620)
        view.show()
        self.app.processEvents()
        self.assertEqual(view.width(), 640)
        for button in view.activity.buttons:
            self.assertLessEqual(button.geometry().right(), view.activity.width())
        self.assertLessEqual(view.activity.columns, 2)
