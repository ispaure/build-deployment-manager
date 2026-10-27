"""Read-only, keyboard-selectable dependency cards shared by review and execution."""
from PySide6.QtCore import Qt, QPointF, Signal, QTimer, QRectF, QEvent
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QTransform, QTextLayout, QTextOption
from PySide6.QtWidgets import (QGridLayout, QLabel, QPushButton,
    QGraphicsScene, QGraphicsView, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget,
    QComboBox, QHeaderView, QProgressBar, QStackedWidget, QTreeWidget, QTreeWidgetItem)
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
    if effect == 'deploy' and not getattr(phase, 'approval_required', True):
        return 'Deliver to selected device'
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


def layout_positions(phases):
    """Keep each column near its parents, preserving stable sibling order."""
    levels, rows = {}, {}
    visible = {phase.id for phase in phases}
    for phase in phases:
        parents = [key for key in (*phase.dependencies, *getattr(phase, 'waits_for', ())) if key in visible]
        level = 1 + max((levels[key] for key in parents), default=-1)
        levels[phase.id] = level
        rows.setdefault(level, []).append(phase)
    width = max((len(row) for row in rows.values()), default=1)
    positions = {}
    for level, row in rows.items():
        def parent_center(phase):
            parents = [key for key in (*phase.dependencies, *getattr(phase, 'waits_for', ())) if key in visible]
            nearest = max((levels[key] for key in parents), default=-1)
            parents = [key for key in parents if levels[key] == nearest]
            return sum(positions[key][1] for key in parents) / len(parents) if parents else width - 1
        ordered = sorted(row, key=parent_center)
        start = round(sum(parent_center(phase) for phase in ordered) / len(ordered) - len(ordered) + 1)
        for index, phase in enumerate(ordered):
            positions[phase.id] = (level, start + 2 * index)
    offset = min((lane for _, lane in positions.values()), default=0)
    return {key: (level, lane - min(0, offset)) for key, (level, lane) in positions.items()}


def visible_dependencies(phases):
    """Omit success arrows already implied by a visible success-only path.

    Completion waits and always-run steps do not propagate success, so they
    must never be used to hide a success requirement. Always-run targets only
    require completion, so their incoming arrows can use completion paths.
    Reduce only the drawing;
    the original plan remains the source for scheduling and inspection.
    """
    phases = {phase.id: phase for phase in phases}
    ancestors, completed_ancestors = {}, {}
    for key in phases:
        seen, pending = set(), [key]
        while pending:
            phase = phases[pending.pop()]
            if phase.always:
                continue
            for parent in phase.dependencies:
                if parent in phases and parent not in seen:
                    seen.add(parent)
                    pending.append(parent)
        ancestors[key] = seen
        seen, pending = set(), [key]
        while pending:
            phase = phases[pending.pop()]
            for parent in (*phase.dependencies, *getattr(phase, 'waits_for', ())):
                if parent in phases and parent not in seen:
                    seen.add(parent)
                    pending.append(parent)
        completed_ancestors[key] = seen
    edges = []
    for phase in phases.values():
        parents = [key for key in phase.dependencies if key in phases]
        implied = completed_ancestors if phase.always else ancestors
        alternatives = parents + ([key for key in getattr(phase, 'waits_for', ()) if key in phases]
                                  if phase.always else [])
        for parent in parents:
            if not any(parent in implied[other] for other in alternatives if other != parent):
                edges.append((parent, phase.id))
        edges.extend((key, phase.id) for key in getattr(phase, 'waits_for', ()) if key in phases)
    return edges


def connection_groups(edges, positions, order_edges=(), states=None, completion_targets=()):
    """Bundle only identical prerequisites with matching meaning and line style.

    Expanding each group's sources × targets reconstructs exactly the drawn
    graph. Long connections stay separate from adjacent-column junctions.
    """
    incoming = {}
    for source, target in edges:
        style = 'completion' if (source, target) in order_edges else (
            'blocked' if (states or {}).get(target, ('', ''))[0] in {'blocked', 'skipped'} else 'success')
        incoming.setdefault((target, positions[source][0], style), []).append(source)
    groups = {}
    for (target, level, style), sources in incoming.items():
        sources = tuple(sorted(set(sources)))
        adjacent = positions[target][0] == level + 1
        signature = (sources, positions[target][0], style, target in completion_targets,
                     None if adjacent else target)
        groups.setdefault(signature, []).append(target)
    return [(sources, tuple(targets), style)
            for (sources, _, style, _, _), targets in groups.items()]


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


