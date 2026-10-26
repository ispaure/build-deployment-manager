"""Read-only, keyboard-selectable dependency cards shared by review and execution."""
from math import atan2, cos, sin
from PySide6.QtCore import Qt, QPointF, Signal, QTimer, QRectF
from PySide6.QtGui import QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QGridLayout, QLabel, QPushButton,
    QGraphicsScene, QGraphicsView, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget,
    QHeaderView, QStackedWidget, QTreeWidget, QTreeWidgetItem)
from .workflow_icons import NAMES, WorkflowIcons, step_icons

FAILED = {'failed', 'error', 'timeout', 'cancelled', 'interrupted', 'unknown', 'skipped'}
PENDING = {'queued', 'pending', 'planned'}


def title(phase):
    return getattr(phase, 'label', '') or phase.id.replace('.', ' · ').replace('_', ' ').replace('-', ' ').capitalize()


def effect_label(phase, plan):
    if getattr(plan, 'proposed', False):
        return phase.description
    if getattr(phase, 'description', ''):
        return phase.description
    if phase.always:
        return 'Cleanup · runs even after a failure' if phase.kind == 'cleanup' else 'Continue after completion · allows prior failure'
    effect = phase.effect if phase.effect != 'inherit' else plan.effect
    return {'test': 'Run checks', 'inspect': 'Inspect files', 'build': 'Build / package',
            'upload': 'Upload · approval required', 'deploy': 'Deliver · approval required',
            'publish': 'Publish · approval required', 'dispatch': 'Launch checks · approval required'}[effect]


def stage_label(phase, plan):
    """Presentation groups only: execution order still comes from dependencies."""
    effect = phase.effect if phase.effect != 'inherit' else plan.effect
    if phase.always or phase.kind == 'cleanup':
        return 'Cleanup'
    if getattr(phase, 'section', '') == 'source':
        return 'Source'
    return {'inspect': 'Inspection', 'test': 'Checks', 'build': 'Build / package',
            'upload': 'Delivery / publication', 'deploy': 'Delivery / publication',
            'publish': 'Delivery / publication', 'dispatch': 'Checks'}.get(effect, 'Checks')


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
                if self.steps[phase.id].parent() is parent)
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


def layout_positions(phases):
    """Keep each column near its parents, preserving stable sibling order."""
    levels, rows = {}, {}
    for phase in phases:
        parents = (*phase.dependencies, *getattr(phase, 'waits_for', ()))
        level = 1 + max((levels[key] for key in parents), default=-1)
        levels[phase.id] = level
        rows.setdefault(level, []).append(phase)
    width = max((len(row) for row in rows.values()), default=1)
    positions = {}
    for level, row in rows.items():
        def parent_center(phase):
            parents = (*phase.dependencies, *getattr(phase, 'waits_for', ()))
            nearest = max((levels[key] for key in parents), default=-1)
            parents = [key for key in parents if levels[key] == nearest]
            return sum(positions[key][1] for key in parents) / len(parents) if parents else width - 1
        ordered = sorted(row, key=parent_center)
        start = round(sum(parent_center(phase) for phase in ordered) / len(ordered) - len(ordered) + 1)
        for index, phase in enumerate(ordered):
            positions[phase.id] = (level, start + 2 * index)
    offset = min((lane for _, lane in positions.values()), default=0)
    return {key: (level, lane - min(0, offset)) for key, (level, lane) in positions.items()}


def display_states(plan, facts, preview=False):
    """Explain scheduling without turning predicted blocks into execution evidence."""
    states = {}
    for phase in plan.phases:
        fact = facts.get(phase.id, {})
        status = fact.get('status', ('needs_selection' if phase.issue else 'proposed')
            if getattr(plan, 'proposed', False) else 'planned' if preview else 'queued')
        reason = str(fact.get('reason') or fact.get('error') or '')
        blockers = [key for key in phase.dependencies if states[key][0] in FAILED | {'blocked'}]
        if not preview and not phase.always and blockers and (status in PENDING or status.startswith('waiting')):
            status, reason = 'blocked', 'Will not run because a prerequisite did not pass: ' + ', '.join(blockers)
        elif not reason and status in PENDING:
            reason = (('This step waits for its declared prerequisites to finish; it still runs after failure.'
                       if phase.dependencies or getattr(phase, 'waits_for', ()) else
                       'Whole-workflow cleanup waits for owned running work to finish; it still runs after failure.') if phase.always
                      else 'Waits for: ' + ', '.join(phase.dependencies) if phase.dependencies
                      else 'No prerequisites. Scheduling and resources determine when it starts.')
        states[phase.id] = (status, reason)
    return states


