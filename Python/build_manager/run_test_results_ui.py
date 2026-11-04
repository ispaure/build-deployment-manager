"""Test and timing presentation from explicit scoped run facts; no coordinator access."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QStyle, QStyledItemDelegate, QStyleOptionProgressBar)
from .test_results import stage_label
from .workflow_presentation import format_elapsed_time
from .ui_components import search_shortcut, WrappingLayout


class TimingBarDelegate(QStyledItemDelegate):
    """Paint visible duration cells without allocating one QWidget per test."""
    def paint(self, painter, option, index):
        progress = index.data(Qt.ItemDataRole.UserRole)
        if progress is None:
            return super().paint(painter, option, index)
        bar = QStyleOptionProgressBar()
        bar.rect = option.rect.adjusted(3, 3, -3, -3)
        bar.palette = option.palette
        bar.state = option.state
        bar.minimum, bar.maximum, bar.progress = 0, 1000, progress
        bar.textVisible = False
        option.widget.style().drawControl(QStyle.ControlElement.CE_ProgressBar, bar, painter, option.widget)


class TestResultsView(QWidget):
    problems_requested = Signal()
    timings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.totals_widget = QWidget(self)
        totals_layout = QVBoxLayout(self.totals_widget)
        totals_layout.setContentsMargins(0, 0, 0, 0)
        self.result_counts = QLabel('No test reports yet. Counts appear as tests finish.')
        self.result_counts.setWordWrap(True)
        self.result_counts.setAccessibleName('Reported test totals')
        totals = WrappingLayout()
        self.count_cards = {}
        for state, label in (('passed', 'Passed'), ('failed', 'Failed'), ('error', 'Errors'), ('skipped', 'Skipped')):
            card = QLabel(label + ' —')
            card.setAlignment(Qt.AlignmentFlag.AlignLeft)
            card.setMargin(2)
            self.count_cards[state] = (card, label)
            totals.addWidget(card)
        totals_layout.addLayout(totals)
        totals_layout.addWidget(self.result_counts)
        self.actions_widget = QWidget(self)
        actions_layout = QVBoxLayout(self.actions_widget)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        result_actions = WrappingLayout()
        problems = self.problems_button = QPushButton('Show failed tests')
        problems.setEnabled(False)
        problems.clicked.connect(self.problems_requested.emit)
        timing_button = QPushButton('See slowest tests')
        timing_button.clicked.connect(self.timings_requested.emit)
        result_actions.addWidget(problems)
        result_actions.addWidget(timing_button)
        result_actions.addStretch()
        actions_layout.addLayout(result_actions)
        test_layout = QVBoxLayout(self)
        filters = WrappingLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('Find a test, suite or failure message…')
        self.search.setAccessibleName('Search individual tests')
        self.find_tests = search_shortcut(self, self.search)
        self.search.setClearButtonEnabled(True)
        self.filter = QComboBox()
        self.filter.addItems(['All tests', 'Problems', 'Passed', 'Skipped'])
        self.filter.setAccessibleName('Test outcome filter')
        self.search.textChanged.connect(self.filter_tests)
        self.filter.currentTextChanged.connect(self.filter_tests)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.filter)
        self.stage_filter = QComboBox()
        self.stage_filter.addItems(['All stages', 'Smoke', 'Regression', 'Extended', 'Unspecified'])
        self.stage_filter.setAccessibleName('Test execution stage filter')
        self.stage_filter.setToolTip('Execution scope reported by the runner. Unspecified means no stage was supplied.')
        self.stage_filter.currentTextChanged.connect(self.filter_tests)
        self.stage_filter.hide()
        filters.addWidget(self.stage_filter)
        self.test_matches = QLabel()
        self.test_matches.setAccessibleName('Visible test count')
        filters.addWidget(self.test_matches)
        test_layout.addLayout(filters)
        self.test_summary = QLabel('Individual cases appear when a declared JUnit report is captured.')
        self.test_summary.setWordWrap(True)
        test_layout.addWidget(self.test_summary)
        self.tests = QTreeWidget()
        self.tests.setHeaderLabels(['Test', 'Outcome', 'Duration', 'Suite / class', 'Step', 'Stage'])
        self.tests.setAccessibleName('Individual test outcomes and timings')
        self.tests.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tests.setColumnWidth(0, 240)
        self.tests.setColumnWidth(1, 80)
        self.tests.header().moveSection(5, 2)
        self.tests.headerItem().setToolTip(5, 'Execution scope: Smoke, Regression or Extended. Unspecified means the report has no stage.')
        self.tests.setColumnWidth(5, 95)
        self.tests.setColumnHidden(5, True)
        self.tests.setColumnWidth(2, 80)
        self.tests.setColumnWidth(3, 130)
        self.tests.setAlternatingRowColors(True)
        self.tests.currentItemChanged.connect(self.show_test)
        test_layout.addWidget(self.tests, 2)
        self.test_detail = QPlainTextEdit()
        self.test_detail.setReadOnly(True)
        self.test_detail.setAccessibleName('Selected test failure or skip details')
        test_layout.addWidget(self.test_detail, 1)
        self.timing_page = timing = QWidget(self)
        timing_layout = QVBoxLayout(timing)
        self.timing_summary = QLabel('Timing appears when individual test reports include durations.')
        self.timing_summary.setWordWrap(True)
        timing_layout.addWidget(self.timing_summary)
        self.timings = QTreeWidget()
        self.timings.setHeaderLabels(['Test (slowest first)', 'Duration', 'Suite / class', 'Step', 'Relative duration', 'Stage'])
        self.timings.setAccessibleName('Individual test timing profile')
        self.timings.header().setMinimumSectionSize(65)
        self.timings.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.timings.setColumnWidth(0, 240)
        self.timings.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.timings.header().moveSection(5, 2)
        self.timings.setColumnWidth(5, 95)
        self.timings.setColumnHidden(5, True)
        self.timings.setColumnWidth(2, 110)
        self.timings.setColumnWidth(3, 95)
        self.timings.header().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.timings.setItemDelegateForColumn(4, TimingBarDelegate(self.timings))
        timing_layout.addWidget(self.timings)
        note = QLabel('Reported test time is the sum of case durations. Parallel tests can overlap; this differs from active run time. Missing durations are excluded from averages.')
        note.setWordWrap(True)
        timing_layout.addWidget(note)

    def present(self, scope, *, selected=False):
        signature = (selected, tuple((key, tuple((case.get('name'), case.get('status'),
                                      case.get('seconds'), case.get('message'),
                                      case.get('suite'), case.get('classname'), case.get('stage'))
                                     for case in fact.get('tests', ())))
                          for key, fact in scope.items()))
        interim = sum(len(fact.get('live_tests', ())) for fact in scope.values())
        if getattr(self, 'final_tests_signature', None) == signature:
            # Interim case snapshots do not change final rows or timing bars.
            # Rebuilding thousands of native items here stalls resize/input.
            self.present_totals(self.final_counts, interim)
            return False
        self.final_tests_signature = signature
        current = self.tests.currentItem()
        previous = (current.text(4), current.data(0, Qt.ItemDataRole.UserRole)) if current else None
        self.test_detail.clear()
        self.tests.clear()
        counts = {}
        measured = []
        missing = 0
        for key, fact in scope.items():
            for case in fact.get('tests', []):
                if case.get('seconds') is None:
                    missing += 1
                else:
                    measured.append((case['seconds'], case, key))
                status = case['status']
                counts[status] = counts.get(status, 0) + 1
                item = QTreeWidgetItem([case['name'], status, format_elapsed_time(case['seconds']),
                                       ' / '.join(filter(None, [case['suite'], case['classname']])), key, stage_label(case)])
                item.setData(0, Qt.ItemDataRole.UserRole, case)
                self.tests.addTopLevelItem(item)
                if previous == (key, case):
                    self.tests.setCurrentItem(item)
        self.final_counts = counts
        self.present_totals(counts, interim)
        self.timings.clear()
        longest = max((row[0] for row in measured), default=0)
        for seconds, case, key in sorted(measured, key=lambda row: row[0], reverse=True):
            item = QTreeWidgetItem([case['name'], format_elapsed_time(seconds),
                ' / '.join(filter(None, [case['suite'], case['classname']])), key, '', stage_label(case)])
            self.timings.addTopLevelItem(item)
            item.setData(4, Qt.ItemDataRole.UserRole, round(1000 * seconds / longest) if longest else 0)
            item.setData(4, Qt.ItemDataRole.AccessibleTextRole, case['name'] + ': ' + format_elapsed_time(seconds))
            item.setToolTip(4, 'Relative to the slowest reported test: ' + format_elapsed_time(longest))
        if measured:
            from statistics import median
            values = [row[0] for row in measured]
            self.timing_summary.setText(f'{len(values)} timed tests · {missing} without duration\n'
                f'Total reported test time: {format_elapsed_time(sum(values))} · Average: {format_elapsed_time(sum(values)/len(values))} · Median: {format_elapsed_time(median(values))}')
        else:
            self.timing_summary.setText(f'No individual test durations reported. {missing} tests without duration. Step durations are available in Details.')
        classified = any(case.get('stage') for fact in scope.values() for case in fact.get('tests', ()))
        self.tests.setColumnHidden(5, not classified)
        self.timings.setColumnHidden(5, not classified)
        self.stage_filter.setVisible(classified)
        if not classified:
            self.stage_filter.setCurrentIndex(0)
        self.tests.setColumnHidden(4, selected)
        self.timings.setColumnHidden(3, selected)
        self.filter_tests()
        return True

    def reset(self):
        self.final_tests_signature = None
        self.final_counts = {}
        self.tests.clear()
        self.timings.clear()
        self.test_detail.clear()
        self.search.clear()
        self.filter.setCurrentIndex(0)
        self.stage_filter.setCurrentIndex(0)

    def present_totals(self, counts, interim):
        summary = (' · '.join(f'{value} {key}' for key, value in counts.items())
                   if counts else 'No individual case report supplied. Step results remain available.')
        totals = f'{sum(counts.values())} reported tests\n' + summary
        if interim:
            totals = (f'{sum(counts.values())} final test results · {interim} interim results\n'
                      'Expand the execution step above to inspect live reports.')
            summary = 'Interim reports are shown under the execution step; final outcomes appear here when the suite finishes.'
        self.test_summary.setText(summary)
        self.result_counts.setText(totals)
        for state, (card, label) in self.count_cards.items():
            value = counts.get(state, 0) if counts else '—'
            card.setText(f'{label} {value}')
            card.setAccessibleName(f'{value} {label.lower()} tests' if counts else label + ' count not reported yet')
        self.problems_button.setEnabled(bool(counts.get('failed') or counts.get('error')))

    def filter_tests(self, *_):
        query, choice = self.search.text().casefold(), self.filter.currentText()
        shown = 0
        stage = self.stage_filter.currentText()
        for index in range(self.tests.topLevelItemCount()):
            item = self.tests.topLevelItem(index)
            case = item.data(0, Qt.ItemDataRole.UserRole)
            text = ' '.join(str(value) for value in case.values()).casefold()
            visible = (not query or query in text) and (
                choice == 'All tests' or choice == 'Problems' and case['status'] in {'failed', 'error'}
                or choice == 'Passed' and case['status'] == 'passed'
                or choice == 'Skipped' and case['status'] == 'skipped')
            visible = visible and (stage == 'All stages' or stage_label(case) == stage)
            item.setHidden(not visible)
            shown += int(visible)
        active = query or choice != 'All tests' or stage != 'All stages'
        self.test_matches.setText(f'{shown} / {self.tests.topLevelItemCount()} shown' if active else '')
        current = self.tests.currentItem()
        if current is not None and current.isHidden():
            self.tests.setCurrentItem(None)
            self.test_detail.clear()

    def show_test(self, item, previous=None):
        if item is None:
            self.test_detail.clear()
            return
        case = item.data(0, Qt.ItemDataRole.UserRole)
        self.test_detail.setPlainText(f'{case["classname"]}.{case["name"]}\n'
                                     f'{case["status"]} · {format_elapsed_time(case["seconds"])} · Stage: {stage_label(case)}\n\n{case["message"]}')
