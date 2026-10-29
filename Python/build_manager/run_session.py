"""One Qt-owned execution process, cancellation marker and output/timing state."""
from uuid import uuid4
from pathlib import Path
from PySide6.QtCore import QObject, QElapsedTimer, QProcess, QTimer
from .run_state import EventStream


class RunSession(QObject):
    def __init__(self, directory, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        # Match the GUI launcher's source root so the child can import the
        # pinned commonUtils submodule without inheriting a global PYTHONPATH.
        self.process.setWorkingDirectory(str(Path(directory) / 'Python'))
        self.elapsed, self.phase_elapsed = QElapsedTimer(), QElapsedTimer()
        self.clock = QTimer(self)
        self.clock.setInterval(1000)
        self.events = EventStream()
        self.current_phase = 'queued'
        self.cancel_file = None
        self.failure = None
        self.stderr = ''

    @property
    def buffer(self):
        return self.events.buffer

    @buffer.setter
    def buffer(self, text):
        self.events.buffer = text

    def read_stdout(self):
        text = bytes(self.process.readAllStandardOutput()).decode('utf-8', errors='replace')
        self.events.append(text)

    def set_busy(self, busy):
        if busy:
            self.phase_elapsed.invalidate()
            self.elapsed.start()
            self.current_phase = 'queued'
            self.clock.start()
        else:
            self.clock.stop()

    def launch(self, interpreter, plan_path, output, *, resume=False, confirmed=False, approvals=(), engine_review=None):
        suffix = '.resume-' + uuid4().hex + '.cancel' if resume else '.cancel'
        self.cancel_file = output.with_suffix(suffix)
        self.buffer = ''
        self.failure = None
        self.stderr = ''
        arguments = ['-m', 'build_manager', str(plan_path), '--output', str(output),
                     '--cancel-file', str(self.cancel_file)]
        if resume:
            arguments.append('--resume')
        if confirmed:
            arguments.append('--confirm')
        if engine_review is not None:
            arguments += ['--engine-review-identity', engine_review]
        for approval in approvals:
            arguments += ['--approve-step', approval.step,
                          '--approval-identity', approval.step + '=' + approval.identity]
        self.process.start(str(interpreter), arguments)

    def cancel(self):
        if self.process.state() != QProcess.ProcessState.NotRunning and self.cancel_file is not None:
            self.cancel_file.touch()
