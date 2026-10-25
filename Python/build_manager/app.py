"""Minimal manager-owned GUI entry for shared cross-platform launchers."""
import argparse
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke-exit', action='store_true')
    parser.add_argument('--registry', type=Path)
    args = parser.parse_args(argv)
    from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
    from PySide6.QtCore import QTimer
    app = QApplication.instance() or QApplication([])
    window = QWidget()
    window.setWindowTitle('Build Deployment Manager')
    QVBoxLayout(window).addWidget(QLabel('Build Deployment Manager · project-owned plans and results'))
    window.resize(720, 240)
    window.show()
    if args.smoke_exit:
        QTimer.singleShot(150, window.close)
    return app.exec()
