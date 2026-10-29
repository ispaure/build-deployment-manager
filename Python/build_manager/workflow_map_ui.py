"""Map viewport interaction, fitting and saved view preferences."""
from PySide6.QtCore import Qt, Signal, QRectF, QEvent
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtWidgets import QLabel, QPushButton, QGraphicsScene, QGraphicsView, QWidget, QComboBox, QToolTip
from .profiles import load_profile, save_profile
from .registry import config_directory
from .workflow_cards_ui import section_tint


class FitMapView(QGraphicsView):
    scale_changed = Signal(float)
    minimum_scale = .05
    maximum_scale = 2.5

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        # Resolve the whole card after scene dispatch and pointer-follow have
        # run. Child widgets and proxy enter/leave ordering must not clear it.
        if not event.buttons():
            point = self.proxy.mapFromScene(self.mapToScene(event.position().toPoint()))
            key = next((key for key, (card, _, _) in self.canvas.cards.items()
                        if not card.isHidden() and QRectF(card.geometry()).contains(point)), '')
            if key != self.canvas.hover_key:
                if key:
                    self.canvas.trace_card(key, True)
                elif self.canvas.hover_key:
                    self.canvas.trace_card(self.canvas.hover_key, False)

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
        self.pointer_follow = False
        self._pointer_state = None
        self._pointer_pressed = False
        self.sticky_sections = QWidget(self)
        self.sticky_sections.setObjectName('workflowStickySections')
        self.sticky_sections.setAccessibleName('Workflow sections')
        self.sticky_sections.setAutoFillBackground(False)
        self.sticky_labels = []
        self.sticky_sections.hide()
        scene = QGraphicsScene(self); self.setScene(scene); self.proxy = scene.addWidget(canvas)
        self.setBackgroundBrush(canvas.palette().window())
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setBackgroundRole(QPalette.ColorRole.Window)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.viewport().installEventFilter(self)
        canvas.focused.connect(self.reveal)
        canvas.sections_changed.connect(self._update_sticky_sections)
        self.scale_changed.connect(lambda _: self._layout_sticky_sections())
        self._update_sticky_sections()

    def _update_sticky_sections(self):
        for widget in self.sticky_labels:
            widget.hide()
            widget.deleteLater()
        self.sticky_labels = []
        headings = [header.text() for header in self.canvas.headers]
        visible = bool(headings) and getattr(self.canvas, 'compact', False)
        for header in self.canvas.headers:
            # Keep the band's layout geometry while its title lives solely in
            # the sticky strip. Hiding must not collapse or shift the sections.
            policy = header.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            header.setSizePolicy(policy)
            header.setVisible(not visible)
        if visible:
            for heading in headings:
                label = QLabel(heading, self.sticky_sections)
                label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.sticky_labels.append(label)
        self._style_sticky_sections()
        self.sticky_sections.setVisible(visible)
        self._layout_sticky_sections()

    def _style_sticky_sections(self):
        for label in self.sticky_labels:
            color = section_tint(label.text(), self.canvas.palette())
            label.setStyleSheet('font-weight: 600; padding: 5px 8px; '
                                f'background: rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()});')

    def _layout_sticky_sections(self):
        vertical = self.canvas.vertical
        height = width = 0
        if not self.sticky_sections.isHidden():
            if vertical:
                width = max((label.sizeHint().width() for label in self.sticky_labels), default=0)
            else:
                height = max((label.sizeHint().height() for label in self.sticky_labels), default=0)
        if (self.viewportMargins().left(), self.viewportMargins().top()) != (width, height):
            self.setViewportMargins(width, height, 0, 0)
        if vertical:
            self.sticky_sections.setGeometry(0, self.viewport().y(), width, self.viewport().height())
        else:
            self.sticky_sections.setGeometry(self.viewport().x(), 0, self.viewport().width(), height)
        for header, label in zip(self.canvas.headers, self.sticky_labels):
            band = self.mapFromScene(self.proxy.mapRectToScene(
                QRectF(self.canvas.section_rect(header)))).boundingRect()
            rect = (QRectF(0, band.top(), width, band.height()) if vertical else
                    QRectF(band.left(), 0, band.width(), height))
            # Clip both the tint and the text to the visible part of its band.
            # A section that has panned entirely off screen has no sticky label.
            rect = rect.intersected(QRectF(self.sticky_sections.rect()))
            label.setVisible(not rect.isEmpty())
            label.setGeometry(rect.toAlignedRect())

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        if hasattr(self, 'sticky_sections'):
            self._layout_sticky_sections()

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if self.sticky_sections.isHidden():
            return
        # Fitting can leave spare space above (or left of) the canvas. Continue
        # each band through that space all the way to its sticky heading.
        visible = self.mapToScene(self.viewport().rect()).boundingRect()
        for header in self.canvas.headers:
            band = self.proxy.mapRectToScene(QRectF(self.canvas.section_rect(header)))
            extension = (QRectF(visible.left(), band.top(), max(0., band.left() - visible.left()), band.height())
                         if self.canvas.vertical else
                         QRectF(band.left(), visible.top(), band.width(), max(0., band.top() - visible.top())))
            painter.fillRect(extension, section_tint(header.text(), self.canvas.palette()))

    def set_pointer_follow(self, enabled):
        self.pointer_follow = enabled
        if not enabled:
            self._end_pointer_follow()

    def eventFilter(self, watched, event):
        if watched is self.viewport():
            if event.type() == QEvent.Type.ToolTip:
                QToolTip.hideText()
                return True
            if event.type() == QEvent.Type.MouseMove and not event.buttons():
                self._follow_pointer(event.position())
            elif event.type() == QEvent.Type.MouseButtonPress:
                self._pointer_pressed = True
            elif event.type() == QEvent.Type.KeyPress:
                self._pointer_pressed = False
                self._end_pointer_follow()
            elif event.type() == QEvent.Type.Leave:
                self._pointer_pressed = False
                self._end_pointer_follow()
                if self.canvas.hover_key:
                    self.canvas.trace_card(self.canvas.hover_key, False)
        return super().eventFilter(watched, event)

    def mouseReleaseEvent(self, event):
        try:
            super().mouseReleaseEvent(event)
        finally:
            self._pointer_pressed = False

    def _follow_pointer(self, position):
        if not self.pointer_follow or not self.fit_mode:
            return
        if self._pointer_state is None:
            current = self.transform().m11()
            if current >= 1:
                return
            self._pointer_state = (self.transform(), self.horizontalScrollBar().value(),
                                   self.verticalScrollBar().value())
            self.scale(1 / current, 1 / current)
            self.scale_changed.emit(1.)
        # Reach each edge in the outer fifth of the viewport so exploring a
        # corner does not require aiming at the physical edge of the map.
        for bar, coordinate, extent in (
                (self.horizontalScrollBar(), position.x(), self.viewport().width()),
                (self.verticalScrollBar(), position.y(), self.viewport().height())):
            margin = extent * .20
            fraction = max(0., min(1., (coordinate - margin) / max(1, extent - 2 * margin)))
            bar.setValue(round(bar.minimum() + fraction * (bar.maximum() - bar.minimum())))

    def _end_pointer_follow(self):
        if self._pointer_state is None:
            return
        transform, horizontal, vertical = self._pointer_state
        self._pointer_state = None
        self.setTransform(transform)
        self.horizontalScrollBar().setValue(horizontal)
        self.verticalScrollBar().setValue(vertical)
        self.scale_changed.emit(transform.m11())

    def fit_map(self, force=False):
        if self._fitting or self._pointer_state is not None:
            return
        self._fitting = True
        try:
            self._fit_map(force)
        finally:
            self._fitting = False
            self._layout_sticky_sections()

    def _fit_map(self, force=False):
        if self.fit_mode:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.canvas.adapt_to(self.viewport().size(), self.orientation)
            self._layout_sticky_sections()
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
        if self._pointer_state is not None and self._pointer_pressed:
            return
        self._end_pointer_follow()
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
        self._end_pointer_follow()
        self.fit_mode, self._fitted, self.anchor = True, None, ''

    def zoom(self, amount):
        self._end_pointer_follow()
        self.fit_mode = False
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        current = self.transform().m11()
        scale = max(self.minimum_scale, min(self.maximum_scale, current * amount))
        self.scale(scale / current, scale / current)
        self.scale_changed.emit(scale)

    def set_orientation(self, orientation):
        self._end_pointer_follow()
        self.orientation = orientation
        self.fit_mode = True
        self.fit_map(force=True)

    def resizeEvent(self, event):
        self._end_pointer_follow()
        super().resizeEvent(event)
        self._layout_sticky_sections()
        self.fit_map()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in {QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange, QEvent.Type.StyleChange}:
            self.setBackgroundBrush(self.palette().window())
            self._style_sticky_sections()


