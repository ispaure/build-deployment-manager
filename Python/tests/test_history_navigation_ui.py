"""Returning to runs is searchable without launching or implicitly resuming work."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtWidgets import QApplication
from build_manager.history_ui import RunHistoryView


class HistoryNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.view = RunHistoryView()
        self.addCleanup(self.view.close)
        self.rows = [dict(path='/retained/' + status + '/result.json', operation='Deliver app', status=status)
            for status in ('awaiting_review', 'passed', 'failed', 'unknown', 'unreadable')]
        self.view.set_rows(self.rows)

    def visible(self):
        return [self.view.tree.topLevelItem(i) for i in range(self.view.tree.topLevelItemCount())
            if not self.view.tree.topLevelItem(i).isHidden()]

    def test_attention_filter_and_search_keep_unknown_and_corrupt_runs_visible(self):
        self.view.filter.setCurrentIndex(1)
        self.assertEqual(len(self.visible()), 4)
        self.view.search.setText('UNKNOWN')
        self.assertEqual(len(self.visible()), 1)
        self.assertEqual(self.visible()[0].text(4), 'Check provider')
        self.view.search.setText('unreadable')
        self.assertEqual(self.visible()[0].text(4), 'Inspect record')

    def test_refresh_preserves_selection_but_filter_cannot_leave_a_hidden_action_target(self):
        item = self.view.tree.topLevelItem(1)
        self.view.tree.setCurrentItem(item)
        self.view.set_rows(list(reversed(self.rows)))
        self.assertEqual(self.view.tree.currentItem().text(2), 'Completed')
        self.view.filter.setCurrentIndex(1)
        self.assertIsNone(self.view.tree.currentItem())
        self.view.search.setText('no such run')
        self.assertEqual(self.view.hint.text(), 'No matching runs')

    def test_ready_approval_and_success_have_distinct_states_and_actions(self):
        self.assertEqual(self.view.tree.topLevelItem(0).text(2), 'Needs approval')
        self.assertEqual(self.view.tree.topLevelItem(0).text(4), 'Review delivery')
        self.assertEqual(self.view.tree.topLevelItem(1).text(4), 'View results')
        self.assertFalse(self.view.tree.topLevelItem(0).icon(2).isNull())