def state_label(status):
    return {'proposed': 'Proposed', 'needs_selection': 'Needs selection',
        'blocked': 'Won’t run · prerequisite failed', 'planned': 'Planned',
        'queued': 'Waiting to start', 'pending': 'Waiting to start',
        'waiting_resource': 'Waiting for shared resource', 'awaiting_review': 'Waiting for approval',
        'retrying': 'Waiting to reconnect',
        'skipped': 'Skipped'}.get(status, status.replace('_', ' ').capitalize())


def step_time(fact, status):
    """Never present a never-started step's synthetic zero as measured runtime."""
    from .run_ui import duration
    if status in {'queued', 'pending', 'planned', 'blocked', 'skipped', 'waiting_resource'}:
        return 'Not started' if not fact.get('seconds') else duration(fact['seconds'])
    return duration(fact.get('seconds')) if fact.get('seconds') is not None else ''


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


class CardActivityLabel(QLabel):
    """Bound live text to reserved lines without changing the card geometry."""

    def __init__(self, lines):
        super().__init__()
        self.lines = lines
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.reserve_lines()

    def reserve_lines(self):
        self.setFixedHeight(self.fontMetrics().lineSpacing() * self.lines + 4)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self.reserve_lines()

    def setText(self, text):
        if text != self.text():
            super().setText(text)
            self.setToolTip(text)
            self.setAccessibleName(text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(self.foregroundRole()))
        text = self.text().replace('\n', ' · ')
        layout = QTextLayout(text, self.font())
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        top = 2
        for index in range(self.lines):
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(self.width())
            if index == self.lines - 1:
                tail = self.fontMetrics().elidedText(text[line.textStart():], Qt.TextElideMode.ElideRight, self.width())
                painter.drawText(QRectF(0, top, self.width(), self.fontMetrics().lineSpacing()),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, tail)
            else:
                line.draw(painter, QPointF(0, top))
            top += self.fontMetrics().lineSpacing()
        layout.endLayout()


class TimeShare(QWidget):
    """Keep timing text outside the native progress groove, at any font size."""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 1, 4, 3)
        layout.setSpacing(2)
        self.label = QLabel()
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(4)
        layout.addWidget(self.label)
        layout.addWidget(self.bar)
        self.setAutoFillBackground(True)


def time_share(tree, row, seconds, total):
    from .run_ui import duration
    if seconds is None or not total or total <= 0:
        tree.removeItemWidget(row, 2)
        row.setText(2, duration(seconds))
        return
    ancestor = row.parent()
    while ancestor is not None:
        if not ancestor.isExpanded():
            tree.removeItemWidget(row, 2)
            row.setText(2, f'{duration(seconds)} · {seconds / total:.0%}')
            return
        ancestor = ancestor.parent()
    cell = tree.itemWidget(row, 2)
    if not isinstance(cell, TimeShare):
        cell = TimeShare()
        tree.setItemWidget(row, 2, cell)
    bar = cell.bar
    share = seconds / total
    bar.setValue(min(1000, round(share * 1000)))
    bar.setFormat(f'{duration(seconds)} · {share:.0%}')
    cell.label.setText(bar.format())
    cell.setAccessibleName(f'{row.text(0)}: {duration(seconds)}, {share:.1%} of parent reported time')
    cell.setToolTip('Share of parent reported time. Includes measured running time; parallel work may overlap. Not an estimate of completion.')
    hint = cell.sizeHint()
    if row.sizeHint(2) != hint:
        row.setSizeHint(2, hint)


def current_test_seconds(case):
    from datetime import datetime, timezone
    try:
        return max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(case['started_at'])).total_seconds())
    except (KeyError, ValueError, TypeError):
        return case.get('seconds')


def visible_tree_rows(row):
    return 1 + (sum(visible_tree_rows(row.child(index)) for index in range(row.childCount())) if row.isExpanded() else 0)


