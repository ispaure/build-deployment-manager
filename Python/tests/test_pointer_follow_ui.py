"""The fitted workflow can be read at full size without losing its corners."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from build_manager import Phase, Plan
from build_manager.workflow_ui import WorkflowFlow


class PointerFollowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.preferences = Path(directory.name) / 'workflow-view.json'
        patcher = patch('build_manager.workflow_map_ui.config_directory', return_value=Path(directory.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.flow = WorkflowFlow(graph_only=True)
        self.addCleanup(self.flow.close)
        phases = tuple(Phase(f'step-{i}', ('fixture',), '.',
                             dependencies=(f'step-{i - 1}',) if i else ())
                       for i in range(12))
        self.plan = Plan('Fixture', 'Inspect', {}, phases, '.')
        self.flow.resize(800, 500)
        self.flow.reset(self.plan)
        self.flow.show()
        for _ in range(5):
            self.app.processEvents()
        self.view = self.flow.scroll

    def test_default_and_saved_preference(self):
        from build_manager.profiles import load_profile
        self.assertFalse(self.flow.follow_mouse.isChecked())
        self.assertFalse(self.view.pointer_follow)
        self.assertFalse(self.preferences.exists())
        fitted = self.view.transform()
        self.move(QPoint(0, 0))
        self.assertEqual(self.view.transform(), fitted)
        for enabled in (True, False):
            self.flow.follow_mouse.click()
            self.flow.reset(self.plan)
            self.assertEqual(self.view.pointer_follow, enabled)
            self.assertEqual(load_profile(self.preferences)['follow_mouse'], enabled)
            reopened = WorkflowFlow(graph_only=True)
            try:
                self.assertEqual(reopened.follow_mouse.isChecked(), enabled)
                self.assertEqual(reopened.scroll.pointer_follow, enabled)
            finally:
                reopened.close()

    def move(self, point):
        event = QMouseEvent(QEvent.Type.MouseMove, QPointF(point), QPointF(point),
                            Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier)
        self.app.sendEvent(self.view.viewport(), event)

    def test_readable_scale_reaches_each_corner_and_restores_on_leave(self):
        self.flow.follow_mouse.click()
        for orientation in ('horizontal', 'vertical'):
            with self.subTest(orientation=orientation):
                self.view.set_orientation(orientation)
                fitted = self.view.transform()
                self.assertLess(fitted.m11(), 1)
                bounds = self.view.viewport().rect()
                # Full edges should already be visible at 20% / 80%, well
                # before the pointer reaches the physical viewport boundary.
                for point in (QPoint(round(bounds.width() * x), round(bounds.height() * y))
                              for x, y in ((.19, .19), (.81, .19), (.19, .81), (.81, .81))):
                    self.move(point)
                    self.assertAlmostEqual(self.view.transform().m11(), 1)
                    visible = self.view.mapToScene(bounds).boundingRect()
                    scene = self.view.sceneRect()
                    # Scrollbar rounding may leave less than two scene pixels.
                    if point.x() < bounds.center().x():
                        self.assertLessEqual(visible.left(), scene.left() + 2)
                    else:
                        self.assertGreaterEqual(visible.right(), scene.right() - 2)
                    if point.y() < bounds.center().y():
                        self.assertLessEqual(visible.top(), scene.top() + 2)
                    else:
                        self.assertGreaterEqual(visible.bottom(), scene.bottom() - 2)
                self.app.sendEvent(self.view.viewport(), QEvent(QEvent.Type.Leave))
                self.assertEqual(self.view.transform(), fitted)
                self.assertTrue(self.view.fit_mode)

    def test_click_does_not_move_card_and_updates_do_not_cancel_following(self):
        self.flow.follow_mouse.click()
        before = self.plan.data()
        self.move(QPoint(0, 0))
        self.flow.set_facts({'step-0': {'status': 'running'}})
        self.app.processEvents()
        self.assertAlmostEqual(self.view.transform().m11(), 1)
        card = self.flow.canvas.cards['step-0'][0]
        point = self.view.mapFromScene(self.view.proxy.mapToScene(QPointF(card.geometry().center())))
        self.assertTrue(self.view.viewport().rect().contains(point))
        QTest.mouseClick(self.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        self.assertEqual(self.flow.selected, 'step-0')
        self.assertAlmostEqual(self.view.transform().m11(), 1)
        self.assertEqual(self.view.mapFromScene(self.view.proxy.mapToScene(
            QPointF(card.geometry().center()))), point)
        self.assertEqual(self.plan.data(), before)

    def test_keyboard_focus_and_resize_restore_the_fitted_map(self):
        self.flow.follow_mouse.click()
        fitted = self.view.transform()
        self.move(QPoint(0, 0))
        card = self.flow.canvas.cards['step-11'][0]
        card.setFocus(Qt.FocusReason.TabFocusReason)
        self.app.processEvents()
        self.assertEqual(self.view.transform(), fitted)
        self.assertTrue(self.view.viewport().rect().contains(self.view.mapFromScene(
            self.view.proxy.mapToScene(QPointF(card.geometry().center())))))
        self.move(QPoint(0, 0))
        self.flow.resize(900, 600)
        self.app.processEvents()
        self.assertIsNone(self.view._pointer_state)
        self.assertLess(self.view.transform().m11(), 1)
        self.assertEqual(self.view.horizontalScrollBar().maximum(), 0)
        self.assertEqual(self.view.verticalScrollBar().maximum(), 0)

    def test_toggle_and_manual_zoom_keep_a_stationary_map(self):
        self.flow.follow_mouse.click()
        fitted = self.view.transform()
        self.move(QPoint(0, 0))
        self.flow.follow_mouse.click()
        self.assertEqual(self.view.transform(), fitted)
        self.move(QPoint(100, 100))
        self.assertEqual(self.view.transform(), fitted)
        self.flow.follow_mouse.click()
        self.move(QPoint(0, 0))
        self.view.zoom(1.2)
        manual = self.view.transform()
        self.move(QPoint(200, 200))
        self.app.sendEvent(self.view.viewport(), QEvent(QEvent.Type.Leave))
        self.assertEqual(self.view.transform(), manual)
        self.assertFalse(self.view.fit_mode)

    def test_section_row_stays_readable_above_the_panning_map(self):
        self.flow.follow_mouse.click()
        from build_manager.proposed_workflow import ProposedStep, ProposedWorkflow
        phases = tuple(ProposedStep(f'step-{i}', f'Check {i}', 'Fixture',
                                   (f'step-{i - 1}',) if i else (),
                                   section='source' if i == 0 else 'platforms' if i < 8 else 'delivery')
                       for i in range(12))
        self.flow.reset(ProposedWorkflow(phases))
        self.app.processEvents()
        row = self.view.sticky_sections
        labels = self.view.sticky_labels
        # Headers repeat for separate dependency columns. Each must stay with
        # its own band rather than being combined into equal-width categories.
        self.assertEqual([label.text() for label in labels],
                         [header.text() for header in self.flow.canvas.headers])
        self.assertEqual(set(label.text() for label in labels), {'Source', 'Testing', 'Delivery'})
        fonts = [label.fontMetrics().height() for label in labels]

        def assert_aligned():
            self.assertTrue(row.isVisible())
            self.assertEqual([label.fontMetrics().height() for label in labels], fonts)
            vertical = self.flow.canvas.vertical
            if vertical:
                self.assertLess(row.geometry().right(), self.view.viewport().geometry().left())
                self.assertEqual(row.height(), self.view.viewport().height())
            else:
                self.assertLess(row.geometry().bottom(), self.view.viewport().geometry().top())
                self.assertEqual(row.width(), self.view.viewport().width())
            for header, label in zip(self.flow.canvas.headers, labels):
                band = self.view.mapFromScene(self.view.proxy.mapRectToScene(
                    QRectF(self.flow.canvas.section_rect(header)))).boundingRect()
                low = max(0, band.top() if vertical else band.left())
                high = min(row.height() if vertical else row.width(),
                           (band.bottom() if vertical else band.right()) + 1)
                self.assertEqual(label.isVisible(), high > low)
                if high > low:
                    self.assertEqual(label.y() if vertical else label.x(), low)
                    self.assertEqual(label.height() if vertical else label.width(), high - low)

        for orientation in ('horizontal', 'vertical'):
            self.view.set_orientation(orientation)
            assert_aligned()
            for point in (QPoint(0, 0), self.view.viewport().rect().bottomRight()):
                self.move(point)
                assert_aligned()
            self.app.sendEvent(self.view.viewport(), QEvent(QEvent.Type.Leave))
            assert_aligned()
            self.view.zoom(1.6)
            assert_aligned()
            for bar in (self.view.horizontalScrollBar(), self.view.verticalScrollBar()):
                bar.setValue((bar.minimum() + bar.maximum()) // 2)
            assert_aligned()
        self.flow.resize(1100, 700)
        self.app.processEvents()
        assert_aligned()
        self.flow.reset(ProposedWorkflow(phases[:1]))
        self.app.processEvents()
        self.assertEqual(len(self.view.sticky_labels), 1)
        self.assertEqual(self.view.sticky_labels[0].text(), 'Source')
