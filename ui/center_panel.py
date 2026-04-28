from __future__ import annotations

from collections.abc import Callable
from dataclasses import is_dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from core.models import TestResult


LogCallback = Callable[[str, str], None]


class CenterPanel(QWidget):
    HEADERS = [
        "序号",
        "制式",
        "Band",
        "信道",
        "频点类型",
        "测试模式",
        "接收电平(dBm)",
        "指标类型",
        "指标值",
        "结果",
        "状态",
        "时间",
    ]

    def __init__(self) -> None:
        super().__init__()
        self._logger: LogCallback | None = None
        self.summary_labels: dict[str, QLabel] = {}

        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(self._create_summary_bar())
        layout.addLayout(self._create_table_toolbar())

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(72)
        layout.addWidget(self.table, 1)

    def set_logger(self, logger: LogCallback) -> None:
        self._logger = logger

    def add_test_row(self, result: TestResult | dict) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        row_data = self._normalize_row_data(result)
        row_data.setdefault("序号", str(row + 1))
        row_result = str(row_data.get("结果", "")).upper()
        background = self._result_background(row_result)

        for column, header in enumerate(self.HEADERS):
            value = str(row_data.get(header, ""))
            item = QTableWidgetItem(value)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if background:
                item.setBackground(background)
            if header == "结果" and row_result == "PASS":
                item.setForeground(Qt.GlobalColor.darkGreen)
            elif header == "结果" and row_result == "FAIL":
                item.setForeground(Qt.GlobalColor.red)
            self.table.setItem(row, column, item)

        if self.auto_scroll_checkbox.isChecked():
            self.table.scrollToBottom()

    def update_summary(self, data: dict) -> None:
        key_map = {
            "current_mode": "当前制式",
            "current_band": "当前Band",
            "current_channel": "当前信道",
            "current_level": "当前电平",
            "progress": "当前进度",
        }
        normalized = {key_map.get(key, key): value for key, value in data.items()}
        for key, value in normalized.items():
            if key in self.summary_labels:
                self.summary_labels[key].setText(f"{key}：{value}")

    def _log(self, level: str, message: str) -> None:
        if self._logger:
            self._logger(level, message)

    def _create_summary_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("summaryBar")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet(
            """
            QFrame#summaryBar {
                background: #ffffff;
                border: 1px solid #c3cbd4;
                border-radius: 4px;
            }
            """
        )
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(14)

        for key in ["当前制式", "当前Band", "当前信道", "当前电平", "当前进度"]:
            label = QLabel(f"{key}：{'0/0' if key == '当前进度' else '-'}")
            label.setMinimumWidth(88)
            self.summary_labels[key] = label
            layout.addWidget(label)
        layout.addStretch(1)
        return frame

    def _create_table_toolbar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        clear_button = QPushButton("清空表格")
        export_button = QPushButton("导出当前结果")
        self.auto_scroll_checkbox = QCheckBox("自动滚动到底部")
        self.auto_scroll_checkbox.setChecked(True)

        clear_button.clicked.connect(self._clear_table)
        export_button.clicked.connect(lambda: self._log("INFO", "导出当前结果"))

        layout.addWidget(clear_button)
        layout.addWidget(export_button)
        layout.addStretch(1)
        layout.addWidget(self.auto_scroll_checkbox)
        return layout

    def _clear_table(self) -> None:
        self.table.setRowCount(0)
        self._log("INFO", "已清空实时测试数据表格")

    def _normalize_row_data(self, result: TestResult | dict) -> dict:
        if isinstance(result, TestResult) or is_dataclass(result):
            return {
                "序号": result.index,
                "制式": result.mode,
                "Band": result.band,
                "信道": result.channel,
                "频点类型": result.channel_type,
                "测试模式": result.test_mode,
                "接收电平(dBm)": f"{result.rx_level:g}",
                "指标类型": result.metric_type,
                "指标值": f"{result.metric_value:.2f}",
                "结果": result.result,
                "状态": result.status,
                "时间": result.timestamp,
            }
        return dict(result)

    def _result_background(self, result: str) -> QColor | None:
        if result == "PASS":
            return QColor("#eaf7ea")
        if result == "FAIL":
            return QColor("#fdecec")
        if result in {"ERROR", "异常"}:
            return QColor("#fff7d6")
        return None
