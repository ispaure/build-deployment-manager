"""One review map and a persistent, synchronized task/evidence inspector."""
import json
import shlex
from PySide6.QtCore import QElapsedTimer, QEvent, QSignalBlocker, Qt, Signal, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (QFormLayout, QGroupBox, QHeaderView, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy, QSplitter, QStyle, QToolButton,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)
from .grouped_workflow_ui import GroupedFlowView
from .plan_summary import phase_title, destination_label_for_phase
from .review_presentation import review_data, retained_artifact_provenance
from .workflow_ui import WorkflowGraphView
from .workflow_presentation import blocking_prerequisite, display_states, state_label, format_step_time
from .test_tree_ui import update_test_children, time_share
from .ui_components import EvidenceNavigator, EvidenceGroup, AdaptiveSplitter


class DisclosureToggle(QToolButton):
    """Keep the full caption accessible without forcing the review width."""
    def __init__(self):
        super().__init__()
        self.full_text = ''
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def setText(self, text):
        self.full_text = text
        self.setAccessibleName(text)
        self.setToolTip(text)
        self.elide()

    def elide(self):
        QToolButton.setText(self, self.fontMetrics().elidedText(
            self.full_text, Qt.TextElideMode.ElideRight, max(0, self.width() - 32)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.elide()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.FontChange, QEvent.Type.StyleChange}:
            self.elide()


class Disclosure(QWidget):
    def __init__(self, label, content):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.toggle = DisclosureToggle()
        self.toggle.setText(label)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.content = content
        layout.addWidget(self.toggle)
        layout.addWidget(content)
        self.toggle.toggled.connect(self.expand)
        self.expand(False)

    def expand(self, expanded):
        self.content.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)


class DeferredTextView(QPlainTextEdit):
    """Install large technical text only on selection or an explicit text read."""

    def defer(self, render):
        self.clear()
        self.pending_text = render

    def materialize(self):
        if self.pending_text is not None:
            text, self.pending_text = self.pending_text, None
            self.setPlainText(text())

    def toPlainText(self):
        self.materialize()
        return super().toPlainText()


def text_view(name, *, deferred=False):
    view = DeferredTextView() if deferred else QPlainTextEdit()
    if deferred:
        view.pending_text = None
    view.setReadOnly(True)
    view.setAccessibleName(name)
    view.setMinimumHeight(140)
    return view


