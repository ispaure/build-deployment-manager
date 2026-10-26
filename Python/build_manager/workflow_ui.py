"""Read-only, keyboard-selectable dependency cards shared by review and execution."""
from math import atan2, cos, sin
from PySide6.QtCore import Qt, QPointF, Signal, QTimer
from PySide6.QtGui import QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QGridLayout, QLabel, QPushButton,
    QGraphicsScene, QGraphicsView, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget)

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
            reason = ('This step waits for prerequisites and running work to finish; it still runs after failure.' if phase.always
                      else 'Waits for: ' + ', '.join(phase.dependencies) if phase.dependencies
                      else 'No prerequisites. Scheduling and resources determine when it starts.')
        states[phase.id] = (status, reason)
    return states


class FlowCard(QPushButton):
    def sizeHint(self):
        hint = super().sizeHint()
        if self.layout() is not None:
            hint.setHeight(max(hint.height(), self.layout().totalHeightForWidth(self.width())))
        return hint

    def minimumSizeHint(self):
        return self.sizeHint()


class FlowCanvas(QWidget):
    selected = Signal(str)

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
            QPushButton#workflowCard[state="running"] { border-left-color: #2980b9; }
            QPushButton#workflowCard[state="passed"] { border-left-color: #20834a; }
            QPushButton#workflowCard[state="failed"], QPushButton#workflowCard[state="error"],
            QPushButton#workflowCard[state="timeout"] { border-left-color: #c54040; }
            QPushButton#workflowCard[state="needs_selection"], QPushButton#workflowCard[state="awaiting_review"] { border-left-color: #b37c12; }
            QPushButton#workflowCard[state="blocked"], QPushButton#workflowCard[state="skipped"] {
                background: palette(alternate-base); color: palette(mid); border-left-color: palette(mid); }
            QPushButton#workflowCard:checked { border: 2px solid palette(highlight); }
            QPushButton#workflowCard:focus { border: 2px solid palette(highlight); }
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
        width = 176 if getattr(plan, 'proposed', False) else 184
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
            card.setFixedWidth(width)
            card.setMinimumHeight(64 if getattr(plan, 'proposed', False) else 100)
            card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
            body = QVBoxLayout(card)
            body.setContentsMargins(9, 7, 7, 7)
            body.setSpacing(4)
            heading, kind, status, counts = (QLabel() for _ in range(4))
            heading.setText(title(phase))
            heading.setStyleSheet('font-weight: 600;')
            kind.setText(effect_label(phase, plan))
            for label in (heading, kind, status, counts):
                label.setProperty('workflowHeading', label is heading)
                label.setWordWrap(True)
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                body.addWidget(label)
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
                     'queued': 'Waiting to start', 'awaiting_review': 'Waiting for approval',
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
            if card.property('state') != status:
                card.setProperty('state', status)
                card.style().unpolish(card)
                card.style().polish(card)
            muted = status in {'blocked', 'skipped'}
            text_color = '#b3b3b3' if card.palette().base().color().lightness() < 128 else '#626262'
            for child in card.findChildren(QLabel):
                child.setStyleSheet(('font-weight: 600;' if child.property('workflowHeading') else '') +
                    ('color: ' + text_color + ';' if muted else ''))
            card.setMinimumHeight(max(64 if getattr(plan, 'proposed', False) else 100,
                card.layout().totalHeightForWidth(card.width())))
            card.setToolTip(title(phase) + '\n' + effect_label(phase, plan) + '\n' + reason + '\n' + phase.id)
            card.setAccessibleName(title(phase) + ': ' + label)
            card.setAccessibleDescription(reason)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
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
    def __init__(self, canvas):
        super().__init__()
        self.canvas, self.fit_mode = canvas, True
        scene = QGraphicsScene(self); self.setScene(scene); self.proxy = scene.addWidget(canvas)
        self.setBackgroundBrush(canvas.palette().window())
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)

    def fit_map(self):
        self.canvas.adjustSize()
        rect = self.proxy.boundingRect().adjusted(-4, -4, 4, 4)
        self.setSceneRect(rect)
        if self.fit_mode and rect.width() and rect.height():
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            # Keep small graphs at readable native size, centered in the viewport.
            if self.transform().m11() > 1.35:
                self.resetTransform(); self.scale(1.35, 1.35)

    def zoom(self, amount):
        self.fit_mode = False
        if .08 <= self.transform().m11() * amount <= 2.5:self.scale(amount, amount)

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
        tools.addWidget(self.whole); tools.addStretch()
        self.fit_button, self.zoom_in, self.zoom_out = QPushButton('Fit'), QPushButton('+'), QPushButton('−')
        for control, name in ((self.fit_button, 'Fit whole workflow'), (self.zoom_in, 'Zoom in'), (self.zoom_out, 'Zoom out')):
            control.setAccessibleName(name); control.setToolTip(name); control.setMaximumWidth(52); tools.addWidget(control)
        layout.addLayout(tools)
        self.guidance = QLabel('Read left to right. Arrows show prerequisites. Branches can overlap when workers and resources allow. Select a card for details.')
        self.guidance.setWordWrap(True)
        layout.addWidget(self.guidance)
        self.canvas = FlowCanvas()
        self.scroll = FitMapView(self.canvas)
        self.scroll.setAccessibleName('Workflow dependency map. Fit shows the whole flow; zoom for details. Tab between cards; Space selects a step.')
        self.fit_button.clicked.connect(self.fit_map)
        self.zoom_in.clicked.connect(lambda: self.scroll.zoom(1.2))
        self.zoom_out.clicked.connect(lambda: self.scroll.zoom(1 / 1.2))
        layout.addWidget(self.scroll, 1)
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
        self.whole.setVisible(not getattr(plan, 'proposed', False))
        if getattr(plan, 'proposed', False):
            self.whole.setText('Overview')
            self.guidance.setText('Select a card to configure it. Read left to right. Arrows show the order.')
            self.legend.setText('Review resolves the exact steps. Nothing starts here.')
        else:
            self.whole.setText('Reviewed plan' if preview else 'Whole workflow')
            self.guidance.setText(f'Read left to right. Arrows show prerequisites. Up to {plan.max_workers} steps can run together, subject to shared resources. Select a card for details.')
            self.legend.setText('Prepared plan · not started. Select a card for its exact prerequisites.' if preview else
                'Blue: running · Green: passed · Red: failed · Amber: approval\nMuted cards: blocked or skipped; select them to see why.')
        if self.canvas.order_edges:
            self.legend.setText(self.legend.text() + '\nDotted arrows: wait for completion, not success.')
        self.set_facts({})
        self.scroll.verticalScrollBar().setValue(0)
        self.center_timer.start(0)

    def center_map(self):
        self.scroll.fit_map()

    def fit_map(self):
        self.scroll.fit_mode = True
        self.scroll.fit_map()

    def set_facts(self, facts):
        self.facts = facts
        if self.plan:
            self.whole.setChecked(not self.selected)
            self.canvas.update_facts(self.plan, facts, self.selected, self.preview)
            self.center_timer.start(0)

    def select(self, key):
        if self.plan is None or key and key not in self.canvas.cards:
            return
        self.selected = key
        self.set_facts(self.facts)
        self.phase_selected.emit(key)
