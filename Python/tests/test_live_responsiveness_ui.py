"""Live bursts yield to input and selection clearing preserves the current scope."""
import json
import unittest
from unittest.mock import patch

from PySide6.QtCore import QTimer, Qt, QPoint
from PySide6.QtTest import QTest
import test_review_workspace_ui as fixture


class LiveResponsivenessTests(unittest.TestCase):
    setUpClass = classmethod(fixture.ReviewWorkspaceTests.setUpClass.__func__)
    setUp = fixture.ReviewWorkspaceTests.setUp
    tearDown = fixture.ReviewWorkspaceTests.tearDown
    def test_growing_case_snapshots_are_coalesced_before_recursive_redaction(self):
        panel = self.panel
        panel.run_view.reset(self.plan)
        events = [dict(type='phase', id='android', status='running',
            live_tests=[dict(name=f'test_{case}', status='passed') for case in range(100)],
            current_test=dict(name=f'active_{index}', status='running')) for index in range(100)]
        raw = ('\n'.join(json.dumps(event) for event in events) + '\n').encode()
        with patch.object(panel.process, 'readAllStandardOutput', side_effect=[raw] + [b''] * 1000), \
             patch.object(panel, 'redacted_data', wraps=panel.redacted_data) as redact:
            panel.read_output()
            while '\n' in panel.session.buffer:
                panel.read_output()
            self.assertEqual(redact.call_count, 0)
            panel.live_update_timer.stop()
            panel.flush_live_updates()
            self.assertEqual(sum(len(call.args) == 1 for call in redact.call_args_list), 1)
            self.assertEqual(panel.run_view.facts['android']['current_test']['name'], 'active_99')
            self.assertEqual(len(panel.run_view.facts['android']['live_tests']), 100)

    def test_stream_burst_yields_before_draining_and_coalesces_hidden_review(self):
        panel = self.panel
        panel.run_view.reset(self.plan)
        panel.stages.setCurrentIndex(2)
        events = [dict(type='phase', id='android', status='running',
                       current_test=dict(name=f'test_{i}', status='running')) for i in range(1000)]
        raw = ('\n'.join(json.dumps(event) for event in events) + '\n').encode()
        heartbeat = []
        with patch.object(panel.process, 'readAllStandardOutput', side_effect=[raw] + [b''] * 1000), \
             patch.object(panel.run_view, 'refresh_inspector', wraps=panel.run_view.refresh_inspector) as render, \
             patch.object(panel.review_workspace, 'set_facts', wraps=panel.review_workspace.set_facts) as review:
            panel.read_output()
            self.assertIn('\n', panel.session.buffer)
            self.assertEqual(render.call_count, 0)
            def resize():
                heartbeat.append(bool(panel.session.buffer))
                panel.resize(1080, 760)
            QTimer.singleShot(0, resize)
            for _ in range(100):
                self.app.processEvents()
                if not panel.session.buffer:
                    break
            self.assertEqual(heartbeat, [True])
            self.assertEqual(panel.session.buffer, '')
            panel.live_update_timer.stop()
            panel.flush_live_updates()
            self.assertLess(render.call_count, 20)
            self.assertEqual(review.call_count, 0)
            self.assertEqual(panel.run_view.facts['android']['current_test']['name'], 'test_999')
            panel.stages.setCurrentIndex(1)
            self.assertEqual(review.call_count, 1)

    def test_clicking_background_clears_step_without_leaving_current_view(self):
        panel = self.panel
        view = panel.run_view
        view.reset(self.plan)
        panel.stages.setCurrentIndex(2)
        view.run_choices.flow.open_group('platform.android')
        view.flow.select('android')
        self.app.processEvents()
        group = view.run_choices.flow.selected
        keys = set(view.scoped_facts())
        self.assertEqual(keys, {'android'})
        QTest.mouseClick(view.flow.canvas, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        self.assertEqual(view.selected, '')
        self.assertEqual(view.flow.selected, '')
        self.assertEqual(view.run_choices.flow.selected, group)
        self.assertEqual(view.run_choices.flow.pages.currentIndex(), 1)
        expected = set(view.run_choices.flow.group_keys(group))
        self.assertEqual(set(view.scoped_facts()), expected)
        self.assertEqual(view.substeps.topLevelItemCount(), len(expected))
        for key, row in view.rows.items():
            self.assertEqual(row.isHidden(), key not in expected)
        self.view.flow.open_group('platform.android')
        self.view.graph.select('android')
        QTest.mouseClick(self.view.graph.canvas, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        self.assertEqual(self.view.selected, '')
        self.assertEqual(self.view.flow.pages.currentIndex(), 1)
        self.assertIn('android', self.view.rows)
