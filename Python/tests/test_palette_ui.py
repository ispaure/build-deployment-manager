"""Native palette changes refresh cached local styles without resetting views."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
import unittest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QPushButton, QWidget
from build_manager import Phase, Plan
from build_manager.palette_ui import install_palette_refresh
from build_manager.ui_components import style_button
from build_manager.workflow_ui import WorkflowFlow


class PaletteRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        original = QPalette(self.app.palette())
        def restore():
            self.app.setPalette(original)
            self.app.processEvents()
        self.addCleanup(restore)
        self.controller = install_palette_refresh(self.app)

    def test_existing_primary_button_refreshes_to_new_accent(self):
        button = style_button(QPushButton('Continue'), 'primary')
        self.addCleanup(button.close)
        button.resize(240, 44)
        button.show()
        for accent in ('#ed7a23', '#844dbf', '#ed7a23'):
            palette = QPalette(self.app.palette())
            palette.setColor(QPalette.ColorRole.Highlight, QColor(accent))
            self.app.setPalette(palette)
            for _ in range(3):
                self.app.processEvents()
            self.assertEqual(button.grab().toImage().pixelColor(8, 8).name(), accent)
            self.assertTrue(button.updatesEnabled())
        self.assertIs(install_palette_refresh(self.app), self.controller)

    def test_refresh_does_not_call_application_methods_named_update(self):
        class DataView(QWidget):
            def update(self, data):
                raise AssertionError('Theme refresh must call QWidget.update, not a data API')
        widget = DataView()
        self.addCleanup(widget.close)
        widget.setStyleSheet('background: palette(base)')
        widget.show()
        self.controller.schedule(force=True)
        self.controller.timer.stop()
        self.controller.refresh()
        self.assertTrue(widget.updatesEnabled())

    def test_palette_refresh_keeps_selection_manual_zoom_and_disabled_updates(self):
        plan = Plan('Fixture', 'Test', {}, (Phase('test', (sys.executable, '-V'), '.'),), '.')
        view = WorkflowFlow(graph_only=True)
        self.addCleanup(view.close)
        view.reset(plan)
        view.resize(600, 400)
        view.show()
        view.select('test')
        view.scroll.zoom(1.1)
        self.app.processEvents()
        scale = view.scroll.transform().m11()
        card = view.canvas.cards['test'][0]
        paused = QWidget()
        self.addCleanup(paused.close)
        paused.show()
        paused.setUpdatesEnabled(False)
        palette = QPalette(self.app.palette())
        palette.setColor(QPalette.ColorRole.Window, QColor('#222222'))
        self.app.setPalette(palette)
        for _ in range(3):
            self.app.processEvents()
        self.assertEqual(view.selected, 'test')
        self.assertIs(view.canvas.cards['test'][0], card)
        self.assertTrue(card.isChecked())
        self.assertEqual(view.scroll.transform().m11(), scale)
        self.assertTrue(view.updatesEnabled())
        self.assertFalse(paused.updatesEnabled())
