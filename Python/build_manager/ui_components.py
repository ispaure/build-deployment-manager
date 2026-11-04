"""Shared action hierarchy for the optional Qt presentation."""
from PySide6.QtCore import Qt, QSize, QEvent, Signal, QRect, QPoint, QObject, QTimer
from PySide6.QtGui import QKeySequence, QShortcut, QFont
from PySide6.QtWidgets import (QApplication, QComboBox, QDialogButtonBox, QPushButton,
    QSizePolicy, QWidget, QGridLayout, QStackedWidget, QLabel, QHBoxLayout,
    QVBoxLayout, QSplitter, QToolButton, QMenu, QWidgetAction, QFormLayout, QLayout, QSpacerItem,
    QLineEdit, QAbstractSpinBox)


class WrappingLayout(QLayout):
    """Native controls wrap at their useful size instead of widening the window."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.setSpacing(8)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item): self.items.append(item)
    def count(self): return len(self.items)
    def itemAt(self, index): return self.items[index] if 0 <= index < len(self.items) else None
    def takeAt(self, index): return self.items.pop(index) if 0 <= index < len(self.items) else None
    def addWidget(self, widget, stretch=0): super().addWidget(widget)
    def addStretch(self): self.addItem(QSpacerItem(0, 0, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
    def expandingDirections(self): return Qt.Orientation(0)
    def hasHeightForWidth(self): return True
    def heightForWidth(self, width): return self._layout(QRect(0, 0, width, 0), False)
    def sizeHint(self): return self.minimumSize()
    def minimumSize(self):
        size = QSize()
        for item in self.items:
            if not item.widget() or not item.widget().isHidden(): size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        return size + QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, True)
    def _layout(self, rect, apply):
        margins = self.contentsMargins()
        area = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        rows, row, used = [], [], 0
        for item in self.items:
            if item.widget() and item.widget().isHidden(): continue
            width = min(max(0, area.width()), item.sizeHint().width())
            if row and used + self.spacing() + width > area.width():
                rows.append(row); row, used = [], 0
            row.append((item, width)); used += width + (self.spacing() if len(row) > 1 else 0)
        if row: rows.append(row)
        y = area.y()
        for row in rows:
            spare = max(0, area.width() - sum(width for _, width in row) - self.spacing() * (len(row) - 1))
            stretches = sum(item.spacerItem() is not None for item, _ in row)
            x, height = area.x(), 0
            for item, width in row:
                if item.spacerItem() is not None and stretches: width += spare // stretches
                h = item.heightForWidth(width) if item.hasHeightForWidth() else item.sizeHint().height()
                h = max(0, h)
                if apply: item.setGeometry(QRect(QPoint(x, y), QSize(width, h)))
                x += width + self.spacing(); height = max(height, h)
            y += height + self.spacing()
        return y - rect.y() - (self.spacing() if rows else 0) + margins.bottom()


def map_view_options(orientation, follow=None):
    """Keep occasional display choices out of the map's reading surface."""
    button = QToolButton()
    button.setText('View')
    button.setAccessibleName('Workflow view options')
    menu = QMenu(button)
    content = QWidget()
    form = QFormLayout(content)
    form.addRow('Orientation', orientation)
    if follow is not None:
        form.addRow('Pointer behavior', follow)
    action = QWidgetAction(menu)
    action.setDefaultWidget(content)
    menu.addAction(action)
    button.setMenu(menu)
    button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    return button


def status_colors(widget, state):
    """Semantic surface, text and border; selection/focus remain native accent."""
    dark = widget.palette().window().color().lightness() < 128
    return ({
        'passed': ('#164b46', '#d0f5ed', '#58b8a8'),
        'failed': ('#542d22', '#ffe0d1', '#df8a64'),
        'running': ('#1d3c5a', '#d5e9ff', '#75ace0'),
        'awaiting_review': ('#4c3d20', '#ffebbb', '#c7a055'),
        'muted': ('#292d33', '#c2cad4', '#646b75'),
    } if dark else {
        'passed': ('#e6f5f0', '#12483e', '#398779'),
        'failed': ('#fbece5', '#672b18', '#ba6845'),
        'running': ('#eaf2fc', '#163e69', '#4d86bd'),
        'awaiting_review': ('#fff4dd', '#604500', '#b58a2e'),
        'muted': ('#eceef1', '#525960', '#a0a6ae'),
    }).get(state, ('palette(base)', 'palette(text)', 'palette(mid)'))


