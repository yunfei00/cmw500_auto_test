from __future__ import annotations

from collections.abc import Callable
from dataclasses import is_dataclass
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.models import TestResult
from core.result_summary import SummaryResult, build_lte_summary
from reports.excel_exporter import export_results_to_excel


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
    SUMMARY_HEADERS = [
        "制式",
        "Band",
        "信道",
        "频点类型",
        "测试模式",
        "灵敏度(dBm)",
        "PASS数量",
        "FAIL数量",
        "总数",
        "结果",
        "备注",
    ]

    def __init__(self) -> None:
        super().__init__()
        self._logger: LogCallback | None = None
        self.summary_labels: dict[str, QLabel] = {}
        self.test_results: list[TestResult] = []
        self.summary_results: list[SummaryResult] = []

        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(self._create_summary_bar())
        layout.addLayout(self._create_table_toolbar())

        self.tab_widget = QTabWidget()
        self.realtime_tab = QWidget()
        self.summary_tab = QWidget()
        self.table = self._create_table(self.HEADERS)
        self.summary_table = self._create_table(self.SUMMARY_HEADERS)

        realtime_layout = QVBoxLayout(self.realtime_tab)
        realtime_layout.setContentsMargins(0, 0, 0, 0)
        realtime_layout.addWidget(self.table)

        summary_layout = QVBoxLayout(self.summary_tab)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.addWidget(self.summary_table)

        self.tab_widget.addTab(self.realtime_tab, "实时数据")
        self.tab_widget.addTab(self.summary_tab, "汇总结果")
        layout.addWidget(self.tab_widget, 1)

    def set_logger(self, logger: LogCallback) -> None:
        self._logger = logger

    def add_test_row(self, result: TestResult | dict) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        if isinstance(result, TestResult):
            self.test_results.append(result)

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

    def update_summary_table(self, summary_results: list[SummaryResult]) -> None:
        self.summary_table.setRowCount(0)
        for summary_result in summary_results:
            row = self.summary_table.rowCount()
            self.summary_table.insertRow(row)
            row_data = self._summary_result_to_row_data(summary_result)
            row_result = str(row_data.get("结果", "")).upper()
            background = self._result_background(row_result)

            for column, header in enumerate(self.SUMMARY_HEADERS):
                value = str(row_data.get(header, ""))
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if background:
                    item.setBackground(background)
                if header == "结果" and row_result == "PASS":
                    item.setForeground(Qt.GlobalColor.darkGreen)
                elif header == "结果" and row_result == "FAIL":
                    item.setForeground(Qt.GlobalColor.red)
                self.summary_table.setItem(row, column, item)

    def generate_summary_from_current_results(self) -> None:
        self._log("INFO", "开始生成汇总结果")
        self.summary_results = build_lte_summary(self.test_results)
        self.update_summary_table(self.summary_results)
        self._log("INFO", f"共生成 {len(self.summary_results)} 条汇总结果")
        self.tab_widget.setCurrentWidget(self.summary_tab)

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
        export_button.clicked.connect(self._export_current_results)

        layout.addWidget(clear_button)
        layout.addWidget(export_button)
        layout.addStretch(1)
        layout.addWidget(self.auto_scroll_checkbox)
        return layout

    def _clear_table(self) -> None:
        self.table.setRowCount(0)
        self.summary_table.setRowCount(0)
        self.test_results.clear()
        self.summary_results.clear()
        self.update_summary(
            {
                "当前制式": "-",
                "当前Band": "-",
                "当前信道": "-",
                "当前电平": "-",
                "当前进度": "0/0",
            }
        )
        self.tab_widget.setCurrentWidget(self.realtime_tab)
        self._log("INFO", "已清空实时测试数据和汇总结果")

    def _create_table(self, headers: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setMinimumSectionSize(72)
        return table

    def _export_current_results(self) -> None:
        if not self.summary_results and self.test_results:
            self.summary_results = build_lte_summary(self.test_results)
            self.update_summary_table(self.summary_results)

        default_name = f"cmw500_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "导出当前结果",
            default_name,
            "Excel 工作簿 (*.xlsx);;所有文件 (*.*)",
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".xlsx"):
            file_path = f"{file_path}.xlsx"

        try:
            export_results_to_excel(self.test_results, self.summary_results, file_path)
        except Exception as exc:
            self._log("ERROR", f"结果导出失败：{exc}")
            return

        self._log("INFO", f"结果已导出：{file_path}")

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

    def _summary_result_to_row_data(self, result: SummaryResult) -> dict:
        return {
            "制式": result.mode,
            "Band": result.band,
            "信道": result.channel,
            "频点类型": result.channel_type,
            "测试模式": result.test_mode,
            "灵敏度(dBm)": "-" if result.sensitivity is None else f"{result.sensitivity:g}",
            "PASS数量": result.pass_count,
            "FAIL数量": result.fail_count,
            "总数": result.total_count,
            "结果": result.result,
            "备注": result.remark,
        }

    def _result_background(self, result: str) -> QColor | None:
        if result == "PASS":
            return QColor("#eaf7ea")
        if result == "FAIL":
            return QColor("#fdecec")
        if result in {"ERROR", "异常"}:
            return QColor("#fff7d6")
        return None