class ReviewPlanView(QWidget):
    phase_selected = Signal(str)
    rendering_finished = Signal()
    _ROW_BATCH_SIZE = 32
    _ROW_SLICE_MS = 6

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plan, self.phases, self.facts, self.rows = None, {}, {}, {}
        self.selected, self.detail_selection = '', None
        self.log_reader = None
        self.show_global_problems = True
        self.manual_task_split = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.captured_summary = QLabel()
        self.captured_summary.setWordWrap(True)
        self.captured_summary.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.captured_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.captured_summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.captured_summary.setAccessibleName('Captured source, execution hosts and destinations')
        layout.addWidget(self.captured_summary)
        self.captured = QLabel()
        self.captured.setWordWrap(True)
        self.captured.setTextFormat(Qt.TextFormat.PlainText)
        self.captured.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.source_details = Disclosure('Captured source and run choices', self.captured)
        layout.addWidget(self.source_details)
        self.problems = QPushButton('Inspect failure')
        self.problems.setAccessibleName('Inspect failed step and crash evidence')
        self.problems.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical))
        self.problems.clicked.connect(self.show_problems)
        self.problems.hide()
        layout.addWidget(self.problems)
        self.splitter = AdaptiveSplitter(sizes=(450, 550), minimums=(300, 400))
        self.splitter.setChildrenCollapsible(False)
        self.flow = GroupedFlowView(graph_mode=True, inspect_single_cards=True, nested_navigation=False)
        self.graph = WorkflowGraphView(graph_only=True, lazy_canvas=True)
        self.flow.attach_inspector(self.graph)
        self.flow.group_selected.connect(self.select_group)
        self.graph.phase_selected.connect(self.select_step)
        self.splitter.addWidget(self.flow)
        self.inspector = QWidget()
        self.inspector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.inspector_scroll = self.inspector  # Compatibility handle; no outer scrolling container.
        inspector_layout = QVBoxLayout(self.inspector)
        inspector_layout.setContentsMargins(0, 0, 0, 0)
        self.sidebar_splitter = QSplitter(Qt.Orientation.Vertical)
        self.sidebar_splitter.setChildrenCollapsible(False)
        self.sidebar_splitter.setHandleWidth(5)
        self.sidebar_splitter.splitterMoved.connect(lambda *_: setattr(self, 'manual_task_split', True))
        inspector_layout.addWidget(self.sidebar_splitter)
        task_panel = QWidget()
        side = QVBoxLayout(task_panel)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(4)
        self.task_heading = QLabel('All execution steps')
        self.task_heading.setWordWrap(True)
        self.task_heading.setTextFormat(Qt.TextFormat.PlainText)
        self.task_heading.setStyleSheet('font-weight: 600;')
        side.addWidget(self.task_heading)
        self.tasks = QTreeWidget()
        self.tasks.setHeaderLabels(['Workflow card / task', 'State', 'Time'])
        self.tasks.setAccessibleName('Tasks in the selected workflow card and its prerequisites')
        self.tasks.setRootIsDecorated(True)
        self.tasks.setWordWrap(False)
        self.tasks.setUniformRowHeights(True)
        self.tasks.setIndentation(14)
        self.tasks.setMinimumHeight(130)
        self.tasks.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tasks.header().setStretchLastSection(False)
        self.tasks.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tasks.setColumnWidth(1, max(96, self.fontMetrics().horizontalAdvance('Needs approval') + 12))
        self.tasks.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.tasks.setColumnWidth(2, 80)
        self.tasks.currentItemChanged.connect(self.task_changed)
        self.tasks.itemExpanded.connect(lambda _: self.size_task_list(False))
        self.tasks.itemExpanded.connect(lambda _: self.refresh_rows(force_tests=True))
        self.tasks.itemCollapsed.connect(lambda _: self.refresh_rows(force_tests=True))
        self.tasks.itemCollapsed.connect(lambda _: self.size_task_list(False))
        side.addWidget(self.tasks, 2)
        self.sidebar_splitter.addWidget(task_panel)
        details_panel = QWidget()
        side = QVBoxLayout(details_panel)
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(4)
        self.sidebar_splitter.addWidget(details_panel)
        self.sidebar_splitter.setSizes([180, 380])
        self.sidebar_splitter.setStretchFactor(0, 1)
        self.sidebar_splitter.setStretchFactor(1, 2)
        self.case_detail = QLabel()
        self.case_detail.setAccessibleName('Selected underlying test outcome and details')
        self.case_detail.setTextFormat(Qt.TextFormat.PlainText)
        self.case_detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.case_detail.setWordWrap(True)
        self.case_detail.hide()
        self.selection_heading = QLabel('Whole workflow')
        self.selection_heading.setWordWrap(True)
        self.selection_heading.setTextFormat(Qt.TextFormat.PlainText)
        self.selection_heading.setStyleSheet('font-weight: 600;')
        self.scope_label = QLabel('Scope: whole workflow')
        self.scope_label.setWordWrap(True)
        self.scope_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.scope_label.setAccessibleName('Evidence scope')
        self.blocking_key = ''
        self.blocker = QPushButton('View blocking step')
        self.blocker.clicked.connect(lambda: self.inspect_phase(self.blocking_key))
        self.blocker.hide()
        # These captions share the bounded inspector header. Stacking them
        # consumes another text line. Keep the repair alongside its task scope;
        # scrolling evidence cannot make an overflowing ancestor pane visible.
        heading = QHBoxLayout()
        heading.setSpacing(8)
        heading.addWidget(self.selection_heading, 1)
        heading.addWidget(self.scope_label, 2)
        heading.addWidget(self.blocker)
        side.addLayout(heading)
        self.inspector_tabs = EvidenceNavigator()
        self.inspector_tabs.setAccessibleName('Selected task details, command and complete plan')
        side.addWidget(self.inspector_tabs, 3)
        self.details_scroll = QScrollArea()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        details_body = QWidget()
        detail_side = QVBoxLayout(details_body)
        detail_side.setContentsMargins(6, 6, 6, 6)
        detail_side.setSpacing(4)
        self.details_scroll.setWidget(details_body)
        self.inspector_tabs.addTab(self.details_scroll, 'Details')
        detail_side.addWidget(self.case_detail)
        self.context_info = QLabel()
        self.context_info.setWordWrap(True)
        self.context_info.setTextFormat(Qt.TextFormat.PlainText)
        self.context_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_side.addWidget(self.context_info)
        self.error_panel = QGroupBox('Error details')
        self.error_panel.setAccessibleName('Selected step error, traceback and captured output')
        error_layout = QVBoxLayout(self.error_panel)
        self.error_summary = QLabel()
        self.error_summary.setWordWrap(True)
        self.error_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.error_summary.setStyleSheet('font-weight: 600;')
        error_layout.addWidget(self.error_summary)
        self.details = text_view('Full error traceback, test failures and captured output')
        error_layout.addWidget(self.details)
        detail_side.addWidget(self.error_panel)
        self.error_panel.hide()
        self.fact_panel = QWidget()
        self.fact_form = QFormLayout(self.fact_panel)
        self.fact_form.setContentsMargins(0, 0, 0, 0)
        self.fact_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.fact_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.fact_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        self.fact_form.setVerticalSpacing(10)
        self.fact_values = {}
        for label in ('Purpose', 'Runs on', 'Elapsed', 'Running test', 'Result', 'Outputs', 'Delivery', 'Notes'):
            value = QLabel()
            value.setWordWrap(True)
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
            self.fact_values[label] = value
            heading = QLabel(label)
            heading.setStyleSheet('font-weight: 600; padding-top: 6px;')
            self.fact_form.addRow(heading, value)
        detail_side.addWidget(self.fact_panel)
        self.prerequisites = QWidget()
        self.prerequisite_layout = QVBoxLayout(self.prerequisites)
        self.prerequisite_layout.setContentsMargins(0, 0, 0, 0)
        detail_side.addWidget(self.prerequisites)
        detail_side.addStretch()
        self.command = text_view('Exact selected step command and execution settings')
        self.command_section = self.command
        self.inspector_tabs.addTab(self.command, 'Technical · Command')
        self.plan_tabs = EvidenceGroup(self.inspector_tabs, prefix='Technical · ')
        self.plan_tabs.setAccessibleName('Complete plan summary, dependencies and data')
        self.overview = text_view('Readable complete plan', deferred=True)
        self.plan_data = text_view('Complete redacted plan data', deferred=True)
        self.board = QTreeWidget()
        self.board.setHeaderLabels(['Planned work', 'Starts after', 'What happens'])
        self.board.setMinimumHeight(140)
        self.board.setAccessibleName('Every declared dependency')
        for label, widget in [('Summary', self.overview), ('Dependencies', self.board), ('Data', self.plan_data)]:
            self.plan_tabs.addTab(widget, label)
        self.technical_section = self.plan_tabs
        self.inspector_tabs.currentChanged.connect(self.materialize_evidence)
        self.splitter.addWidget(self.inspector_scroll)
        self.splitter.setSizes([450, 550])
        self.splitter.setStretchFactor(0, 45)
        self.splitter.setStretchFactor(1, 55)
        layout.addWidget(self.splitter, 1)
        self._task_size_timer = QTimer(self)
        self._task_size_timer.setSingleShot(True)
        self._task_size_targets = (self.tasks, self.tasks.header())
        self._task_size_observer_active = False
        self._connect_task_size_refresh()
        self.rendering = False
        self._staged_data = None
        self._task_work = None
        self._dependency_work = None
        self._requested_phase = ''
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self.render_slice)

    def _connect_task_size_refresh(self):
        if not self._task_size_observer_active:
            self._task_size_timer.timeout.connect(self._refresh_task_minimum)
            for target in self._task_size_targets:
                target.installEventFilter(self)
            self._task_size_observer_active = True

    def _disconnect_task_size_refresh(self):
        self._task_size_timer.stop()
        if self._task_size_observer_active:
            for target in self._task_size_targets:
                target.removeEventFilter(self)
            self._task_size_timer.timeout.disconnect(self._refresh_task_minimum)
            self._task_size_observer_active = False

    def _refresh_task_minimum(self):
        self.size_task_list(False)

    def eventFilter(self, watched, event):
        if (watched in self._task_size_targets
                and event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange)):
            # Native header/row metrics settle after the application's font
            # batch. Coalesce that batch without resetting a user's split.
            self._task_size_timer.start(0)
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._connect_task_size_refresh()
        self._task_size_timer.start(0)

    def hideEvent(self, event):
        self._disconnect_task_size_refresh()
        super().hideEvent(event)

    def closeEvent(self, event):
        self.cancel_rendering()
        self._disconnect_task_size_refresh()
        super().closeEvent(event)

    def materialize_evidence(self, _):
        page = self.inspector_tabs.currentWidget()
        if page in (self.overview, self.plan_data):
            page.materialize()

    def cancel_rendering(self):
        self._render_timer.stop()
        self._task_work = self._dependency_work = None
        self._requested_phase = ''
        self.rendering = False
        self.tasks.setEnabled(True)
        self.flow.setEnabled(True)

    def stage_prepared(self, data):
        """Supply worker data to the enclosing view's next reset of this display plan."""
        self._staged_data = data

    def reset(self, plan, fields=(), *, capability=None, proposal=None, summary='', inputs='',
              preview=True, prepared=None):
        self.cancel_rendering()
        staged, self._staged_data = self._staged_data, None
        if prepared is None and staged is not None and staged.plan is plan:
            prepared = staged
        data = prepared if prepared is not None else review_data(plan, fields, capability, proposal)
        self.presentation = data
        self.plan, self.fields, self.summary = data.plan, fields, summary
        self.overview.defer(lambda: data.overview)
        self.plan_data.defer(lambda: json.dumps(
            data.plan.data() if hasattr(data.plan, 'data') else vars(data.plan), default=vars, indent=2))
        self.board.clear()
        self._dependency_work = iter(data.dependency_rows)
        self.phases = data.phases
        self.task_owners, self.task_names = data.task_owners, data.task_names
        self._overview_nodes = {node.id: node for node in data.grouped.phases}
        self._card_details = getattr(data.grouped, 'card_details', None) or {}
        self.selected, self.facts, self.detail_selection = '', {}, None
        self.captured.setText('\n\n'.join(name + ': ' + value for name, value in data.captured_choices) +
                              ('\n\nCaptured notes and recipients:\n' + inputs if inputs else ''))
        self.captured_summary.setText(data.captured_summary)
        self.source_details.toggle.setText('Captured choices · full identity, notes and recipients')
        self.source_details.toggle.setChecked(False)
        self.inspector_tabs.setCurrentWidget(self.details_scroll)
        self.plan_tabs.last = 0
        self.graph.reset(self.plan, preview=preview)
        # Reserve the same status space before and after Start.
        self.flow.reset(self.plan, fields, preview=preview, reserve_activity=True, overview=data.grouped)
        self.problems.hide()
        self.select_group('')

    def scope_keys(self):
        if not self.flow.selected:
            return tuple(self.phases)
        if self.flow.pages.currentIndex() == 0:
            return self.flow.group_keys(self.flow.selected)
        visible = set(self.flow.group_keys(self.flow.selected))
        pending = list(visible)
        while pending:
            phase = self.phases[pending.pop()]
            for parent in (*phase.dependencies, *getattr(phase, 'waits_for', ())):
                if parent not in visible:
                    visible.add(parent)
                    pending.append(parent)
        return tuple(key for key in self.phases if key in visible)

    def select_group(self, key):
        if not key:
            self.flow.selected = ''
        self.selected = ''
        self._requested_phase = ''
        keys = self.scope_keys()
        expanded = bool(key and self.flow.pages.currentIndex() == 1)
        if expanded:
            self.graph.set_scope(keys)
            self.graph.setVisible(bool(keys))
            extra = len(set(keys) - set(self.flow.group_keys(key)))
            self.task_heading.setText(self.flow.heading.text() +
                                      (f'\n{extra} prerequisite steps from other cards' if extra else ''))
        else:
            self.task_heading.setText(self.flow.heading.text() if key else 'Workflow cards · ' + str(len(keys)) + ' execution steps')
        with QSignalBlocker(self.tasks):
            self.tasks.clear()
        self.rows, self.card_rows = {}, {}
        members = set(self.flow.grouped.members.get(key, ()) or self.flow.group_keys(key)) if key else set(keys)
        states = (display_states(self.plan, self.facts) if self.facts else self.presentation.preview_states)
        self._task_work = (key, keys, iter(keys), members, states, expanded)
        large_dependencies = self._dependency_work is not None and len(self.phases) > self._ROW_BATCH_SIZE
        if len(keys) > self._ROW_BATCH_SIZE or large_dependencies:
            self.rendering = True
            self.tasks.setEnabled(False)
            if large_dependencies:
                # Establish the complete initial task list before allowing a
                # card click to replace its scope.
                self.flow.setEnabled(False)
            self.render_details()
            self._render_timer.start(1)
        else:
            self.render_slice(synchronous=True)

    def render_slice(self, *, synchronous=False):
        elapsed = QElapsedTimer()
        elapsed.start()

        def available(index):
            return synchronous or (index < self._ROW_BATCH_SIZE and
                                   (index == 0 or elapsed.elapsed() < self._ROW_SLICE_MS))

        index = 0
        if self._task_work is not None:
            key, keys, pending, members, states, expanded = self._task_work
            with QSignalBlocker(self.tasks):
                while available(index):
                    phase_id = next(pending, None)
                    if phase_id is None:
                        self._task_work = None
                        if key and not keys:
                            self.card_row(key)
                        break
                    self.add_task_row(phase_id, members, states)
                    index += 1
            if self._task_work is None:
                self.finish_task_rows(key, keys, members, expanded)
        if self._dependency_work is not None:
            while available(index):
                row_data = next(self._dependency_work, None)
                if row_data is None:
                    self._dependency_work = None
                    break
                key, columns = row_data
                row = QTreeWidgetItem(list(columns))
                row.setToolTip(0, key)
                self.board.addTopLevelItem(row)
                index += 1
        if self._task_work is not None or self._dependency_work is not None:
            self._render_timer.start(1)
        elif self.rendering:
            self.rendering = False
            self.tasks.setEnabled(True)
            self.flow.setEnabled(True)
            self.rendering_finished.emit()

    def card_row(self, group):
        if group not in self.card_rows:
            node = self._overview_nodes.get(group)
            card = QTreeWidgetItem([node.label if node else 'Other execution steps', '', ''])
            card.setData(0, Qt.ItemDataRole.UserRole + 3, group)
            self.tasks.addTopLevelItem(card)
            card.setExpanded(True)
            self.card_rows[group] = card
        return self.card_rows[group]

    def add_task_row(self, phase_id, members, states):
        row = QTreeWidgetItem([self.task_names[phase_id], '', ''])
        row.setData(0, Qt.ItemDataRole.UserRole, phase_id)
        row.setToolTip(0, self.presentation.titles[phase_id] + '\nStep identity: ' + phase_id +
                       ('\nPrerequisite from another card' if phase_id not in members else ''))
        self.card_row(self.task_owners.get(phase_id, '__unassigned__')).addChild(row)
        self.rows[phase_id] = row
        self.refresh_task_row(phase_id, row, states, 0)

    def finish_task_rows(self, key, keys, members, expanded):
        self.size_task_list(False)
        if self.facts:
            self.refresh_rows()
        else:
            self.refresh_card_rows(self.presentation.preview_states, {})
        chosen = self._requested_phase
        if key and not chosen:
            chosen = next((phase_id for phase_id in keys
                           if phase_id in members and self.is_problem(phase_id)), '')
        if key and not chosen:
            chosen = next((phase_id for phase_id in keys if phase_id in members), '')
        self._requested_phase = ''
        if expanded:
            self.graph.select(chosen)
        else:
            self.select_step(chosen)

    def size_task_list(self, error_visible):
        # The vertical splitter owns space allocation; the tree scrolls itself.
        # A fixed tree minimum can squeeze the details headers and repair
        # action outside their pane at large fonts. Keep one native row usable;
        # the preferred split below still reserves more rows when space permits.
        row_height = max(self.tasks.fontMetrics().height(), self.tasks.sizeHintForRow(0))
        self.tasks.setMinimumHeight(self.tasks.header().sizeHint().height() + row_height
                                    + 2 * self.tasks.frameWidth())
        identity = (self.flow.selected, tuple(self.rows))
        if not self.manual_task_split and identity != getattr(self, '_sized_scope', None) and self.sidebar_splitter.height() > 0:
            rows = len(self.rows) + len(getattr(self, 'card_rows', {}))
            desired = min(210, max(110, (min(rows, 6) + 1) * self.fontMetrics().height() + 24))
            self.sidebar_splitter.setSizes([desired, max(180, self.sidebar_splitter.height() - desired)])
            self._sized_scope = identity

    def task_changed(self, row, previous=None):
        if row is not None:
            group = row.data(0, Qt.ItemDataRole.UserRole + 3)
            if group:
                self.flow.open_group(group)
                return
            self.inspect_phase(row.data(0, Qt.ItemDataRole.UserRole))
            if row.data(0, Qt.ItemDataRole.UserRole + 1):
                self.tasks.blockSignals(True)
                self.tasks.setCurrentItem(row)
                self.tasks.blockSignals(False)
                self.show_case_detail(row)

    def show_case_detail(self, row):
        case = row.data(0, Qt.ItemDataRole.UserRole + 1)
        self.case_detail.setText('\n'.join(filter(None, (
            case['name'], case.get('classname'), row.text(1), row.text(2), case.get('message')))))
        self.case_detail.show()

    def inspect_phase(self, key):
        if key not in self.phases:
            return
        if key not in self.rows:
            if self._task_work is not None and key in self._task_work[1]:
                self._requested_phase = key
                return
            self.flow.open_group(self.task_owners.get(key, '__unassigned__'))
        if key not in self.rows and self._task_work is not None:
            self._requested_phase = key
            return
        if self.flow.pages.currentIndex() == 0:
            self.select_step(key)
        else:
            self.graph.select(key)

    def select_step(self, key):
        self.case_detail.hide()
        changed = self.selected != key
        self.selected = key
        if key and self.flow.pages.currentIndex() == 0:
            self.flow.selected = self.task_owners.get(key, self.flow.selected)
            self.flow.set_facts(self.facts)
        self.tasks.blockSignals(True)
        row = self.rows.get(key)
        self.tasks.setCurrentItem(row)
        if row:
            if row.parent():
                row.parent().setExpanded(True)
            self.tasks.scrollToItem(row)
        self.tasks.blockSignals(False)
        self.render_details()
        if changed:
            self.details_scroll.verticalScrollBar().setValue(0)
        self.phase_selected.emit(key)

    def is_problem(self, key):
        fact = self.facts.get(key, {})
        return fact.get('status') in {'failed', 'error', 'timeout', 'unknown', 'interrupted', 'cancelled'} or any(
            case.get('status') in {'failed', 'error'} for case in fact.get('tests', ()))

    def refresh_rows(self, *, force_tests=False):
        if self._task_work is not None:
            return
        with QSignalBlocker(self.tasks):
            groups = {}
            for key in self.rows:
                group = self.task_owners.get(key, '__unassigned__')
                fact = self.facts.get(key, {})
                groups[group] = groups.get(group, 0) + (0 if fact.get('reused') else fact.get('seconds') or 0)
            states = display_states(self.plan, self.facts) if self.facts else self.presentation.preview_states
            for key, row in self.rows.items():
                self.refresh_task_row(key, row, states, groups.get(self.task_owners.get(key, '__unassigned__')),
                                      force_tests=force_tests)
            self.refresh_card_rows(states, groups)
        current = self.tasks.currentItem()
        if current is not None and current.data(0, Qt.ItemDataRole.UserRole + 1):
            self.show_case_detail(current)
        else:
            self.case_detail.hide()

    def refresh_task_row(self, key, row, states, group_seconds, *, force_tests=False):
        state, reason = states[key]
        fact = self.facts.get(key, {})
        row.setText(1, 'Reused' if fact.get('reused') else {'awaiting_review': 'Approval', 'waiting_resource': 'Waiting'}.get(state, state.replace('_', ' ').capitalize()))
        if fact.get('recovery', {}).get('status') == 'recovered':
            row.setText(1, 'Passed after recovery')
        elapsed = format_step_time(fact, state) or 'Not recorded'
        row.setText(2, '—' if elapsed in {'Not started', 'Not recorded'} else elapsed)
        row.setToolTip(1, reason)
        row.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxCritical)
            if self.is_problem(key) else self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        update_test_children(row, key, fact, self.phases[key], force=force_tests)
        time_share(self.tasks, row, fact.get('reuse', {}).get('original_seconds') if fact.get('reused') else fact.get('seconds'),
                   group_seconds, reused=fact.get('reused', False))
        if fact.get('seconds') is None and not fact.get('reused'):
            row.setToolTip(2, elapsed)
        cases = fact.get('tests') or fact.get('live_tests', ())
        if cases:
            row.setToolTip(1, row.text(1) + f' · {len(cases)} reported tests')
        if fact.get('current_test'):
            row.setToolTip(1, 'Running: ' + fact['current_test']['name'])

    def refresh_card_rows(self, states, groups):
        total = sum(fact.get('seconds') or 0 for fact in self.facts.values() if not fact.get('reused'))
        statuses = {group: set() for group in self.card_rows}
        for key in self.rows:
            statuses[self.task_owners.get(key, '__unassigned__')].add(states[key][0])
        priority = ('failed', 'error', 'running', 'awaiting_review', 'blocked', 'queued', 'planned')
        for group, card in self.card_rows.items():
            time_share(self.tasks, card, groups.get(group) or None, total)
            state = next((value for value in priority if value in statuses[group]), next(iter(statuses[group]), 'planned'))
            card.setText(1, state_label(state))

    def set_facts(self, facts):
        if self.plan is None:
            return
        self.facts = {key: fact for key, fact in facts.items() if key in self.phases}
        self.graph.preview = not bool(self.facts)
        self.graph.update_guidance()
        self.graph.set_facts(self.facts)
        self.flow.set_facts(self.facts)
        self.refresh_rows()
        problems = sum(self.is_problem(key) for key in self.phases)
        self.problems.setText(f'{problems} step' + ('s' if problems != 1 else '') + ' with errors · View error details')
        self.problems.setVisible(bool(problems) and self.show_global_problems)
        self.render_details()

    def show_problems(self):
        key = next((key for key in self.phases if self.facts.get(key, {}).get('status') == 'unknown'), '')
        key = key or next((key for key in self.phases if self.is_problem(key)), '')
        if key:
            self.inspect_phase(key)
            self.inspector_tabs.setCurrentWidget(self.details_scroll)
            self.details.setFocus()
            self.details_scroll.ensureWidgetVisible(self.error_summary)

    def set_fact(self, label, text):
        self.fact_values[label].setText(text)
        self.fact_form.setRowVisible(self.fact_values[label], bool(text))

    def execution_location(self, key):
        journey = getattr(self.plan, 'journey', {})
        targets = {target for target, steps in journey.get('platforms', {}).items() if key in steps}
        for node in self.flow.grouped.phases:
            if key in self.flow.group_keys(node.id):
                targets.update(getattr(node, 'platforms', ()))
                if node.id.startswith('platform.'):
                    targets.add(node.id.removeprefix('platform.'))
        locations = [journey.get('executions', {}).get(target, {}).get('backend', '') for target in sorted(targets)]
        return ', '.join(dict.fromkeys(filter(None, locations))) or self.plan.backend

    def render_details(self):
        key = self.selected
        group = self.flow.selected
        self.scope_label.setText('Scope: task · ' + phase_title(self.phases[key]) if key else
            'Scope: card · ' + self.flow.heading.text() if group else 'Scope: whole workflow')
        while self.prerequisite_layout.count():
            widget = self.prerequisite_layout.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        for label in self.fact_values:
            self.set_fact(label, '')
        self.inspector_tabs.setTabEnabled(self.inspector_tabs.indexOf(self.command), bool(key))
        self.fact_panel.setVisible(bool(key))
        self.blocking_key = blocking_prerequisite(self.plan, self.facts, key) if self.facts and key else ''
        self.blocker.setVisible(bool(self.blocking_key))
        problem = bool(key and self.is_problem(key))
        self.error_panel.setVisible(problem)
        self.size_task_list(problem)
        self.error_summary.clear()
        self.context_info.clear()
        self.context_info.hide()
        self.selection_heading.setVisible(bool(key))
        if not key:
            count = sum(len(getattr(phase, 'test_files', ())) for phase in self.phases.values())
            self.context_info.setText(f'{len(self.phases)} execution steps across {len(self.flow.grouped.phases)} workflow cards.\n'
                + (f'{count} declared test files are available in the tree.\n' if count else '')
                + 'Select a card, task or test to inspect its details. Time bars show each item’s share of measured time at its level; expanded children total 100%.')
            self.context_info.show()
            if self.flow.selected == 'source':
                self.selection_heading.setText('Captured source')
                self.selection_heading.show()
                self.context_info.setText(self.presentation.captured_choices[0][1] +
                    '\n\nNo executable source subtasks were declared.' if not self.flow.group_keys('source')
                    else self.presentation.captured_choices[0][1])
                self.context_info.show()
            elif group in self._overview_nodes:
                node = self._overview_nodes[group]
                category, description = self._card_details.get(group, (node.category, node.description))
                if category == 'build':
                    self.selection_heading.setText(node.label)
                    self.selection_heading.show()
                    self.context_info.setText(description)
            self.set_detail_text('', key)
            return
        phase, fact = self.phases[key], self.facts.get(key, {})
        states = display_states(self.plan, self.facts) if self.facts else self.presentation.preview_states
        state, reason = states[key]
        self.selection_heading.setText(self.task_names.get(key, phase_title(phase)))
        self.selection_heading.setToolTip(phase_title(phase) + '\n' + key)
        if problem:
            lines = []
            for field in ('error', 'reason', 'summary', 'cleanup_error'):
                if fact.get(field):
                    lines.append(field.replace('_', ' ').title() + ': ' + str(fact[field]))
            if fact.get('exit_code') is not None:
                lines.append('Exit code: ' + str(fact['exit_code']))
            for case in fact.get('tests', ()):
                if case.get('status') in {'failed', 'error'}:
                    lines.append(case['name'] + ' · ' + case['status'] + '\n' + str(case.get('message', '')))
            for observation in fact.get('observed_test_failures', ()):
                lines.append('Runner reported: ' + observation.get('name', 'test') + ' · '
                             + observation['status'] + '\n' + observation.get('message', ''))
            if reason and reason not in (fact.get('error'), fact.get('reason')):
                lines.append(reason)
            self.error_summary.setText(str(fact.get('error') or fact.get('reason') or state_label(state)).splitlines()[0])
            if self.log_reader and fact.get('log'):
                try:
                    lines += ['Captured step output:', self.log_reader(key)]
                except (OSError, ValueError, TypeError) as error:
                    lines.append('Could not read captured step output: ' + str(error))
            self.set_detail_text('\n\n'.join(lines) or 'No error message was captured. Inspect the step command and retained output.', key)
        else:
            self.set_detail_text('', key)
        description = getattr(phase, 'description', '')
        self.set_fact('Purpose', description)
        self.set_fact('Runs on', self.execution_location(key))
        elapsed = format_step_time(fact, state)
        self.set_fact('Elapsed', elapsed if elapsed not in {'', 'Not started'} else '')
        if fact.get('current_test'):
            case = fact['current_test']
            self.set_fact('Running test', '.'.join(filter(None, (case.get('classname'), case['name']))))
        if self.blocking_key:
            self.set_fact('Result', 'Blocked by ' + self.task_names.get(self.blocking_key, phase_title(self.phases[self.blocking_key])))
        elif state == 'waiting_resource':
            self.set_fact('Result', reason)
        else:
            self.set_fact('Result', 'Passed after infrastructure recovery' if fact.get('recovery', {}).get('status') == 'recovered' else state_label(state))
        self.set_fact('Outputs', '\n'.join(path.replace('\\', '/').rsplit('/', 1)[-1] for path in phase.artifacts) or 'No output files declared')
        self.fact_values['Outputs'].setToolTip('\n'.join(phase.artifacts))
        effect = phase.effect if phase.effect != 'inherit' else self.plan.effect
        destinations = [destination_label_for_phase(destination, key) for destination in getattr(self.plan, 'journey', {}).get('destinations', {}).values()
                        if key in destination['steps']]
        delivery = '\n'.join(destinations)
        if effect in {'upload', 'deploy', 'publish', 'dispatch'} and getattr(phase, 'approval_required', True):
            delivery += ('\n' if delivery else '') + 'Separate approval required'
        self.set_fact('Delivery', delivery)
        notes = []
        owner = self.task_owners.get(key)
        node = self._overview_nodes.get(owner)
        category = self._card_details.get(owner, (node.category if node else '', ''))[0]
        if category == 'build' and node and node.platforms:
            notes.append('Build targets: ' + ', '.join(filter(None, node.platforms)) + '.')
        if category == 'build' and retained_artifact_provenance(self.plan):
            notes.append('Uses verified artifacts from the saved run.')
        recovery = getattr(phase, 'infrastructure_recovery', {})
        if recovery:
            notes.append('One infrastructure recovery attempt is authorized for this repeatable test on ' + recovery['target'] + '.')
        notes.extend(self.presentation.later_notes.get(key, ()))
        self.set_fact('Notes', '\n'.join([*notes, *self.presentation.shared_notes]))
        parents = tuple(dict.fromkeys((*phase.dependencies, *getattr(phase, 'waits_for', ()))))
        if parents:
            heading = QLabel('Prerequisites')
            heading.setStyleSheet('font-weight: 600;')
            self.prerequisite_layout.addWidget(heading)
        from .ui_components import SelectionSummary
        for parent in parents:
            button = SelectionSummary()
            label = self.task_names.get(parent, phase_title(self.phases[parent]))
            if parent in getattr(phase, 'waits_for', ()):
                label += ' · wait for completion'
            button.set_summary(label)
            button.setToolTip(phase_title(self.phases[parent]) + '\n' + parent)
            button.clicked.connect(lambda checked=False, parent=parent: self.inspect_phase(parent))
            self.prerequisite_layout.addWidget(button)
        from .resources import resource_details
        technical = ['Step identity: ' + key, shlex.join(phase.argv), 'Working directory: ' + phase.cwd,
                     'Required for success: ' + ('Yes' if phase.required else 'No'), 'Timeout: ' + str(phase.timeout) + ' seconds',
                     'Success prerequisites: ' + (', '.join(phase.dependencies) or 'None'),
                     'Waits for completion: ' + (', '.join(getattr(phase, 'waits_for', ())) or 'None')]
        if phase.always:
            technical.append('Runs after prerequisites finish, including after failure.')
        technical.extend(resource_details(self.plan, key))
        if recovery:
            technical.extend(['Infrastructure probe: ' + shlex.join(recovery['probe']),
                              'Infrastructure repair: ' + shlex.join(recovery['recover']),
                              'Recovery deadline: ' + str(recovery['timeout']) + ' seconds'])
        evidence = fact.get('recovery', {})
        if evidence:
            technical.append('Infrastructure recovery: ' + evidence.get('status', 'unknown'))
            for attempt in (*evidence.get('attempts', ()), *evidence.get('checks', ())):
                technical.append('Retained ' + attempt.get('operation', 'test attempt') + ': '
                                 + attempt['status'] + ' · ' + attempt.get('log', 'No log captured'))
        if phase.environment:
            technical.append('Environment references:\n' + '\n'.join(f'{name}={value}' for name, value in phase.environment.items()))
        self.command.setPlainText('\n\n'.join(technical))

    def set_detail_text(self, text, selection):
        if self.details.toPlainText() == text and self.detail_selection == selection:
            return
        same = self.detail_selection == selection
        cursor = self.details.textCursor()
        position, anchor = cursor.position(), cursor.anchor()
        scroll = self.details.verticalScrollBar().value()
        self.details.setPlainText(text)
        if same:
            cursor = self.details.textCursor()
            last = self.details.document().characterCount() - 1
            cursor.setPosition(min(anchor, last))
            cursor.setPosition(min(position, last), QTextCursor.MoveMode.KeepAnchor)
            self.details.setTextCursor(cursor)
            self.details.verticalScrollBar().setValue(scroll)
        else:
            self.details.verticalScrollBar().setValue(0)
        self.detail_selection = selection
