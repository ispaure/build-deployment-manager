"""Shared action hierarchy for the optional Qt presentation."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDialogButtonBox, QPushButton, QSizePolicy, QWidget, QGridLayout, QStackedWidget


class ViewportStack(QStackedWidget):
    """Bound stage content to its viewport, independent of hidden-page text."""
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
            QPushButton:checked { border: 2px solid #245db5; padding: 5px 9px; font-weight: 600; }
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
    def __init__(self, parent=None):
        super().__init__(parent)
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
            background: #245db5; color: white; border: 2px solid #245db5; font-weight: 600; }
            QPushButton:hover { background: #194c9b; border-color: #194c9b; }
            QPushButton:pressed { background: #123c80; }
            QPushButton:focus { border: 2px dashed white; }
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
