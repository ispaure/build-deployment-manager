"""An invisible footer page must not set the window's minimum width."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QHBoxLayout, QVBoxLayout
from build_manager.ui_components import CurrentPageStack, ViewportStack


class CurrentFooterPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_hidden_stage_does_not_constrain_visible_viewport(self):
        stack = ViewportStack()
        self.addCleanup(stack.close)
        short, wide = QWidget(), QWidget()
        short.setMinimumWidth(120)
        wide.setMinimumWidth(1400)
        stack.addWidget(short)
        stack.addWidget(wide)
        self.assertEqual(stack.minimumSizeHint().width(), 120)
        stack.setCurrentIndex(1)
        self.assertEqual(stack.minimumSizeHint().width(), 1400)

    def test_hidden_wide_page_does_not_widen_short_page_or_discard_active_minima(self):
        window = QWidget()
        self.addCleanup(window.close)
        stack = CurrentPageStack()
        layout = QVBoxLayout(window)
        layout.addWidget(stack)
        short = QWidget()
        short_layout = QHBoxLayout(short)
        short_layout.addWidget(QPushButton('Review'))
        wide = QWidget()
        wide_layout = QHBoxLayout(wide)
        for index in range(4):
            button = QPushButton(f'Action {index}')
            button.setMinimumWidth(350)
            wide_layout.addWidget(button)
        stack.addWidget(short)
        stack.addWidget(wide)
        window.resize(640, 240)
        window.show()
        self.app.processEvents()
        self.assertEqual(window.width(), 640)
        self.assertLess(stack.minimumSizeHint().width(), 640)
        stack.setCurrentWidget(wide)
        self.app.processEvents()
        self.assertGreaterEqual(stack.minimumSizeHint().width(), 1400)
        self.assertGreaterEqual(window.width(), 1400)
        stack.setCurrentWidget(short)
        self.app.processEvents()
        window.resize(640, 240)
        self.app.processEvents()
        self.assertEqual(window.width(), 640)

    def test_empty_footer_can_be_measured(self):
        stack = CurrentPageStack()
        self.addCleanup(stack.close)
        self.assertEqual(stack.minimumSizeHint().width(), 0)
        self.assertEqual(stack.sizeHint().height(), 0)