class HeadingLabel(QLabel):
    """A heading that follows application text size, including later changes."""
    def __init__(self, text='', parent=None, *, section=False):
        super().__init__(text, parent)
        self.scale = 1.0 if section else 1.35
        self.setWordWrap(True)
        install_font_refresh(QApplication.instance())
        self.refresh_font()

    def refresh_font(self):
        font = QFont(QApplication.font())
        font.setPointSizeF(max(1, font.pointSizeF()) * self.scale)
        font.setWeight(QFont.Weight.DemiBold)
        self.setFont(font)


class FontRefresh(QObject):
    """Reapply application text size through native dock/style font boundaries."""
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)
        app.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ApplicationFontChange:
            self.timer.start(0)
        elif event.type() == QEvent.Type.Polish:
            self.refresh_entry(watched)
        return False

    @staticmethod
    def refresh_entry(widget):
        if isinstance(widget, QLineEdit) and isinstance(widget.parentWidget(), (QComboBox, QAbstractSpinBox)):
            return  # The containing native control owns its editor geometry.
        if isinstance(widget, (QLineEdit, QComboBox, QAbstractSpinBox)):
            # Native Cocoa entry size hints can remain 21 px at 28 pt.
            # Keep the original minimum so resetting text size stays compact.
            if not hasattr(widget, '_manager_entry_minimum'):
                widget._manager_entry_minimum = widget.minimumHeight()
            minimum = max(widget._manager_entry_minimum, widget.fontMetrics().height() + 8)
            widget.setMinimumHeight(minimum)
            if widget.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Fixed:
                # Bound Qt's cached first-show combo minimum when fonts shrink.
                widget.setMaximumHeight(max(minimum, widget.sizeHint().height()))

    def refresh(self):
        size = self.app.font().pointSizeF()
        if size <= 0:
            return
        for widget in self.app.allWidgets():
            if isinstance(widget, HeadingLabel):
                widget.refresh_font()
            else:
                font = QFont(widget.font())
                if font.pointSizeF() != size:
                    font.setPointSizeF(size)
                    widget.setFont(font)
            self.refresh_entry(widget)


def install_font_refresh(app):
    if not hasattr(app, '_manager_font_refresh'):
        app._manager_font_refresh = FontRefresh(app)
    return app._manager_font_refresh


class AdaptiveSplitter(QSplitter):
    """Preserve manual sizes per orientation; stack when text needs more width."""
    def __init__(self, parent=None, *, sizes=(42, 58), minimums=(420, 330)):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.preferred_sizes = sizes
        self.minimums = minimums
        self.saved_sizes = {}
        self._reflowing = False
        self.setChildrenCollapsible(False)
        self.setHandleWidth(7)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.FontChange, QEvent.Type.StyleChange} and hasattr(self, '_reflowing'):
            self.reflow()

    def reflow(self):
        if self.count() != 2 or self._reflowing:
            return
        self._reflowing = True
        try:
            scale = max(1, self.fontMetrics().height() / 16)
            horizontal = self.width() >= sum(self.minimums) * scale + self.handleWidth()
            target = Qt.Orientation.Horizontal if horizontal else Qt.Orientation.Vertical
            if target != self.orientation():
                self.saved_sizes[self.orientation()] = self.sizes()
                for index in range(2):
                    self.widget(index).setMinimumWidth(self.minimums[index] if horizontal else 0)
                self.setOrientation(target)
                self.setSizes(self.saved_sizes.get(target, self.preferred_sizes))
            elif target not in self.saved_sizes:
                for index in range(2):
                    self.widget(index).setMinimumWidth(self.minimums[index] if horizontal else 0)
                self.setSizes(self.preferred_sizes)
                self.saved_sizes[target] = self.sizes()
        finally:
            self._reflowing = False


