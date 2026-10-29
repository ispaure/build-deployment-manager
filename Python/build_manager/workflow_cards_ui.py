"""Workflow cards, dependency paths and canvas rendering."""
from PySide6.QtCore import Qt, QPointF, Signal, QRectF, QEvent
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF, QTransform, QTextLayout, QTextOption
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget, QProgressBar, QToolTip
from .workflow_icons import NAMES, WorkflowIcons, step_icons
from .workflow_graph import layout_positions, visible_dependencies, connection_groups
from .workflow_presentation import FAILED, title, effect_label, display_states, state_label, step_time
from .test_tree_ui import current_test_seconds

SECTION_COLORS = {'Source': '#7296ca', 'Testing': '#71ab8b',
                  'Delivery': '#d6aa64', 'Build / package': '#aa8ac4'}


def section_tint(heading, palette):
    color = QColor(SECTION_COLORS.get(heading, '#8998ac'))
    color.setAlpha(30 if palette.window().color().lightness() >= 128 else 42)
    return color


def connection_color(palette, *, muted=False):
    dark = palette.window().color().lightness() < 128
    if muted:
        return QColor('#777777' if dark else '#999999')
    return QColor(Qt.GlobalColor.white) if dark else palette.text().color()


class FlowCard(QPushButton):
    focused = Signal()
    hovered = Signal(bool)
    keyboard_trace = Signal(bool)

    def event(self, event):
        # Floating help windows can steal hover from a graphics proxy. Card
        # details remain available through selection and accessibility text.
        if event.type() == QEvent.Type.ToolTip:
            QToolTip.hideText()
            return True
        return super().event(event)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.hovered.emit(True)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.hovered.emit(False)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focused.emit()
        if event.reason() in {Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
                              Qt.FocusReason.ShortcutFocusReason}:
            self.keyboard_trace.emit(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.keyboard_trace.emit(False)

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


class FlowCanvas(QWidget):
    selected = Signal(str)
    card_action_requested = Signal(str)
    focused = Signal(str)
    sections_changed = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.selected.emit('')
        super().mousePressEvent(event)

    def __init__(self):
        super().__init__()
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setToolTip('Hover a card to trace its prerequisites and downstream steps. '
                        'Other cards and lines stay visible in gray. Move away to restore the full map. '
                        'Tab focus also traces the flow; selection stays unchanged.')
        self.cards, self.edges, self.states = {}, [], {}
        self.headers, self.order_edges, self.positions = [], set(), {}
        self.completion_targets = set()
        self.hover_key = self.keyboard_key = ''
        self.trace_keys = set()
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

    def set_card_actions(self, actions):
        """Attach explicit caller-owned actions without changing card navigation."""
        changed = False
        for key, (card, _, _) in self.cards.items():
            button = card.findChild(QPushButton, 'cardAction')
            action = actions.get(key)
            if button is None and action:
                button = QPushButton(card)
                button.setObjectName('cardAction')
                button.clicked.connect(lambda checked=False, control=button:
                    self.card_action_requested.emit(control.property('actionKey')))
                card.layout().addWidget(button)
            if button is not None:
                visible = bool(action)
                changed |= button.isHidden() == visible
                button.setVisible(visible)
                if action:
                    label, target = action
                    button.setText(label)
                    button.setProperty('actionKey', target)
                    button.setAccessibleName(label + ': ' + target)
                    button.setToolTip('Retry the same prepared app on this device. The earlier installation may have completed; its result is preserved.')
        if changed:
            self.adjustSize()
            self.updateGeometry()

    def style_card(self, card, status):
        dark = self.palette().window().color().lightness() < 128
        kind = ('passed' if status in {'passed', 'captured'} else
                'failed' if status in FAILED - {'skipped'} else
                'muted' if status in {'blocked', 'skipped'} else
                'awaiting_review' if status == 'needs_selection' else status)
        # Teal-green and orange-red separate along the blue/yellow axis too,
        # making outcomes easier to distinguish with deuteranopia.
        colors = ({
            'passed': ('#164b46', '#d0f5ed', '#58b8a8'),
            'failed': ('#542d22', '#ffe0d1', '#df8a64'),
            'running': ('#1d3c5a', '#d5e9ff', '#75ace0'),
            'awaiting_review': ('#4c3d20', '#ffebbb', '#c7a055'),
            'muted': ('#292d33', '#a5acb6', '#646b75'),
        } if dark else {
            'passed': ('#d4f2eb', '#12483e', '#398779'),
            'failed': ('#f8dfd0', '#672b18', '#ba6845'),
            'running': ('#deecfb', '#163e69', '#4d86bd'),
            'awaiting_review': ('#fff0cf', '#604500', '#b58a2e'),
            'muted': ('#eceef1', '#626262', '#a0a6ae'),
        }).get(kind)
        background, text, border = colors or ('palette(base)', 'palette(text)', 'palette(mid)')
        muted = bool(card.property('traceMuted'))
        if muted:
            background, text, border = (('#343434', '#aaaaaa', '#777777') if dark else
                                        ('#e4e4e4', '#777777', '#999999'))
        stylesheet = f'''
            QPushButton#workflowCard {{ background: {background}; color: {text};
                border: 2px solid {border}; border-radius: 8px; text-align: left; }}
            QPushButton#workflowCard:hover, QPushButton#workflowCard:checked,
            QPushButton#workflowCard:focus {{ border: 2px solid palette(highlight); }}
            QPushButton#workflowCard QLabel {{ color: {text}; background: transparent; }}
        '''
        if muted:
            stylesheet += f'QProgressBar::chunk {{ background: {border}; }}'
        if card.styleSheet() != stylesheet:
            card.setStyleSheet(stylesheet)
        for child in card.findChildren(QLabel):
            if child.objectName() == 'approvalBadge':
                child.setStyleSheet('border: 1px solid ' + (border if muted else '#b37c12') +
                                   '; border-radius: 4px; padding: 2px 5px;')
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
        self.hover_key = self.keyboard_key = ''
        self.trace_keys = set()
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
        by_id = {phase.id: phase for phase in plan.phases}
        self.trace_parents = {phase.id: (*phase.dependencies, *getattr(phase, 'waits_for', ()))
                              for phase in plan.phases}
        self.trace_children = {}
        for child, parents in self.trace_parents.items():
            for parent in parents:
                self.trace_children.setdefault(parent, []).append(child)
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
            card.hovered.connect(lambda active, key=phase.id: self.trace_card(key, active))
            card.keyboard_trace.connect(lambda active, key=phase.id: self.trace_card(key, active, keyboard=True))
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
            if getattr(plan, 'proposed', False) and phase.dependencies:
                prerequisites = QLabel('Requires: ' + ', '.join(
                    title(by_id[key]) for key in phase.dependencies if key in by_id))
                prerequisites.setObjectName('workflowPrerequisites')
                prerequisites.setWordWrap(True)
                prerequisites.setTextFormat(Qt.TextFormat.PlainText)
                prerequisites.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                body.addWidget(prerequisites)
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
            if compact:
                card.setMinimumHeight(max(self.base_card_height, body.totalHeightForWidth(width)))
        self.arrange(self.vertical)
        self.adjustSize()
        self.updateGeometry()
        self.update()
        self.sections_changed.emit()

    def trace_card(self, key, active, *, keyboard=False):
        attribute = 'keyboard_key' if keyboard else 'hover_key'
        if active:
            setattr(self, attribute, key)
        elif getattr(self, attribute) == key:
            setattr(self, attribute, '')
        root = self.hover_key or self.keyboard_key
        traced = set()
        # Traverse each direction from the hovered node separately. Walking
        # back down from its ancestors would incorrectly include sibling branches.
        for links in (self.trace_parents, self.trace_children):
            pending = [root] if root else []
            seen = set()
            while pending:
                current = pending.pop()
                if current not in seen:
                    seen.add(current)
                    pending.extend(links.get(current, ()))
            traced.update(seen)
        self.trace_keys = traced
        for card_key, (card, _, _) in self.cards.items():
            dim = bool(traced) and card_key not in traced
            card.setProperty('traceMuted', dim)
            self.style_card(card, card.property('state') or '')
            for icons in card.findChildren(WorkflowIcons):
                icons.update()
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

    def section_rect(self, header):
        rect = header.geometry().adjusted(-4, -16, 0, 16) if self.vertical else header.geometry().adjusted(-16, -4, 16, 0)
        if self.vertical:
            rect.setRight(self.width() - 2)
            if header.isHidden():
                rect.setLeft(0)
        else:
            rect.setBottom(self.height() - 2)
            if header.isHidden():
                rect.setTop(0)
        return rect.intersected(self.rect())

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Sticky headings and tinted bands share exactly the same bounds.
        for header in self.headers:
            rect = self.section_rect(header)
            painter.fillRect(rect, section_tint(header.text(), self.palette()))
        connector_color = connection_color(self.palette())
        pen = QPen(connector_color, 1.7)
        groups = connection_groups(self.edges, self.positions, self.order_edges,
                                   self.states, self.completion_targets)
        # Different prerequisite sets must never share a vertical rail merely
        # because they occupy the same gap between columns.
        gaps = [(self.positions[sources[0]][0], self.positions[targets[0]][0])
                for sources, targets, _ in groups]
        lane_counts = {gap: gaps.count(gap) for gap in set(gaps)}
        lanes = {}
        long_lane = 0
        if self.vertical:
            painter.setTransform(QTransform(0, 1, 1, 0, 0, 0))
        for (sources, targets, style), gap in zip(groups, gaps):
            lanes[gap] = lanes.get(gap, 0) + 1
            rail_fraction = lanes[gap] / (lane_counts[gap] + 1)
            rects = [self.cards[key][0].geometry() for key in sources]
            starts = [QPointF(rect.bottom(), rect.center().x()) if self.vertical else
                      QPointF(rect.right(), rect.center().y()) for rect in rects]
            rects = [self.cards[key][0].geometry() for key in targets]
            ends = [QPointF(rect.top() - 4, rect.center().x()) if self.vertical else
                    QPointF(rect.left() - 4, rect.center().y()) for rect in rects]
            pen.setStyle(Qt.PenStyle.DotLine if style == 'completion' else
                         Qt.PenStyle.DashLine if style == 'blocked' else Qt.PenStyle.SolidLine)
            pen.setColor(connection_color(self.palette(), muted=bool(self.trace_keys)))
            painter.setPen(pen)
            long_edge = self.positions[targets[0]][0] > self.positions[sources[0]][0] + 1
            # Reserve distinct bottom routes so unrelated long links never merge.
            gutter = (self.width() if self.vertical else self.height()) - 6 - long_lane * 10
            if long_edge:
                long_lane += 1
            path, arrows, junctions = connection_path(starts, ends, long_edge=long_edge,
                gutter=gutter, rail_fraction=rail_fraction)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            painter.setBrush(pen.color())
            for arrow in arrows:
                painter.drawPolygon(arrow)
            for point in junctions:
                painter.drawEllipse(point, 2, 2)
            if self.trace_keys:
                traced_starts = [point for key, point in zip(sources, starts) if key in self.trace_keys]
                traced_ends = [point for key, point in zip(targets, ends) if key in self.trace_keys]
                if traced_starts and traced_ends:
                    path, arrows, junctions = connection_path(traced_starts, traced_ends,
                        long_edge=long_edge, gutter=gutter, rail_fraction=rail_fraction)
                    pen.setColor(connector_color)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(path)
                    painter.setBrush(pen.color())
                    for arrow in arrows:
                        painter.drawPolygon(arrow)
                    for point in junctions:
                        painter.drawEllipse(point, 2, 2)


def connection_path(starts, ends, *, long_edge=False, gutter=0, rail_fraction=None):
    """One shared rail replaces crossing curves for a complete prerequisite set."""
    if len(starts) == len(ends) == 1 and rail_fraction is None:
        path, arrow = dependency_path(starts[0], ends[0], long_edge=long_edge, gutter=gutter)
        return path, [arrow], []
    path = QPainterPath()
    left, right = max(point.x() for point in starts), min(point.x() for point in ends)
    fraction = .5 if rail_fraction is None else rail_fraction
    rail = left + 10 + 16 * fraction if long_edge else left + (right - left) * fraction
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

