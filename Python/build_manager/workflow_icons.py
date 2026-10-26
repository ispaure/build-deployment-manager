"""Bundled, palette-aware platform and service badges for workflow cards."""
from functools import lru_cache
from importlib.resources import files
import re

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget


PLATFORMS = {'windows': 'windows', 'win32': 'windows', 'linux': 'linux',
             'macos': 'apple', 'darwin': 'apple', 'ios': 'apple', 'android': 'android'}
NAMES = {'windows': 'Windows', 'linux': 'Linux', 'apple': 'Apple',
         'android': 'Android', 'github': 'GitHub', 'docker': 'Docker'}


def backend_icons(backend):
    # Backend names are display strings; match whole words, never arbitrary substrings.
    words = set(re.findall(r'[a-z0-9]+', backend.lower()))
    return [icon for word, icon in {**PLATFORMS, 'github': 'github', 'docker': 'docker'}.items()
            if word in words]


def step_icons(phase, plan):
    """Use declared targets and execution locations, never commands or dependencies."""
    platforms = list(getattr(phase, 'platforms', ()))
    backends = [getattr(phase, 'backend', '')]
    services = []
    if getattr(phase, 'provider', '') == 'github' or getattr(phase, 'target', '') == 'github':
        services.append('github')
    journey = getattr(plan, 'journey', {})
    for target, steps in journey.get('platforms', {}).items():
        execution = journey.get('executions', {}).get(target, {})
        if phase.id in steps or phase.id in execution.get('steps', []):
            platforms.append(target)
            backends.append(execution.get('backend', ''))
    for destination, row in journey.get('destinations', {}).items():
        if phase.id in row['steps']:
            platforms.extend(row.get('platforms', journey['platforms']))
            if destination == 'github':
                services.append('github')
    if not journey:
        backends.append(getattr(plan, 'backend', ''))
    icons = [PLATFORMS[target.lower()] for target in platforms if target.lower() in PLATFORMS]
    icons.extend(icon for backend in backends for icon in backend_icons(backend))
    return tuple(dict.fromkeys((*icons, *services)))


@lru_cache(maxsize=6)
def svg_data(name):
    return files('build_manager').joinpath('assets', 'icons', name + '.svg').read_bytes()


class WorkflowIcons(QWidget):
    """Keep icons decorative; the card exposes their meaning to assistive tools."""
    def __init__(self, icons, parent=None):
        super().__init__(parent)
        self.icons = icons
        self.renderers = [QSvgRenderer(svg_data(name), self) for name in icons]
        self.setFixedSize(22 * len(icons) - 4, 18)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event):
        painter = QPainter(self)
        color = self.palette().text().color()
        if self.parentWidget().property('state') in {'blocked', 'skipped'}:
            color.setAlphaF(.45)
        ratio = self.devicePixelRatioF()
        for index, renderer in enumerate(self.renderers):
            pixmap = QPixmap(round(18 * ratio), round(18 * ratio))
            pixmap.setDevicePixelRatio(ratio)
            pixmap.fill(Qt.GlobalColor.transparent)
            ink = QPainter(pixmap)
            bounds = renderer.viewBoxF()
            width = 18 * bounds.width() / max(bounds.width(), bounds.height())
            height = 18 * bounds.height() / max(bounds.width(), bounds.height())
            renderer.render(ink, QRectF((18 - width) / 2, (18 - height) / 2, width, height))
            ink.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            ink.fillRect(QRectF(0, 0, 18, 18), color)
            ink.end()
            painter.drawPixmap(index * 22, 0, pixmap)
