"""Stable file/case tree synchronization and measured timing cells."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPainterPath, QPalette
from PySide6.QtWidgets import QTreeWidgetItem, QStyledItemDelegate, QStyleOptionViewItem, QStyle
from .workflow_presentation import timing_duration


class TimeShareDelegate(QStyledItemDelegate):
    """Paint only visible timing cells; large test trees need no cell widgets."""

    def paint(self, painter, option, index):
        share = index.data(Qt.ItemDataRole.UserRole)
        if share is None:
            return super().paint(painter, option, index)
        background = QStyleOptionViewItem(option)
        self.initStyleOption(background, index)
        background.text = ''
        option.widget.style().drawControl(QStyle.ControlElement.CE_ItemViewItem,
                                           background, painter, option.widget)
        painter.save()
        rect = QRectF(option.rect.adjusted(4, 2, -4, -2))
        groove = QPainterPath()
        groove.addRoundedRect(rect, 3, 3)
        painter.setClipPath(groove)
        tint = QColor(option.palette.mid().color())
        tint.setAlpha(35)
        painter.fillRect(rect, tint)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        tint = QColor(option.palette.highlightedText().color() if selected else option.palette.highlight().color())
        tint.setAlpha(90)
        fill = QRectF(rect)
        fill.setWidth(rect.width() * max(0, min(1, share)))
        painter.fillRect(fill, tint)
        painter.setClipping(False)
        role = QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text
        painter.setPen(option.palette.color(role))
        painter.setFont(option.font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, index.data(Qt.ItemDataRole.DisplayRole))
        painter.restore()


def time_share(tree, row, seconds, total, *, reused=False):
    if not isinstance(tree.itemDelegateForColumn(2), TimeShareDelegate):
        tree.setItemDelegateForColumn(2, TimeShareDelegate(tree))
    share = seconds / total if not reused and seconds is not None and total and total > 0 else None
    label = '—' if reused else timing_duration(seconds)
    row.setText(2, label)
    row.setData(2, Qt.ItemDataRole.UserRole, share)
    description = (f'{label}, {share:.1%} of measured sibling time' if share is not None else label)
    if reused:
        description = 'Reused result; no test execution in this run.'
        if seconds is not None:
            description += f' Previous run: {timing_duration(seconds)}.'
        row.setData(2, Qt.ItemDataRole.AccessibleTextRole, description)
        row.setToolTip(2, description)
        return
    row.setData(2, Qt.ItemDataRole.AccessibleTextRole, description)
    row.setToolTip(2, description + '\nFill shows the share of measured time at this level. '
                   'Expanded children total 100% independently. Parallel work may overlap. '
                   'Not an estimate of completion.')


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
            if info.get('kind') == 'folder' or (info.get('seconds') is None and nested):
                measured = [child['seconds'] for child, _ in nested if child.get('seconds') is not None]
                info['seconds'] = sum(measured) if measured else None
            if info.get('kind') == 'folder':
                statuses = {child.get('status') for child, _ in nested}
                info['status'] = next((state for state in ('running', 'failed', 'error', 'timeout', 'crashed', 'cancelled', 'interrupted', 'reported', 'planned', 'pending')
                                       if state in statuses), 'passed')
    summarize(roots)
    if not roots and phase is not None and 'junit' in phase.artifact_types.values():
        roots.append((dict(name='Test list not declared by this project', kind='info', status='pending',
            message='Individual tests appear when the runner reports them.'), []))
    # Tick only the current test's elapsed display; completed rows remain stable.
    signature = repr((roots, bool(fact.get('tests_provisional')), bool(fact.get('reused')), round(fact.get('seconds') or 0)))
    if not force and getattr(row, '_test_signature', None) == signature:
        return
    row._test_signature = signature
    tree = row.treeWidget()
    selected = tree.currentItem()

    def sync(parent, nodes):
        total = sum(case.get('seconds') or 0 for case, _ in nodes)
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
            child.setData(0, Qt.ItemDataRole.UserRole, key)
            child.setData(0, Qt.ItemDataRole.UserRole + 1, case)
            from .test_results import stage_label
            stage = 'Stage: ' + stage_label(case) if case.get('stage') else ''
            child.setToolTip(0, '\n'.join(filter(None, (stage, case.get('path'), case.get('file'), case.get('classname'), case.get('suite'), case.get('message')))))
            time_share(tree, child, case.get('seconds'), total, reused=fact.get('reused', False))
            sync(child, nested)
        for index in range(parent.childCount() - 1, -1, -1):
            if id(parent.child(index)) not in keep:
                parent.takeChild(index)

    sync(row, roots)
    if selected is not None and selected.treeWidget() is tree:
        tree.setCurrentItem(selected)