def blocking_prerequisite(plan, facts, key):
    """Navigate to recorded failure evidence behind a predicted blocked step."""
    phases = {phase.id: phase for phase in plan.phases}
    states = display_states(plan, facts)
    if key not in phases or states[key][0] not in {'blocked', 'skipped'}:
        return ''
    pending = list(phases[key].dependencies)
    visited = set()
    while pending:
        parent = pending.pop(0)
        if parent in visited:
            continue
        visited.add(parent)
        if states[parent][0] in {'failed', 'error', 'timeout', 'cancelled', 'interrupted', 'unknown'}:
            return parent
        if states[parent][0] in {'blocked', 'skipped'}:
            pending.extend(phases[parent].dependencies)
    return ''


class FlowCard(QPushButton):
    focused = Signal()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focused.emit()

    def sizeHint(self):
        hint = super().sizeHint()
        if self.layout() is not None:
            hint.setHeight(max(hint.height(), self.layout().totalHeightForWidth(self.width())))
        return hint

    def minimumSizeHint(self):
        return self.sizeHint()


class FlowCanvas(QWidget):
    selected = Signal(str)
    focused = Signal(str)

    def __init__(self):
        super().__init__()
        self.cards, self.edges, self.states = {}, [], {}
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(12, 10, 12, 12)
        self.grid.setHorizontalSpacing(48)
        self.grid.setVerticalSpacing(24)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.setStyleSheet('''
            QPushButton#workflowCard { background: palette(base); border: 1px solid palette(mid);
                border-left: 4px solid palette(mid); border-radius: 8px; text-align: left; }
            QPushButton#workflowCard:hover { border-color: palette(highlight); }
            QPushButton#workflowCard:checked { border: 2px solid #245db5; border-left-width: 4px; }
            QPushButton#workflowCard:focus { border: 2px dashed palette(highlight); border-left-width: 4px; }
            QPushButton#workflowCard[state="running"] { border-left-color: #2980b9; }
            QPushButton#workflowCard[state="passed"] { border-left-color: #20834a; }
            QPushButton#workflowCard[state="failed"], QPushButton#workflowCard[state="error"],
            QPushButton#workflowCard[state="timeout"] { border-left-color: #c54040; }
            QPushButton#workflowCard[state="needs_selection"], QPushButton#workflowCard[state="awaiting_review"] { border-left-color: #b37c12; }
            QPushButton#workflowCard[state="blocked"], QPushButton#workflowCard[state="skipped"] {
                background: palette(alternate-base); color: palette(mid); border-left-color: palette(mid); }
        ''')

    def reset(self, plan):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.cards, self.states = {}, {}
        self.headers = []
        self.positions = layout_positions(plan.phases)
        for column in range(self.grid.columnCount()):
            self.grid.setColumnMinimumWidth(column, 0)
        self.order_edges = {(key, phase.id) for phase in plan.phases for key in getattr(phase, 'waits_for', ())}
        self.edges = [(key, phase.id) for phase in plan.phases
                      for key in (*phase.dependencies, *getattr(phase, 'waits_for', ()))]
        compact = getattr(plan, 'proposed', False) or getattr(plan, 'grouped', False)
        width = max(216, self.fontMetrics().horizontalAdvance('Waiting for approval') + 48)
        column_sections = {}
        for phase in plan.phases:
            section = getattr(phase, 'section', '')
            label = {'source': 'Source', 'platforms': 'Testing', 'delivery': 'Delivery'}.get(section)
            if not label:
                effect = phase.effect if phase.effect != 'inherit' else plan.effect
                label = 'Delivery' if effect in {'upload', 'publish', 'deploy'} else 'Build / package' if effect == 'build' else 'Testing'
            column_sections.setdefault(self.positions[phase.id][0], set()).add(label)
        groups = []
        for column, labels in column_sections.items():
            heading = ' / '.join(sorted(labels))
            if groups and groups[-1][0] == heading and groups[-1][1] + groups[-1][2] == column:
                groups[-1][2] += 1
            else:groups.append([heading, column, 1])
        for heading, column, span in groups:
            label = QLabel(heading)
            label.setObjectName('workflowSectionHeader')
            label.setStyleSheet('font-weight: 600; padding-bottom: 8px;')
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(label, 0, column, 1, span)
            self.headers.append(label)
        for phase in plan.phases:
            card = FlowCard()
            card.setObjectName('workflowCard')
            card.setCheckable(True)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            card.focused.connect(lambda key=phase.id: self.focused.emit(key))
            card.setFixedWidth(width)
            card.setMinimumHeight(64 if compact else 100)
            card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            body = QVBoxLayout(card)
            body.setContentsMargins(12, 10, 10, 10)
            body.setSpacing(6)
            heading, kind, status, counts = (QLabel() for _ in range(4))
            heading.setText(title(phase))
            heading.setStyleSheet('font-weight: 600;')
            kind.setText(effect_label(phase, plan))
            icons = step_icons(phase, plan)
            card.setProperty('workflowContext', ' · '.join(NAMES[name] for name in icons))
            badges = QHBoxLayout()
            badges.setSpacing(6)
            badges.addWidget(heading, 1)
            if icons:
                badges.addWidget(WorkflowIcons(icons, card), 0, Qt.AlignmentFlag.AlignTop)
            disclosure = QLabel('›')
            disclosure.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            badges.addWidget(disclosure, 0, Qt.AlignmentFlag.AlignTop)
            body.addLayout(badges)
            for label in (heading, kind, status, counts):
                label.setProperty('workflowHeading', label is heading)
                label.setWordWrap(True)
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                if label is not heading:
                    body.addWidget(label)
            external = phase.id.startswith('deliver.') if compact else (
                phase.effect if phase.effect != 'inherit' else plan.effect) in {'upload', 'deploy', 'publish', 'dispatch'}
            if external:
                badge = QLabel('Approval required')
                badge.setObjectName('approvalBadge')
                badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                badge.setStyleSheet('border: 1px solid #b37c12; border-radius: 4px; padding: 2px 5px;')
                body.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)
            card.clicked.connect(lambda checked=False, key=phase.id: self.selected.emit(key))
            level, lane = self.positions[phase.id]
            self.grid.addWidget(card, lane + 1, level, 2, 1)
            self.cards[phase.id] = (card, status, counts)
        self.adjustSize()
        self.updateGeometry()
        self.update()

    def update_facts(self, plan, facts, selected, preview=False):
        self.states = display_states(plan, facts, preview)
        for phase in plan.phases:
            card, status_label, counts_label = self.cards[phase.id]
            status, reason = self.states[phase.id]
            label = {'proposed': 'Proposed', 'needs_selection': 'Needs selection', 'blocked': 'Won’t run · prerequisite failed', 'planned': 'Planned',
                     'queued': 'Waiting to start', 'waiting_resource': 'Waiting for shared resource', 'awaiting_review': 'Waiting for approval',
                     'skipped': 'Skipped · did not run'}.get(status, status.replace('_', ' ').capitalize())
            fact = facts.get(phase.id, {})
            seconds = fact.get('seconds')
            if seconds is not None and status != 'running':
                from .run_ui import duration
                label += ' · ' + duration(seconds)
            status_label.setText(label)
            status_label.setVisible(status not in {'proposed', 'planned'})
            tests = fact.get('tests', [])
            problems = sum(case['status'] in {'failed', 'error'} for case in tests)
            counts_label.setText(f'{len(tests)} tests · {problems} problems' if tests else '')
            counts_label.setVisible(bool(tests))
            card.setChecked(phase.id == selected)
            badge = card.findChild(QLabel, 'approvalBadge')
            if badge:
                badge.setVisible(status in {'proposed', 'planned', 'pending', 'queued', 'awaiting_review'})
            if card.property('state') != status:
                card.setProperty('state', status)
                card.style().unpolish(card)
                card.style().polish(card)
            muted = status in {'blocked', 'skipped'}
            text_color = '#b3b3b3' if card.palette().base().color().lightness() < 128 else '#626262'
            for child in card.findChildren(QLabel):
                if child.objectName() == 'approvalBadge':
                    continue
                child.setStyleSheet(('font-weight: 600;' if child.property('workflowHeading') else '') +
                    ('color: ' + text_color + ';' if muted else ''))
            card.setMinimumHeight(max(64 if getattr(plan, 'proposed', False) or getattr(plan, 'grouped', False) else 100,
                card.layout().totalHeightForWidth(card.width())))
            context = card.property('workflowContext')
            card.setToolTip('\n'.join(filter(None, (title(phase), context, effect_label(phase, plan), reason, phase.id))))
            card.setAccessibleName(title(phase) + ': ' + label)
            card.setAccessibleDescription('\n'.join(filter(None, (context, reason))))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Section headings belong to visible bands, including a vertical boundary.
        for index, header in enumerate(self.headers):
            rect = header.geometry().adjusted(-16, -4, 16, 0)
            rect.setBottom(self.height() - 2)
            color = self.palette().alternateBase().color()
            color.setAlpha(110 if index % 2 == 0 else 40)
            painter.fillRect(rect, color)
            painter.setPen(QPen(self.palette().mid().color(), 1))
            painter.drawLine(rect.topLeft(), rect.bottomLeft())
        pen = QPen(self.palette().mid().color(), 1.7)
        for source, target in self.edges:
            start_rect, end_rect = self.cards[source][0].geometry(), self.cards[target][0].geometry()
            start, end = QPointF(start_rect.right(), start_rect.center().y()), QPointF(end_rect.left() - 4, end_rect.center().y())
            blocked = self.states.get(target, ('', ''))[0] in {'blocked', 'skipped'}
            pen.setStyle(Qt.PenStyle.DotLine if (source, target) in self.order_edges else
                         Qt.PenStyle.DashLine if blocked else Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            path = QPainterPath(start)
            if self.positions[target][0] > self.positions[source][0] + 1:
                # Route long edges around intervening cards, retaining every dependency.
                gutter = self.height() - 6
                path.lineTo(start.x() + 18, start.y())
                path.lineTo(start.x() + 18, gutter)
                path.lineTo(end.x() - 18, gutter)
                path.lineTo(end.x() - 18, end.y())
                path.lineTo(end)
            else:
                middle = (start.x() + end.x()) / 2
                path.cubicTo(QPointF(middle, start.y()), QPointF(middle, end.y()), end)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            angle = atan2(end.y() - path.pointAtPercent(.97).y(), end.x() - path.pointAtPercent(.97).x())
            painter.setBrush(pen.color())
            painter.drawPolygon(QPolygonF([end, end - QPointF(8 * cos(angle - .45), 8 * sin(angle - .45)),
                                          end - QPointF(8 * cos(angle + .45), 8 * sin(angle + .45))]))


class FitMapView(QGraphicsView):
    scale_changed = Signal(float)
    minimum_scale = 1.0
    maximum_scale = 2.5

    def __init__(self, canvas):
        super().__init__()
        self.canvas, self.fit_mode = canvas, True
        self._fitted = None
        self.anchor = ''
        scene = QGraphicsScene(self); self.setScene(scene); self.proxy = scene.addWidget(canvas)
        self.setBackgroundBrush(canvas.palette().window())
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        canvas.focused.connect(self.reveal)

    def fit_map(self, force=False):
        self.canvas.adjustSize()
        rect = self.proxy.boundingRect().adjusted(-4, -4, 4, 4)
        self.setSceneRect(rect)
        geometry = (rect, self.viewport().size())
        needs_fit = force or self._fitted is None or geometry[1] != self._fitted[1]
        if self.fit_mode and rect.width() and rect.height() and needs_fit:
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            fitted = self.transform().m11()
            scale = max(self.minimum_scale, min(1.35, fitted))
            self.resetTransform(); self.scale(scale, scale)
            self._fitted = (rect, self.viewport().size())
            if fitted < self.minimum_scale:
                self.reveal(self.anchor if self.anchor in self.canvas.cards else next(iter(self.canvas.cards), ''))
            self.scale_changed.emit(scale)
        elif self.fit_mode:
            self._fitted = geometry

    def reveal(self, key):
        if key in self.canvas.cards:
            self.anchor = key
            self.ensureVisible(self.proxy.mapRectToScene(QRectF(self.canvas.cards[key][0].geometry())), 24, 24)

    def reset_view(self):
        self.fit_mode, self._fitted, self.anchor = True, None, ''

    def zoom(self, amount):
        self.fit_mode = False
        current = self.transform().m11()
        scale = max(self.minimum_scale, min(self.maximum_scale, current * amount))
        self.scale(scale / current, scale / current)
        self.scale_changed.emit(scale)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_map()


class WorkflowFlow(QWidget):
    phase_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.plan, self.facts, self.selected, self.preview = None, {}, '', False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.whole = QPushButton('Whole workflow')
        self.whole.setCheckable(True)
        self.whole.clicked.connect(lambda: self.select(''))
        tools = QHBoxLayout(); tools.setContentsMargins(0, 0, 0, 0)
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
        for control, name in ((self.fit_button, 'Fit readable cards'), (self.zoom_in, 'Zoom in'), (self.zoom_out, 'Zoom out')):
            control.setAccessibleName(name); control.setToolTip(name); control.setMaximumWidth(52); tools.addWidget(control)
        layout.addLayout(tools)
        self.guidance = QLabel('Read left to right. Arrows show prerequisites. Branches can overlap when workers and resources allow. Select a card for details.')
        self.guidance.setWordWrap(True)
        layout.addWidget(self.guidance)
        self.canvas = FlowCanvas()
        self.scroll = FitMapView(self.canvas)
        self.scroll.setAccessibleName('Workflow dependency map. Scroll or drag to pan. Tab between cards; Space selects a step.')
        self.scroll.scale_changed.connect(lambda scale: self.zoom_out.setEnabled(scale > self.scroll.minimum_scale))
        self.scroll.scale_changed.connect(lambda scale: self.zoom_in.setEnabled(scale < self.scroll.maximum_scale))
        self.fit_button.clicked.connect(self.fit_map)
        self.zoom_in.clicked.connect(lambda: self.scroll.zoom(1.2))
        self.zoom_out.clicked.connect(lambda: self.scroll.zoom(1 / 1.2))
        self.browser = StageBrowser()
        self.browser.selected.connect(self.select)
        self.views = QStackedWidget()
        self.views.addWidget(self.browser)
        self.views.addWidget(self.scroll)
        layout.addWidget(self.views, 1)
        self.legend = legend = QLabel('Blue: running · Green: passed · Red: failed · Amber: approval\nMuted cards: blocked or skipped; select them to see why.')
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
        self.guidance.setVisible(not proposed)
        self.legend.setVisible(not proposed)
        if not proposed:
            self.browser.load_plan(plan)
        self.stages_button.setVisible(not proposed)
        self.map_button.setVisible(not proposed)
        self.show_map(proposed)
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

    def show_map(self, visible):
        self.views.setCurrentIndex(1 if visible else 0)
        self.stages_button.setChecked(not visible)
        self.map_button.setChecked(visible)
        for control in (self.fit_button, self.zoom_in, self.zoom_out):
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
            self.legend.setText('Blue: running · Green: passed · Red: failed · Amber: approval\nMuted cards: blocked or skipped; select them to see why.')
        if self.views.currentIndex() == 1 and self.canvas.order_edges:
            self.legend.setText(self.legend.text() + '\nDotted arrows: wait for completion, not success.')
        if self.views.currentIndex() == 0:
            self.guidance.setText(f'{len(self.plan.phases)} execution steps grouped by purpose. '
                'Expand a stage with its arrow or double-click; select a step for details. '
                'Groups can overlap: prerequisites determine order. Use Dependency map to trace them.')
        else:
            self.guidance.setText(f'Read left to right. Arrows show prerequisites. Up to {self.plan.max_workers} steps can run together. '
                'Drag to pan; use + to zoom. Stages returns to the readable step list.')

    def center_map(self):
        self.scroll.fit_map()

    def fit_map(self):
        self.scroll.fit_mode = True
        self.scroll.fit_map(force=True)

    def set_facts(self, facts):
        self.facts = facts
        if self.plan:
            self.whole.setChecked(not self.selected)
            self.canvas.update_facts(self.plan, facts, self.selected, self.preview)
            if not getattr(self.plan, 'proposed', False):
                self.browser.update_facts(self.plan, facts, self.selected, self.preview)
            self.center_timer.start(0)

    def select(self, key):
        if self.plan is None or key and key not in self.canvas.cards:
            return
        self.selected = key
        self.set_facts(self.facts)
        self.scroll.reveal(key)
        self.phase_selected.emit(key)
