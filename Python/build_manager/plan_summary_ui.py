"""Native desktop summary shared by review, live runs and retained results."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget)
from .plan_summary import captured_choices


class PlanSummaryView(QScrollArea):
    phase_selected = Signal(str)
    blocker_selected = Signal(str)
    problems_selected = Signal(str)
    group_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setAccessibleName('Run summary with captured choices and approval boundaries')
        self.body = QWidget()
        self.setWidget(self.body)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 6, 0)
        self.entries = []
        self.plan = None

    def label(self, text, layout):
        control = QLabel(str(text))
        control.setTextFormat(Qt.TextFormat.PlainText)
        control.setWordWrap(True)
        control.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        control.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(control)
        return control

    def reset(self, plan, fields=(), *, preview=True, capability=None, proposal=None):
        self.plan, self.preview = plan, preview
        while self.body_layout.count():
            item = self.body_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        self.entries = []
        choices = QWidget()
        choice_layout = QHBoxLayout(choices)
        choice_layout.setContentsMargins(0, 0, 0, 0)
        for name, value in captured_choices(plan):
            group = QGroupBox(name)
            column = QVBoxLayout(group)
            displayed = value
            identity = plan.source.get('commit') or plan.source.get('fingerprint')
            if name == 'Source' and identity and len(str(identity)) > 16:
                displayed = value.replace(str(identity), str(identity)[:12] + '…')
            label = self.label(displayed, column)
            label.setToolTip(value)
            label.setAccessibleDescription(value)
            choice_layout.addWidget(group, 1)
        self.body_layout.addWidget(choices)
        from .grouped_workflow_ui import GroupedFlowView
        self.flow = GroupedFlowView(graph_mode=not preview)
        choices.setVisible(preview)
        self.flow.pages.currentChanged.connect(lambda index, choices=choices, preview=preview: choices.setVisible(preview and index == 0))
        self.flow.phase_selected.connect(self.phase_selected.emit)
        self.flow.blocker_selected.connect(self.blocker_selected.emit)
        self.flow.problems_selected.connect(self.problems_selected.emit)
        self.flow.group_selected.connect(self.group_selected.emit)
        self.flow.reset(plan, fields, preview=preview, capability=capability, proposal=proposal)
        self.body_layout.addWidget(self.flow, 1)
        self.verticalScrollBar().setValue(0)

    def set_facts(self, facts):
        if self.plan is not None:
            self.flow.set_facts(facts)