def orientation_picker(view):
    control = QComboBox()
    control.setAccessibleName('Workflow orientation')
    for label, key in (('Best fit', 'best'), ('Horizontal', 'horizontal'), ('Vertical', 'vertical')):
        control.addItem(label, key)
    control.setCurrentIndex(control.findData(view.orientation))
    control.currentIndexChanged.connect(lambda _: view.set_orientation(control.currentData()))
    return control


def pointer_follow_picker(view):
    control = QPushButton('Follow mouse')
    control.setCheckable(True)
    control.setToolTip('Enlarge fitted maps while the pointer moves inside. Move toward an edge to see that corner; leave to restore the overview.')
    path = config_directory() / 'workflow-view.json'
    try:
        values = load_profile(path)
        enabled = values.get('follow_mouse', False) is True
    except (OSError, ValueError):
        enabled = False
    control.setChecked(enabled)
    view.set_pointer_follow(enabled)
    control.toggled.connect(view.set_pointer_follow)

    def remember(enabled):
        try:
            values = load_profile(path)
            values['follow_mouse'] = enabled
            save_profile(path, values, allowed=set(values))
        except (OSError, ValueError) as error:
            control.setToolTip('Could not save Follow mouse preference: ' + str(error))

    control.toggled.connect(remember)
    return control

