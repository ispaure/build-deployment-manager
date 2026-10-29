"""Compose workflow browsers; retained imports preserve existing view callers."""
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (QLabel, QPushButton, QHBoxLayout, QSizePolicy,
    QVBoxLayout, QWidget, QHeaderView, QStackedWidget, QTreeWidget, QTreeWidgetItem)
from .workflow_graph import layout_positions, visible_dependencies, connection_groups
from .workflow_presentation import (FAILED, PENDING, title, effect_label, stage_label,
    display_states, blocking_prerequisite, state_label, step_time, timing_duration)
from .test_tree_ui import (TimeShareDelegate, time_share, current_test_seconds,
    visible_tree_rows, update_test_children)
from .workflow_cards_ui import (SECTION_COLORS, section_tint, connection_color, FlowCard,
    CardActivityLabel, FlowCanvas, connection_path, dependency_path)
from .workflow_map_ui import FitMapView, orientation_picker, pointer_follow_picker


class StageBrowser(QTreeWidget):
    """A readable hierarchy over exact steps, without changing the executable plan."""
    selected = Signal(str)

    def __init__(self):
        super().__init__()
        self.setHeaderLabels(['Stage / step', 'Status', 'Purpose'])
        self.setAccessibleName('Workflow stages. Expand a stage to explore its steps. Select a step for details.')
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(False)
        self.setWordWrap(True)
        self.setIndentation(22)
        self.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.setStyleSheet('QTreeWidget::item { padding: 9px 6px; }')
        self.currentItemChanged.connect(self.choose)

    def choose(self, item, previous):
        if item is not None:
            self.selected.emit(item.data(0, Qt.ItemDataRole.UserRole) or '')

    def load_plan(self, plan):
        self.blockSignals(True)
        self.clear()
        self.steps, self.groups = {}, {}
        for phase in plan.phases:
            group = stage_label(phase, plan)
            if group not in self.groups:
                parent = QTreeWidgetItem([group])
                self.addTopLevelItem(parent)
                self.groups[group] = parent
                for column in range(3):
                    font = parent.font(column); font.setBold(True); parent.setFont(column, font)
                    parent.setBackground(column, self.palette().alternateBase())
                parent.setToolTip(0, 'Double-click or use Right arrow to expand. Grouping does not imply execution order.')
            row = QTreeWidgetItem([title(phase), '', effect_label(phase, plan)])
            row.setData(0, Qt.ItemDataRole.UserRole, phase.id)
            row.setToolTip(0, title(phase) + '\nStep identity: ' + phase.id)
            self.groups[group].addChild(row)
            self.steps[phase.id] = row
        for group, parent in self.groups.items():
            count = parent.childCount()
            parent.setText(0, f'{group} · {count} ' + ('step' if count == 1 else 'steps'))
            parent.setExpanded(len(plan.phases) <= 12)
        self.blockSignals(False)

    def update_facts(self, plan, facts, selected, preview):
        states = display_states(plan, facts, preview)
        for key, row in self.steps.items():
            status, reason = states[key]
            row.setText(1, status.replace('_', ' ').capitalize())
            row.setToolTip(1, reason)
        for parent in self.groups.values():
            counts = {}
            for index in range(parent.childCount()):
                state = parent.child(index).text(1)
                counts[state] = counts.get(state, 0) + 1
            parent.setText(1, ' · '.join(f'{count} {state.lower()}' for state, count in counts.items()))
            approvals = sum((phase.effect if phase.effect != 'inherit' else plan.effect) in
                {'upload', 'deploy', 'publish', 'dispatch'} for phase in plan.phases
                if self.steps[phase.id].parent() is parent and getattr(phase, 'approval_required', True))
            parent.setText(2, (f'{approvals} action' + (' requires' if approvals == 1 else 's require') + ' separate approval')
                if approvals else 'Expand to explore steps')
        self.blockSignals(True)
        if selected:
            row = self.steps[selected]
            row.parent().setExpanded(True)
            if self.currentItem() is not row:
                self.setCurrentItem(row)
                self.scrollToItem(row)
        elif self.currentItem() and self.currentItem().data(0, Qt.ItemDataRole.UserRole):
            self.setCurrentItem(None)
        self.blockSignals(False)


