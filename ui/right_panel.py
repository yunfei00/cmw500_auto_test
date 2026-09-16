from __future__ import annotations

import re
from datetime import datetime

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from core.paths import ensure_user_data_dir


class RightPanel(QWidget):
    """Concise operator log.

    Normal LTE measurement points are rendered as aligned numeric rows only.
    Detailed worker messages still exist internally, but repetitive INFO messages
    are intentionally hidden from the operator view. Warnings/errors are never
    hidden.
    """

    _BLER_RE = re.compile(r"\bBLER=([-+]?\d+(?:\.\d+)?)%?")
    _FC_POWER_RE = re.compile(r"Full Cell BW Power=([-+]?\d+(?:\.\d+)?)\s*dBm")
    _CELL_RE = re.compile(r"LTE 小区配置完成：([^ ]+) 信道 (\d+) BW=([^ ]+)")

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumWidth(320)
        self._pending_bler: float | None = None

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
        self.log_edit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.log_edit.document().setMaximumBlockCount(5000)
        self.log_file = ensure_user_data_dir() / "logs" / f"cmw500_{datetime.now():%Y%m%d}.log"
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

        layout.addLayout(button_layout)
        layout.addWidget(self.log_edit, 1)

    def _append_line(self, line: str) -> None:
        self.log_edit.appendPlainText(line)
        self.log_edit.verticalScrollBar().setValue(self.log_edit.verticalScrollBar().maximum())
        try:
            with self.log_file.open("a", encoding="utf-8") as file:
                file.write(f"{line}\n")
        except OSError:
            pass

    def append_log(self, level: str, message: str) -> None:
        now = datetime.now()
        time_text = now.strftime("%H:%M:%S.%f")[:-3]

        # Cache the BLER result. It is rendered only when the matching Full Cell
        # BW Power readback arrives immediately afterwards.
        bler_match = self._BLER_RE.search(message)
        if bler_match and message.startswith("LTE "):
            self._pending_bler = float(bler_match.group(1))
            return

        fc_match = self._FC_POWER_RE.search(message)
        if fc_match and self._pending_bler is not None:
            fc_power = float(fc_match.group(1))
            # Fixed-width columns: time, BLER, Full Cell BW Power.
            self._append_line(f"{time_text}  {self._pending_bler:6.2f}  {fc_power:8.2f}")
            self._pending_bler = None
            return

        # Print one compact header when a new LTE channel becomes ready.
        cell_match = self._CELL_RE.search(message)
        if cell_match:
            band, channel, bw = cell_match.groups()
            self._pending_bler = None
            self._append_line("")
            self._append_line(f"{time_text}  {band}  CH{channel}  BW={bw}")
            self._append_line("TIME          BLER   FC_PWR")
            return

        # Measurement implementation details are intentionally hidden from the
        # operator view. They remain available through result data/command trace.
        if level == "INFO":
            repetitive = (
                message.startswith(("FAST ", "CONFIRM ", "FINE ", "COARSE "))
                or message.startswith("LTE 快速灵敏度扫描：")
                or message.startswith("确认 FAIL：")
                or message.startswith("Sensitivity 边界：")
                or message.startswith("状态切换：")
                or message in {"UE Attach 检查通过", "执行测量前命令", "执行测量后命令"}
            )
            if repetitive:
                return

        # Keep lifecycle information and all warnings/errors visible, but compact.
        message = re.sub(r"\s*DUT=[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*dBm,?\s*", " ", message)
        message = re.sub(r"\s*DUT 电平 [+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*dBm\s*", " ", message)
        message = " ".join(message.split())
        prefix = "" if level == "INFO" else f"[{level}] "
        self._append_line(f"{time_text}  {prefix}{message}")

    def clear_log(self) -> None:
        self._pending_bler = None
        self.log_edit.clear()

    def save_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "保存日志", "cmw500_auto_test.log", "日志文件 (*.log *.txt);;所有文件 (*.*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as file:
                file.write(self.log_edit.toPlainText())
        except OSError as exc:
            QMessageBox.critical(self, "日志保存失败", str(exc))
            return
        self.append_log("INFO", f"日志已保存：{path}")
