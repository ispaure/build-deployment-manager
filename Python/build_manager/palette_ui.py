"""Refresh manager-local palette styles together after a native theme change."""
from PySide6.QtCore import QObject, QEvent, QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QWidget


class PaletteRefresh(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app, self.refreshing, self.frozen = app, False, []
        self.palette = QPalette(app.palette())
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.refresh)
        app.installEventFilter(self)
        app.styleHints().colorSchemeChanged.connect(lambda _: self.schedule(force=True))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ApplicationPaletteChange:
            self.schedule()
        elif event.type() == QEvent.Type.ThemeChange:
            self.schedule(force=True)
        return False

    def schedule(self, force=False):
        if self.refreshing or self.timer.isActive() or (not force and self.palette == self.app.palette()):
            return
        self.frozen = [window for window in self.app.topLevelWidgets()
                       if window.isVisible() and window.updatesEnabled()]
        for window in self.frozen:
            window.setUpdatesEnabled(False)
        self.timer.start(0)

    def refresh(self):
        self.refreshing = True
        try:
            # Native controls follow Qt's palette themselves. Locally styled
            # manager controls need their cached palette() brushes invalidated.
            for widget in self.app.allWidgets():
                if widget.styleSheet():
                    sheet = widget.styleSheet()
                    widget.setStyleSheet('')
                    widget.setStyleSheet(sheet)
                    QWidget.update(widget)
            self.palette = QPalette(self.app.palette())
        finally:
            for window in self.frozen:
                try:
                    window.setUpdatesEnabled(True)
                    QWidget.update(window)
                except RuntimeError:  # A window may close during a queued update.
                    pass
            self.frozen = []
            self.refreshing = False


def install_palette_refresh(app):
    controller = getattr(app, '_manager_palette_refresh', None)
    if controller is None:
        controller = PaletteRefresh(app)
        app._manager_palette_refresh = controller
    return controller