class EvidenceNavigator(QWidget):
    """One native evidence selector; pages never acquire nested tab bars."""
    currentChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        row = QHBoxLayout()
        label = QLabel('Evidence')
        self.selector = QComboBox()
        self.selector.setAccessibleName('Evidence view')
        self.selector.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.selector.setMinimumContentsLength(8)
        self.selector.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        label.setBuddy(self.selector)
        row.addWidget(label)
        row.addWidget(self.selector, 1)
        layout.addLayout(row)
        self.stack = ViewportStack()
        self.stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.stack, 1)
        self.entries = []
        self.selector.currentIndexChanged.connect(self._selected)
        self.stack.currentChanged.connect(lambda _: self.currentChanged.emit(self.currentIndex()))

    def _selected(self, index):
        if index >= 0:
            self.stack.setCurrentWidget(self.selector.itemData(index))

    def addTab(self, widget, label):
        index = (next((i for i, entry in enumerate(self.entries) if entry['label'].startswith('Technical · ')), len(self.entries))
                 if not label.startswith('Technical · ') else len(self.entries))
        self.entries.insert(index, dict(widget=widget, label=label, visible=True, enabled=True))
        self.stack.addWidget(widget)
        self._refresh()
        return index

    def _refresh(self):
        selected = self.stack.currentWidget()
        self.selector.blockSignals(True)
        self.selector.clear()
        for entry in self.entries:
            if entry['visible']:
                self.selector.addItem(entry['label'], entry['widget'])
                self.selector.model().item(self.selector.count() - 1).setEnabled(entry['enabled'])
        index = self.selector.findData(selected)
        if index < 0 or not self.selector.model().item(index).isEnabled():
            index = next((i for i in range(self.selector.count())
                          if self.selector.model().item(i).isEnabled()), -1)
        self.selector.setCurrentIndex(index)
        self.selector.blockSignals(False)
        self._selected(index)

    def count(self): return len(self.entries)
    def widget(self, index): return self.entries[index]['widget']
    def indexOf(self, widget): return next((i for i, e in enumerate(self.entries) if e['widget'] is widget), -1)
    def tabText(self, index): return self.entries[index]['label']
    def currentWidget(self): return self.stack.currentWidget()
    def currentIndex(self): return self.indexOf(self.currentWidget())
    def setCurrentIndex(self, index):
        if 0 <= index < self.count(): self.setCurrentWidget(self.widget(index))
    def setCurrentWidget(self, widget):
        if isinstance(widget, EvidenceGroup):
            widget.activate()
            return
        index = self.indexOf(widget)
        if index >= 0 and self.entries[index]['visible'] and self.entries[index]['enabled']:
            self.stack.setCurrentWidget(widget)
            self._refresh()
    def setTabVisible(self, index, visible):
        if index >= 0:
            self.entries[index]['visible'] = visible
            self._refresh()
    def isTabVisible(self, index): return index >= 0 and self.entries[index]['visible']
    def setTabEnabled(self, index, enabled):
        if index >= 0:
            self.entries[index]['enabled'] = enabled
            self._refresh()


class EvidenceGroup(QWidget):
    """Compatibility navigation for a logical group within one evidence selector."""
    def __init__(self, navigator, *, prefix=''):
        super().__init__(navigator)
        self.navigator, self.prefix, self.pages, self.labels, self.last = navigator, prefix, [], [], 0
        navigator.currentChanged.connect(self.remember_selection)
        self.hide()

    def remember_selection(self, _):
        index = self.indexOf(self.navigator.currentWidget())
        if index >= 0:
            self.last = index

    def addTab(self, widget, label):
        self.pages.append(widget)
        self.labels.append(label)
        self.navigator.addTab(widget, self.prefix + label)
        return len(self.pages) - 1
    def count(self): return len(self.pages)
    def indexOf(self, widget): return self.pages.index(widget) if widget in self.pages else -1
    def widget(self, index): return self.pages[index]
    def tabText(self, index): return self.labels[index]
    def currentWidget(self):
        current = self.navigator.currentWidget()
        return current if current in self.pages else self.pages[self.last] if self.pages else None
    def currentIndex(self): return self.indexOf(self.currentWidget())
    def setCurrentIndex(self, index):
        if 0 <= index < self.count():
            self.last = index
            self.navigator.setCurrentWidget(self.pages[index])
    def setCurrentWidget(self, widget): self.setCurrentIndex(self.indexOf(widget))
    def activate(self): self.setCurrentIndex(self.last)
    def setTabVisible(self, index, visible):
        if index >= 0: self.navigator.setTabVisible(self.navigator.indexOf(self.pages[index]), visible)
    def isTabVisible(self, index): return index >= 0 and self.navigator.isTabVisible(self.navigator.indexOf(self.pages[index]))


class ViewportStack(QStackedWidget):
    """Bound stage content to its viewport, independent of hidden-page text."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(self.updateGeometry)

    def minimumSizeHint(self):
        page = self.currentWidget()
        if page is None:
            return QSize(0, 0)
        hint = page.minimumSizeHint().expandedTo(page.minimumSize())
        margins = self.contentsMargins()
        return QSize(max(0, hint.width()) + margins.left() + margins.right(), 0)

    def hasHeightForWidth(self):
        return False

    def heightForWidth(self, width):
        return -1


class CurrentPageStack(QStackedWidget):
    """Size a docked action area from its visible page, including native minima."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentChanged.connect(self.updateGeometry)

    def _page_hint(self, minimum):
        page = self.currentWidget()
        if page is None:
            return QSize(0, 0)
        hint = page.minimumSizeHint() if minimum else page.sizeHint()
        hint = hint.expandedTo(page.minimumSize()).expandedTo(QSize(0, 0))
        margins = self.contentsMargins()
        return hint + QSize(margins.left() + margins.right(),
                            margins.top() + margins.bottom())

    def minimumSizeHint(self):
        return self._page_hint(True)

    def sizeHint(self):
        return self._page_hint(False)

    def hasHeightForWidth(self):
        return bool(self.currentWidget() and self.currentWidget().hasHeightForWidth())

    def heightForWidth(self, width):
        return self.currentWidget().heightForWidth(width) if self.hasHeightForWidth() else self.sizeHint().height()


