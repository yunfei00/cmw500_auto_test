from __future__ import annotations

from PySide6.QtCore import QTime
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


class RightPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        button_layout = QHBoxLayout()
        clear_button = QPushButton("清空日志")
        save_button = QPushButton("保存日志")
        clear_button.clicked.connect(self.clear_log)
        save_button.clicked.connect(self.save_log)
        button_layout.addWidget(clear_button)
        button_layout.addWidget(save_button)

        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)

        layout.addLayout(button_layout)
        layout.addWidget(self.log_edit, 1)

    def append_log(self, level: str, message: str) -> None:
        timestamp = QTime.currentTime().toString("HH:mm:ss")
        self.log_edit.appendPlainText(f"[{timestamp}][{level}] {message}")
        self.log_edit.verticalScrollBar().setValue(self.log_edit.verticalScrollBar().maximum())

    def clear_log(self) -> None:
        self.log_edit.clear()

    def save_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "保存日志", "cmw500_auto_test.log", "日志文件 (*.log *.txt);;所有文件 (*.*)")
        if not path:
            return

        with open(path, "w", encoding="utf-8") as file:
            file.write(self.log_edit.toPlainText())
        self.append_log("INFO", f"日志已保存：{path}")