def update_test_children(row, key, fact, phase=None, *, force=False):
    """Render task → declared file → observed test, retaining item identities."""
    from .run_ui import duration
    files = {name: dict(name=name, kind='file', status='planned', seconds=None,
                       message='Individual tests are discovered when this file starts.')
             for name in getattr(phase, 'test_files', ())}
    for info in fact.get('test_files', ()):
        files[info['name']] = dict(info, kind='file')
        if info.get('status') == 'running':
            files[info['name']]['seconds'] = current_test_seconds(info)
    cases = list(fact.get('tests') or fact.get('live_tests', ()))
    current = fact.get('current_test')
    if current:
        current = dict(current, seconds=current_test_seconds(current))
        cases.append(current)
    children = {name: [] for name in files}
    roots = []
    for case in cases:
        name = case.get('file')
        if name:
            if name not in files:
                files[name] = dict(name=name, kind='file', status='running' if current else 'reported')
                children[name] = []
            children[name].append((case, []))
        else:
            roots.append((case, []))
    for name, info in files.items():
        from pathlib import PurePosixPath
        parts = PurePosixPath(name.replace('\\', '/')).parts
        container = roots
        for index, part in enumerate(parts[:-1]):
            path = '/'.join(parts[:index + 1])
            folder = next((node for node in container if node[0].get('kind') == 'folder' and node[0].get('path') == path), None)
            if folder is None:
                folder = (dict(name=part, path=path, kind='folder', status='planned'), [])
                container.append(folder)
            container = folder[1]
        container.append((dict(info, name=parts[-1] if parts else name, file=name), children[name]))

    def summarize(nodes):
        for info, nested in nodes:
            summarize(nested)
            if info.get('kind') == 'folder':
                measured = [child['seconds'] for child, _ in nested if child.get('seconds') is not None]
                info['seconds'] = sum(measured) if measured else None
                statuses = {child.get('status') for child, _ in nested}
                info['status'] = next((state for state in ('running', 'failed', 'error', 'timeout', 'crashed', 'cancelled', 'interrupted', 'reported', 'planned', 'pending')
                                       if state in statuses), 'passed')
    summarize(roots)
    if not roots and phase is not None and 'junit' in phase.artifact_types.values():
        roots.append((dict(name='Test list not declared by this project', kind='info', status='pending',
            message='Individual tests appear when the runner reports them.'), []))
    # Tick only the current test's elapsed display; completed rows remain stable.
    signature = repr((roots, bool(fact.get('tests_provisional')), round(fact.get('seconds') or 0)))
    if not force and getattr(row, '_test_signature', None) == signature:
        return
    row._test_signature = signature
    tree = row.treeWidget()
    selected = tree.currentItem()

    def sync(parent, nodes, total):
        existing = {getattr(parent.child(i), '_test_identity', None): parent.child(i) for i in range(parent.childCount())}
        keep = set()
        for index, (case, nested) in enumerate(nodes):
            identity = (case.get('kind', 'test'), case.get('path'), case.get('file'), case.get('classname'), case['name'])
            child = existing.get(identity)
            if child is None:
                child = QTreeWidgetItem()
                child._test_identity = identity
            old_index = parent.indexOfChild(child)
            if old_index != index:
                if old_index >= 0:
                    parent.takeChild(old_index)
                parent.insertChild(index, child)
            keep.add(id(child))
            child.setText(0, case['name'])
            child.setText(1, case['status'].capitalize())
            child.setText(2, duration(case.get('seconds')))
            child.setData(0, Qt.ItemDataRole.UserRole, key)
            child.setData(0, Qt.ItemDataRole.UserRole + 1, case)
            child.setToolTip(0, '\n'.join(filter(None, (case.get('path'), case.get('file'), case.get('classname'), case.get('suite'), case.get('message')))))
            time_share(tree, child, case.get('seconds'), total)
            sync(child, nested, case.get('seconds'))
        for index in range(parent.childCount() - 1, -1, -1):
            if id(parent.child(index)) not in keep:
                parent.takeChild(index)

    sync(row, roots, fact.get('seconds'))
    if selected is not None and selected.treeWidget() is tree:
        tree.setCurrentItem(selected)