class WorkflowFlow(QWidget):
    phase_selected = Signal(str)

    def __init__(self, parent=None, *, graph_only=False):
        super().__init__(parent)
        self.graph_only = graph_only
        self.plan, self.facts, self.selected, self.preview = None, {}, '', False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.overview_heading = QLabel()
        self.overview_heading.setStyleSheet('font-weight: 600;')
        self.overview_heading.hide()
        self.whole = QPushButton('Whole workflow')
        self.whole.setCheckable(True)
        self.whole.clicked.connect(lambda: self.select(''))
        tools = QHBoxLayout(); tools.setContentsMargins(0, 0, 0, 0)
        tools.addWidget(self.overview_heading)
        tools.addWidget(self.whole)
        self.stages_button = QPushButton('Stages')
        self.map_button = QPushButton('Dependency map')
        for button in (self.stages_button, self.map_button):
            button.setCheckable(True)
            tools.addWidget(button)
        self.stages_button.clicked.connect(lambda: self.show_map(False))
        self.map_button.clicked.connect(lambda: self.show_map(True))
        tools.addStretch()
        self.fit_button, self.zoom_in, self.zoom_out = QPushButton('Fit'), QPushButton('+'), QPushButton('−')
        for control, name in ((self.fit_button, 'Fit entire workflow'), (self.zoom_in, 'Zoom in'), (self.zoom_out, 'Zoom out')):
            control.setAccessibleName(name); control.setToolTip(name); control.setMaximumWidth(52); tools.addWidget(control)
        layout.addLayout(tools)
        self.guidance = QLabel('Read left to right. Arrows show prerequisites. Branches can overlap when workers and resources allow. Select a card for details.')
        self.guidance.setWordWrap(True)
        layout.addWidget(self.guidance)
        self.canvas = FlowCanvas()
        self.scroll = FitMapView(self.canvas)
        self.orientation = orientation_picker(self.scroll)
        tools.insertWidget(tools.count() - 3, self.orientation)
        self.follow_mouse = pointer_follow_picker(self.scroll)
        tools.insertWidget(tools.count() - 3, self.follow_mouse)
        self.scroll.setAccessibleName('Workflow dependency map. Scroll or drag to pan. Tab between cards; Space selects a step.')
        self.scroll.scale_changed.connect(lambda scale: self.zoom_out.setEnabled(scale > self.scroll.minimum_scale))
        self.scroll.scale_changed.connect(lambda scale: self.zoom_in.setEnabled(scale < self.scroll.maximum_scale))
        self.fit_button.clicked.connect(self.fit_map)
        self.zoom_in.clicked.connect(lambda: self.scroll.zoom(1.2))
        self.zoom_out.clicked.connect(lambda: self.scroll.zoom(1 / 1.2))
        self.browser = StageBrowser() if not graph_only else None
        if self.browser is not None:
            self.browser.selected.connect(self.select)
        self.views = QStackedWidget()
        self.views.addWidget(self.browser if self.browser is not None else QWidget())
        self.views.addWidget(self.scroll)
        layout.addWidget(self.views, 1)
        self.legend = legend = QLabel('Blue: running · Teal-green: passed · Orange-red: failed · Amber: approval\nMuted cards: blocked or skipped; select them to see why.')
        legend.setWordWrap(True)
        layout.addWidget(legend)
        self.canvas.selected.connect(self.select)
        self.center_timer = QTimer(self)
        self.center_timer.setSingleShot(True)
        self.center_timer.timeout.connect(self.center_map)

    def reset(self, plan, preview=False):
        self.plan, self.facts, self.selected, self.preview = plan, {}, '', preview
        self.canvas.reset(plan)
        self.scroll.reset_view()
        proposed = getattr(plan, 'proposed', False)
        self.guidance.setVisible(not proposed and not self.graph_only)
        self.legend.setVisible(not proposed and not self.graph_only)
        if not proposed and not self.graph_only:
            self.browser.load_plan(plan)
        self.stages_button.setVisible(not proposed and not self.graph_only)
        self.map_button.setVisible(not proposed and not self.graph_only)
        self.show_map(proposed or self.graph_only)
        self.whole.setVisible(not getattr(plan, 'proposed', False))
        if getattr(plan, 'proposed', False):
            self.whole.setText('Overview')
            self.guidance.setText('Select a card to configure it. Read left to right. Arrows show the order.')
            self.legend.setText('Review resolves the exact steps. Nothing starts here.')
        else:
            self.whole.setText('Reviewed plan' if preview else 'Whole workflow')
        self.update_guidance()
        self.set_facts({})
        self.scroll.verticalScrollBar().setValue(0)
        self.center_timer.start(0)

    def set_scope(self, keys):
        # Card inspection already has its own back-to-overview navigation.
        self.whole.hide()
        self.selected = ''
        self.canvas.reset(self.plan, keys)
        self.scroll.reset_view()
        self.set_facts(self.facts)
        self.center_timer.start(0)

    def show_map(self, visible):
        self.views.setCurrentIndex(1 if visible else 0)
        self.stages_button.setChecked(not visible)
        self.map_button.setChecked(visible)
        for control in (self.orientation, self.follow_mouse, self.fit_button, self.zoom_in, self.zoom_out):
            control.setVisible(visible)
        self.update_guidance()
        if visible:
            self.center_timer.start(0)

    def update_guidance(self):
        if self.plan is None or getattr(self.plan, 'proposed', False):
            return
        if self.preview:
            self.legend.setText('Prepared plan · not started. Select a step for its exact prerequisites.')
        elif self.views.currentIndex() == 0:
            self.legend.setText('Statuses reflect execution. Select a step to inspect results, approval requirements or blockers.')
        else:
            self.legend.setText('Blue: running · Teal-green: passed · Orange-red: failed · Amber: approval\nMuted cards: blocked or skipped; select them to see why.')
        if self.views.currentIndex() == 1 and self.canvas.order_edges:
            self.legend.setText(self.legend.text() + '\nDotted arrows: wait for completion, not success.')
        if self.views.currentIndex() == 0:
            self.guidance.setText(f'{len(self.plan.phases)} execution steps grouped by purpose. '
                'Expand a stage with its arrow or double-click; select a step for details. '
                'Groups can overlap: prerequisites determine order. Use Dependency map to trace them.')
        else:
            self.guidance.setText(f'Read left to right. Arrows show prerequisites. Up to {self.plan.max_workers} steps can run together. '
                'Hover a card to trace its prerequisites and downstream steps. Other branches stay gray. '
                'Drag to pan; use + to zoom. '
                'Redundant success arrows are omitted; details list every prerequisite.' +
                ('' if self.graph_only else ' Stages returns to the readable step list.'))

        self.scroll.setToolTip(self.guidance.text() + '\nShared junctions mean every incoming prerequisite is required.\n' + self.legend.text())

    def center_map(self):
        self.scroll.fit_map()

    def fit_map(self):
        self.scroll._end_pointer_follow()
        self.scroll.fit_mode = True
        self.scroll.fit_map(force=True)

    def set_facts(self, facts):
        self.facts = facts
        if self.plan:
            self.whole.setChecked(not self.selected)
            self.canvas.update_facts(self.plan, facts, self.selected, self.preview)
            if not getattr(self.plan, 'proposed', False) and not self.graph_only:
                self.browser.update_facts(self.plan, facts, self.selected, self.preview)
            self.center_timer.start(0)

    def select(self, key):
        if self.plan is None or key and not any(phase.id == key for phase in self.plan.phases):
            return
        self.selected = key
        self.set_facts(self.facts)
        self.scroll.reveal(key)
        self.phase_selected.emit(key)