class SelectionSummary(QPushButton):
    """Compact navigation that retains full choice names for assistive tools."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.full_text = ''
        self.setAutoDefault(False)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setStyleSheet('''QPushButton { padding: 6px 10px; min-height: 20px;
            border: 1px solid palette(mid); border-radius: 6px; background: palette(alternate-base); }
            QPushButton:hover, QPushButton:focus { border: 1px solid palette(highlight); }
            QPushButton:checked { border: 2px solid palette(highlight); padding: 5px 9px; font-weight: 600; }
            QPushButton:disabled { color: palette(mid); }''')

    def set_summary(self, text):
        self.full_text = text
        self.setAccessibleName(text)
        self.setToolTip(text)
        self.elide()

    def elide(self):
        self.setText(self.fontMetrics().elidedText(self.full_text, Qt.TextElideMode.ElideRight,
            max(20, self.width() - (46 if not self.icon().isNull() else 24))))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.elide()


class ActionStrip(QWidget):
    """Let compact attention actions wrap instead of widening a small window."""
    def __init__(self, parent=None, *, compact=False):
        super().__init__(parent)
        self.compact = compact
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.buttons, self.columns = [], 0

    def set_buttons(self, buttons):
        for button in self.buttons:
            self.grid.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.buttons, self.columns = buttons, 0
        self.reflow()
        self.setVisible(bool(buttons))

    def reflow(self):
        columns = max(1, min(4, self.width() // max(220, self.fontMetrics().horizontalAdvance('Choose committed source…') + 50)))
        if self.compact:
            width = max((self.fontMetrics().horizontalAdvance(button.full_text) +
                         (48 if not button.icon().isNull() else 26) for button in self.buttons), default=100)
            columns = 4 if self.width() >= width * 4 + self.grid.horizontalSpacing() * 3 else 2
        if columns == self.columns:
            return
        for button in self.buttons:
            self.grid.removeWidget(button)
        for column in range(self.grid.columnCount()):
            self.grid.setColumnStretch(column, 0)
        for index, button in enumerate(self.buttons):
            self.grid.addWidget(button, index // columns, index % columns)
            button.show()
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)
        self.columns = columns

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()


def style_button(button, role='secondary'):
    """Emphasize an action without changing keyboard defaults or authorization."""
    button.setAutoDefault(False)
    if button.property('actionRole') == role:
        return button
    button.setProperty('actionRole', role)
    base = 'QPushButton { min-height: 20px; padding: 6px 12px; border-radius: 6px;'
    if role == 'primary':
        button.setStyleSheet(base + '''
            background: palette(highlight); color: palette(highlighted-text); border: 2px solid palette(highlight); font-weight: 600; }
            QPushButton:hover { border-color: palette(text); }
            QPushButton:pressed { border-color: palette(highlighted-text); }
            QPushButton:focus { border: 2px dashed palette(highlighted-text); }
            QPushButton:disabled { background: palette(midlight); color: palette(mid);
                border-color: palette(midlight); }
        ''')
    else:
        button.setStyleSheet(base + '''
            background: palette(button); color: palette(button-text); border: 1px solid palette(mid); }
            QPushButton:hover { border-color: palette(highlight); }
            QPushButton:focus { border: 2px solid palette(highlight); padding: 5px 11px; }
            QPushButton:disabled { color: palette(mid); }
        ''')
    return button


def style_tabs(tabs):
    """Use the application theme's tabs, or native Qt tabs without a theme."""
    tabs.setDocumentMode(False)
    tabs.setStyleSheet('')


def search_shortcut(parent, field):
    """Use the platform's Find key only inside the owning panel or dialog."""
    shortcut = QShortcut(QKeySequence.StandardKey.Find, parent)
    shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    shortcut.activated.connect(field.setFocus)
    shortcut.activated.connect(field.selectAll)
    return shortcut


def style_dialog_buttons(buttons):
    for button in buttons.buttons():
        role = buttons.buttonRole(button)
        style_button(button, 'primary' if role in (
            QDialogButtonBox.ButtonRole.AcceptRole,
            QDialogButtonBox.ButtonRole.ApplyRole,
            QDialogButtonBox.ButtonRole.YesRole,
        ) else 'secondary')


def style_utilities(dialog):
    """Utility buttons must not become a native dialog's implicit Return action."""
    for button in dialog.findChildren(QPushButton):
        if button.property('actionRole') is None:
            style_button(button)