class FlowCanvas(QWidget):
    selected = Signal(str)
    focused = Signal(str)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.selected.emit('')
        super().mousePressEvent(event)

    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.cards, self.edges, self.states = {}, [], {}
        self.headers, self.order_edges, self.positions = [], set(), {}
        self.completion_targets = set()
        self.vertical = False
        self.adaptive = False
        self.header_positions = []
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(12, 10, 12, 12)
        self.grid.setHorizontalSpacing(48)
        self.grid.setVerticalSpacing(24)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.setStyleSheet('''
            QPushButton#workflowCard { background: palette(base); border: 1px solid palette(mid);
                border-radius: 8px; text-align: left; }
            QPushButton#workflowCard:hover { border-color: palette(highlight); }
            QPushButton#workflowCard:checked, QPushButton#workflowCard:focus { border-color: palette(highlight); }
            QProgressBar#cardProgress { border: 1px solid palette(mid); border-radius: 3px;
                background: palette(base); color: palette(text); text-align: center; }
            QProgressBar#cardProgress::chunk { background: #69acd5; }
        ''')

    def style_card(self, card, status):
        dark = self.palette().window().color().lightness() < 128
        kind = ('passed' if status in {'passed', 'captured'} else
                'failed' if status in FAILED - {'skipped'} else
                'muted' if status in {'blocked', 'skipped'} else
                'awaiting_review' if status == 'needs_selection' else status)
        colors = ({
            'passed': ('#1e4431', '#d0f2dc', '#5aab79'),
            'failed': ('#542c32', '#ffdce0', '#cf7885'),
            'running': ('#1d3c5a', '#d5e9ff', '#75ace0'),
            'awaiting_review': ('#4c3d20', '#ffebbb', '#c7a055'),
            'muted': ('#292d33', '#a5acb6', '#646b75'),
        } if dark else {
            'passed': ('#dff2e4', '#173d24', '#609771'),
            'failed': ('#f8dede', '#632020', '#b76f6f'),
            'running': ('#deecfb', '#163e69', '#4d86bd'),
            'awaiting_review': ('#fff0cf', '#604500', '#b58a2e'),
            'muted': ('#eceef1', '#626262', '#a0a6ae'),
        }).get(kind)
        background, text, border = colors or ('palette(base)', 'palette(text)', 'palette(mid)')
        stylesheet = f'''
            QPushButton#workflowCard {{ background: {background}; color: {text};
                border: 2px solid {border}; border-radius: 8px; text-align: left; }}
            QPushButton#workflowCard:hover, QPushButton#workflowCard:checked,
            QPushButton#workflowCard:focus {{ border: 2px solid palette(highlight); }}
            QPushButton#workflowCard QLabel {{ color: {text}; background: transparent; }}
        '''
        if card.styleSheet() != stylesheet:
            card.setStyleSheet(stylesheet)
        for child in card.findChildren(QLabel):
            if child.objectName() == 'approvalBadge':
                continue
            style = 'font-weight: 600;' if child.property('workflowHeading') else ''
            if child.styleSheet() != style:
                child.setStyleSheet(style)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange}:
            for card, _, _ in getattr(self, 'cards', {}).values():
                self.style_card(card, card.property('state') or '')
            self.update()

    def reset(self, plan, keys=None, *, reserve_activity=None):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.cards, self.states = {}, {}
        self.headers = []
        self.header_positions = []
        self.adaptive = True
        if not self.adaptive:
            self.vertical = False
        keys = set(keys) if keys is not None else {phase.id for phase in plan.phases}
        # Filter only the drawing. Statuses, inspection and execution keep the
        # original plan, including prerequisites outside this card.
        phases = tuple(phase for phase in plan.phases if phase.id in keys)
        self.positions = layout_positions(phases)
        for column in range(self.grid.columnCount()):
            self.grid.setColumnMinimumWidth(column, 0)
        self.order_edges = {(key, phase.id) for phase in phases for key in getattr(phase, 'waits_for', ()) if key in keys}
        self.edges = visible_dependencies(phases)
        self.completion_targets = {phase.id for phase in phases if phase.always}
        compact = getattr(plan, 'proposed', False) or getattr(plan, 'grouped', False)
        self.compact = compact
        if reserve_activity is None:
            reserve_activity = not compact
        width = max(216, self.fontMetrics().horizontalAdvance('Waiting for approval') + 48)
        self.base_card_width = width
        self.base_card_height = 64 if compact else 100
        column_sections = {}
        for phase in phases:
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
            self.header_positions.append((column, span))
        for phase in phases:
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
            heading, kind = QLabel(), QLabel()
            status = CardActivityLabel(1) if reserve_activity else QLabel()
            counts = CardActivityLabel(2) if reserve_activity else QLabel()
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
            external = external and getattr(phase, 'approval_required', True)
            if external:
                badge = QLabel('Approval required')
                badge.setObjectName('approvalBadge')
                badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                badge.setStyleSheet('border: 1px solid #b37c12; border-radius: 4px; padding: 2px 5px;')
                body.addWidget(badge, 0, Qt.AlignmentFlag.AlignLeft)
            progress = QProgressBar(card)
            progress.setObjectName('cardProgress')
            progress.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            progress.setFixedHeight(18)
            progress.setAccessibleName('Completed subtasks')
            progress.hide()
            body.addWidget(progress)
            if reserve_activity:
                for widget in (status, counts, progress, card.findChild(QLabel, 'approvalBadge')):
                    if widget is not None:
                        policy = widget.sizePolicy()
                        policy.setRetainSizeWhenHidden(True)
                        widget.setSizePolicy(policy)
            card.clicked.connect(lambda checked=False, key=phase.id: self.selected.emit(key))
            level, lane = self.positions[phase.id]
            self.grid.addWidget(card, lane + 1, level, 2, 1)
            self.cards[phase.id] = (card, status, counts)
        self.arrange(self.vertical)
        self.adjustSize()
        self.updateGeometry()
        self.update()

    def arrange(self, vertical):
        self.vertical = vertical
        self.grid.setAlignment(Qt.AlignmentFlag(0) if getattr(self, 'compact', False) else
                               Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.grid.setHorizontalSpacing(24 if vertical else 48)
        self.grid.setVerticalSpacing(48 if vertical else 24)
        for label, (column, span) in zip(self.headers, self.header_positions):
            self.grid.removeWidget(label)
            label.setWordWrap(vertical)
            label.setMaximumWidth(96 if vertical else 16777215)
            label.setMaximumHeight(16777215 if vertical else label.fontMetrics().lineSpacing() + 8)
            if vertical:
                self.grid.addWidget(label, column, 0, span, 1)
            else:
                self.grid.addWidget(label, 0, column, 1, span)
        for key, (card, _, _) in self.cards.items():
            level, lane = self.positions[key]
            self.grid.removeWidget(card)
            if vertical:
                self.grid.addWidget(card, level, lane + 1, 1, 2, Qt.AlignmentFlag.AlignCenter)
            else:
                self.grid.addWidget(card, lane + 1, level, 2, 1, Qt.AlignmentFlag.AlignCenter)
        self.adjustSize()
        self.updateGeometry()
        self.update()

    def adapt_to(self, size, orientation='best'):
        if not self.adaptive or not self.cards:
            return
        if self.compact:
            self.adapt_overview(size, orientation)
            return
        levels = max(level for level, _ in self.positions.values()) + 1
        lanes = max(sum(level == column for level, _ in self.positions.values()) for column in range(levels))
        width = max(card.width() for card, _, _ in self.cards.values())
        height = max(card.minimumSizeHint().height() for card, _, _ in self.cards.values())
        horizontal = (levels * width + (levels - 1) * 48 + 24,
                      lanes * height + (lanes - 1) * 24 + 60)
        vertical = (lanes * width + (lanes - 1) * 24 + 110,
                    levels * height + (levels - 1) * 48 + 24)
        horizontal_fit = min(size.width() / horizontal[0], size.height() / horizontal[1])
        vertical_fit = min(size.width() / vertical[0], size.height() / vertical[1])
        upright = orientation == 'vertical' or (orientation == 'best' and
            horizontal[0] > size.width() and vertical_fit > horizontal_fit * 1.15)
        if upright != self.vertical:
            self.arrange(upright)

    def adapt_overview(self, size, orientation):
        """Reflow within modest card widths before shrinking the whole map.

        Measure wrapped labels in the actual layout, including reserved activity
        space. Never rebuild cards: selection, keyboard focus and live facts stay
        attached to the same widgets. Explicit orientations remain authoritative.
        """
        widths = [round(self.base_card_width * factor) for factor in (.88, 1, 1.12, 1.24)]
        directions = (False, True) if orientation == 'best' else (orientation == 'vertical',)
        best = None
        for vertical in directions:
            for width in widths:
                for card, _, _ in self.cards.values():
                    card.setFixedWidth(width)
                    card.ensurePolished()
                    card.layout().invalidate()
                    card.setMinimumHeight(max(self.base_card_height,
                                              card.layout().totalHeightForWidth(width)))
                self.arrange(vertical)
                self.grid.invalidate()
                bounds = self.sizeHint()
                scale = min((size.width() - 12) / max(1, bounds.width()),
                            (size.height() - 12) / max(1, bounds.height()), 1.35)
                # Readable type comes first; prefer comfortable wrapping over
                # oversized cards when several layouts fit equally well.
                score = scale - .035 * abs(width / self.base_card_width - 1)
                candidate = (score, vertical, width)
                if best is None or score > best[0] + .005:
                    best = candidate
        _, vertical, width = best
        for card, _, _ in self.cards.values():
            card.setFixedWidth(width)
            card.layout().invalidate()
            card.setMinimumHeight(max(self.base_card_height,
                                      card.layout().totalHeightForWidth(width)))
        self.arrange(vertical)

    def update_facts(self, plan, facts, selected, preview=False):
        self.states = display_states(plan, facts, preview)
        for phase in plan.phases:
            if phase.id not in self.cards:
                continue
            card, status_label, counts_label = self.cards[phase.id]
            status, reason = self.states[phase.id]
            label = state_label(status)
            fact = facts.get(phase.id, {})
            elapsed = step_time(fact, status)
            if elapsed and not preview:
                label += ' · ' + elapsed
            status_label.setText(label)
            status_label.setVisible(status not in {'proposed', 'planned'})
            tests = fact.get('tests') or fact.get('live_tests', [])
            problems = sum(case['status'] in {'failed', 'error'} for case in tests)
            counts_label.setText((f'{len(tests)} reported tests · suite running' if fact.get('tests_provisional') else
                f'{len(tests)} tests · {problems} problems') if tests else '')
            counts_label.setVisible(bool(tests))
            if fact.get('current_test'):
                current = fact['current_test']
                counts_label.setText(f'Running: {current["name"]} · ' +
                    step_time(dict(seconds=current_test_seconds(current)), 'running'))
                counts_label.show()
            progress = card.findChild(QProgressBar, 'cardProgress')
            progress.setVisible(status == 'running')
            completed, total = fact.get('completed', 0), fact.get('total', 0)
            progress.setRange(0, total)
            progress.setValue(completed)
            progress.setFormat(f'{completed}/{total} steps finished' if total else 'Running')
            card.setChecked(phase.id == selected)
            badge = card.findChild(QLabel, 'approvalBadge')
            if badge:
                badge.setVisible(status in {'proposed', 'planned', 'pending', 'queued', 'awaiting_review'})
            if card.property('state') != status:
                card.setProperty('state', status)
                card.style().unpolish(card)
                card.style().polish(card)
            self.style_card(card, status)
            context = card.property('workflowContext')
            card.setToolTip('\n'.join(filter(None, (title(phase), context, effect_label(phase, plan), reason,
                counts_label.text() if not counts_label.isHidden() else '', phase.id))))
            card.setAccessibleName(title(phase) + ': ' + label)
            card.setAccessibleDescription('\n'.join(filter(None, (context, reason,
                counts_label.text() if not counts_label.isHidden() else ''))))
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Tinted section bands stay distinct from dependency connectors.
        for index, header in enumerate(self.headers):
            rect = header.geometry().adjusted(-4, -16, 0, 16) if self.vertical else header.geometry().adjusted(-16, -4, 16, 0)
            if self.vertical:
                rect.setRight(self.width() - 2)
            else:
                rect.setBottom(self.height() - 2)
            color = QColor({'Source': '#7296ca', 'Testing': '#71ab8b',
                            'Delivery': '#d6aa64', 'Build / package': '#aa8ac4'}.get(header.text(), '#8998ac'))
            color.setAlpha(30 if self.palette().window().color().lightness() >= 128 else 42)
            painter.fillRect(rect, color)
        pen = QPen(self.palette().mid().color(), 1.7)
        groups = connection_groups(self.edges, self.positions, self.order_edges,
                                   self.states, self.completion_targets)
        long_lane = 0
        if self.vertical:
            painter.setTransform(QTransform(0, 1, 1, 0, 0, 0))
        for sources, targets, style in groups:
            rects = [self.cards[key][0].geometry() for key in sources]
            starts = [QPointF(rect.bottom(), rect.center().x()) if self.vertical else
                      QPointF(rect.right(), rect.center().y()) for rect in rects]
            rects = [self.cards[key][0].geometry() for key in targets]
            ends = [QPointF(rect.top() - 4, rect.center().x()) if self.vertical else
                    QPointF(rect.left() - 4, rect.center().y()) for rect in rects]
            pen.setStyle(Qt.PenStyle.DotLine if style == 'completion' else
                         Qt.PenStyle.DashLine if style == 'blocked' else Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            long_edge = self.positions[targets[0]][0] > self.positions[sources[0]][0] + 1
            # Reserve distinct bottom routes so unrelated long links never merge.
            gutter = (self.width() if self.vertical else self.height()) - 6 - long_lane * 10
            if long_edge:
                long_lane += 1
            path, arrows, junctions = connection_path(starts, ends, long_edge=long_edge, gutter=gutter)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.setBrush(pen.color())
            for arrow in arrows:
                painter.drawPolygon(arrow)
            for point in junctions:
                painter.drawEllipse(point, 2, 2)


def connection_path(starts, ends, *, long_edge=False, gutter=0):
    """One shared rail replaces crossing curves for a complete prerequisite set."""
    if len(starts) == len(ends) == 1:
        path, arrow = dependency_path(starts[0], ends[0], long_edge=long_edge, gutter=gutter)
        return path, [arrow], []
    path = QPainterPath()
    left, right = max(point.x() for point in starts), min(point.x() for point in ends)
    rail = left + 18 if long_edge else (left + right) / 2
    heights = [point.y() for point in starts] + ([gutter] if long_edge else [point.y() for point in ends])
    path.moveTo(rail, min(heights))
    path.lineTo(rail, max(heights))
    junctions = []
    for start in starts:
        path.moveTo(start)
        path.lineTo(rail, start.y())
        junctions.append(QPointF(rail, start.y()))
    if long_edge:
        approach = right - 24
        path.moveTo(rail, gutter)
        path.lineTo(approach, gutter)
        path.lineTo(approach, ends[0].y())
        path.lineTo(ends[0])
    else:
        for end in ends:
            path.moveTo(rail, end.y())
            path.lineTo(end)
            junctions.append(QPointF(rail, end.y()))
    arrows = [QPolygonF([end, end - QPointF(8, -4), end - QPointF(8, 4)]) for end in ends]
    return path, arrows, junctions


def dependency_path(start, end, *, long_edge=False, gutter=0):
    """Finish every connector horizontally through the centre of its arrowhead."""
    path = QPainterPath(start)
    approach = end - QPointF(16, 0)
    if long_edge:
        path.lineTo(start.x() + 18, start.y())
        path.lineTo(start.x() + 18, gutter)
        path.lineTo(approach.x() - 8, gutter)
        path.lineTo(approach.x() - 8, end.y())
        path.lineTo(approach)
    else:
        middle = (start.x() + approach.x()) / 2
        path.cubicTo(QPointF(middle, start.y()), QPointF(middle, end.y()), approach)
    path.lineTo(end)
    return path, QPolygonF([end, end - QPointF(8, -4), end - QPointF(8, 4)])


class FitMapView(QGraphicsView):
    scale_changed = Signal(float)
    minimum_scale = .05
    maximum_scale = 2.5

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.itemAt(event.position().toPoint()) is None:
            self.canvas.setFocus(Qt.FocusReason.MouseFocusReason)
            self.canvas.selected.emit('')
        super().mousePressEvent(event)

    def __init__(self, canvas):
        super().__init__()
        self.canvas, self.fit_mode = canvas, True
        self._fitted = None
        self.orientation = 'horizontal'
        self._fitting = False
        self.anchor = ''
        scene = QGraphicsScene(self); self.setScene(scene); self.proxy = scene.addWidget(canvas)
        self.setBackgroundBrush(canvas.palette().window())
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        canvas.focused.connect(self.reveal)

    def fit_map(self, force=False):
        if self._fitting:
            return
        self._fitting = True
        try:
            self._fit_map(force)
        finally:
            self._fitting = False

    def _fit_map(self, force=False):
        if self.fit_mode:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.canvas.adapt_to(self.viewport().size(), self.orientation)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if self.fit_mode:
            self.canvas.adjustSize()
        rect = self.proxy.boundingRect().adjusted(-4, -4, 4, 4)
        self.setSceneRect(rect)
        geometry = (rect, self.viewport().size())
        needs_fit = force or self._fitted is None or geometry != self._fitted
        if self.fit_mode and rect.width() and rect.height() and needs_fit:
            self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
            fitted = self.transform().m11()
            scale = min(1.35, fitted)
            self.resetTransform(); self.scale(scale, scale)
            self._fitted = (rect, self.viewport().size())
            self.scale_changed.emit(scale)
        elif self.fit_mode:
            self._fitted = geometry
        if self.fit_mode and getattr(self.canvas, 'compact', False):
            # Section backgrounds use the viewport's spare space. Cards keep
            # their measured size and sit centrally in their expanded cells.
            scale = self.transform().m11()
            self.canvas.resize(max(self.canvas.width(), int((self.viewport().width() - 16) / scale)),
                               max(self.canvas.height(), int((self.viewport().height() - 16) / scale)))
            self.canvas.grid.activate()
            self.setSceneRect(self.proxy.boundingRect().adjusted(-4, -4, 4, 4))

    def reveal(self, key):
        if key in self.canvas.cards:
            self.anchor = key
            rect = self.proxy.mapRectToScene(QRectF(self.canvas.cards[key][0].geometry()))
            # At a manual zoom a reserved activity area may be taller than the
            # viewport. Keyboard focus must still reveal the complete card.
            mapped = self.mapFromScene(rect).boundingRect()
            available = self.viewport().size()
            factor = min((available.width() - 48) / max(1, mapped.width()),
                         (available.height() - 48) / max(1, mapped.height()))
            if not self.fit_mode and factor < 1:
                scale = max(self.minimum_scale, self.transform().m11() * max(.01, factor))
                self.scale(scale / self.transform().m11(), scale / self.transform().m11())
                self.scale_changed.emit(scale)
            self.ensureVisible(rect, 24, 24)

    def reset_view(self):
        self.fit_mode, self._fitted, self.anchor = True, None, ''

    def zoom(self, amount):
        self.fit_mode = False
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        current = self.transform().m11()
        scale = max(self.minimum_scale, min(self.maximum_scale, current * amount))
        self.scale(scale / current, scale / current)
        self.scale_changed.emit(scale)

    def set_orientation(self, orientation):
        self.orientation = orientation
        self.fit_mode = True
        self.fit_map(force=True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_map()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange, QEvent.Type.StyleChange}:
            self.setBackgroundBrush(self.palette().window())


def orientation_picker(view):
    control = QComboBox()
    control.setAccessibleName('Workflow orientation')
    for label, key in (('Best fit', 'best'), ('Horizontal', 'horizontal'), ('Vertical', 'vertical')):
        control.addItem(label, key)
    control.setCurrentIndex(control.findData(view.orientation))
    control.currentIndexChanged.connect(lambda _: view.set_orientation(control.currentData()))
    return control


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
        for control in (self.orientation, self.fit_button, self.zoom_in, self.zoom_out):
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
                'Drag to pan; use + to zoom. Redundant success arrows are omitted; details list every prerequisite.' +
                ('' if self.graph_only else ' Stages returns to the readable step list.'))

        self.scroll.setToolTip(self.guidance.text() + '\nShared junctions mean every incoming prerequisite is required.\n' + self.legend.text())

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
