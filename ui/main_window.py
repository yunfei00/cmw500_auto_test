from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QGroupBox,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QWidget,
)

from app_info import APP_VERSION
from ui.center_panel import CenterPanel
from ui.left_panel import LeftPanel
from ui.right_panel import RightPanel


class MainWindow(QMainWindow):
    SETTINGS_ORG = "cmw500_tool"
    SETTINGS_APP = "cmw500_auto_test"
    LAST_INSTRUMENT_MODE_KEY = "instrument/last_mode"
    LAST_CONNECTION_TYPE_KEY = "instrument/last_connection_type"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"CMW500 手机灵敏度自动化测试工具 {APP_VERSION}")
        self.resize(1500, 900)
        self.settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)

        self.left_panel = LeftPanel()
        self._enhance_lte_panel()
        self._restore_instrument_selection()
        self._bind_instrument_selection_persistence()
        self.center_panel = CenterPanel()
        self.right_panel = RightPanel()

        self.left_panel.set_logger(self.right_panel.append_log)
        self.center_panel.set_logger(self.right_panel.append_log)
        self.left_panel.set_add_row_callback(self.center_panel.add_test_row)
        self.left_panel.set_update_summary_callback(self.center_panel.update_summary)
        self.left_panel.set_run_started_callback(self.center_panel.begin_run)
        self.left_panel.set_finished_callback(self.center_panel.finish_run)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.center_panel)
        splitter.addWidget(self.right_panel)
        splitter.setStretchFactor(0, 32)
        splitter.setStretchFactor(1, 43)
        splitter.setStretchFactor(2, 25)
        splitter.setSizes([480, 645, 375])

        self.setCentralWidget(splitter)
        self.setStyleSheet(self._style_sheet())
        self.right_panel.append_log("INFO", f"{self.windowTitle()} 已启动")
        self.right_panel.append_log(
            "INFO",
            "已恢复上次仪表选择："
            f"{self.left_panel.instrument_mode_combo.currentText()} / "
            f"{self.left_panel.connection_type_combo.currentText()}",
        )

    def _restore_instrument_selection(self) -> None:
        """Restore the operator's last instrument/transport selection."""
        mode = self.settings.value(self.LAST_INSTRUMENT_MODE_KEY, "Fake", str)
        connection_type = self.settings.value(
            self.LAST_CONNECTION_TYPE_KEY,
            "VISA（推荐）",
            str,
        )

        if isinstance(mode, str):
            index = self.left_panel.instrument_mode_combo.findText(mode)
            if index >= 0:
                self.left_panel.instrument_mode_combo.setCurrentIndex(index)

        if isinstance(connection_type, str):
            index = self.left_panel.connection_type_combo.findText(connection_type)
            if index >= 0:
                self.left_panel.connection_type_combo.setCurrentIndex(index)

    def _bind_instrument_selection_persistence(self) -> None:
        self.left_panel.instrument_mode_combo.currentTextChanged.connect(
            self._save_instrument_mode
        )
        self.left_panel.connection_type_combo.currentTextChanged.connect(
            self._save_connection_type
        )

    def _save_instrument_mode(self, mode: str) -> None:
        self.settings.setValue(self.LAST_INSTRUMENT_MODE_KEY, mode)
        self.settings.sync()

    def _save_connection_type(self, connection_type: str) -> None:
        self.settings.setValue(self.LAST_CONNECTION_TYPE_KEY, connection_type)
        self.settings.sync()

    def _enhance_lte_panel(self) -> None:
        """Keep the three LTE configuration groups collapsible."""
        tabs = self.left_panel.standard_group.findChild(QTabWidget)
        if tabs is None or tabs.count() == 0:
            return

        lte_tab = tabs.widget(0)
        if lte_tab is None:
            return

        lte_groups = lte_tab.findChildren(
            QGroupBox,
            options=Qt.FindChildOption.FindDirectChildrenOnly,
        )
        target_titles = {"仪表配置", "测试项选择", "Band 配置"}
        group_map = {group.title(): group for group in lte_groups if group.title() in target_titles}

        for title in ("仪表配置", "测试项选择", "Band 配置"):
            group = group_map.get(title)
            if group is not None:
                self._make_group_collapsible(group)

    def _make_group_collapsible(self, group: QGroupBox) -> None:
        """Use the group title checkbox as a compact expand/collapse control."""
        group.setCheckable(True)
        group.setChecked(True)

        def set_expanded(expanded: bool) -> None:
            for child in group.findChildren(
                QWidget,
                options=Qt.FindChildOption.FindDirectChildrenOnly,
            ):
                child.setVisible(expanded)
            group.updateGeometry()

        group.toggled.connect(set_expanded)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.left_panel.is_test_running():
            answer = QMessageBox.question(
                self,
                "测试仍在运行",
                "关闭程序前将停止测试并执行 Cell OFF/Cleanup。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        if self.left_panel.shutdown():
            event.accept()
            return

        if self.left_panel.requires_unsafe_exit_acknowledgement():
            answer = QMessageBox.question(
                self,
                "安全清理未确认",
                "自动 Cell OFF/Cleanup 失败。只有在您已人工确认仪表 RF/Cell OFF 后，"
                "才能强制退出。是否确认已完成人工安全处置并退出？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self.left_panel.acknowledge_unsafe_exit()
                if self.left_panel.shutdown():
                    event.accept()
                    return

        QMessageBox.critical(
            self,
            "无法安全退出",
            "仪表操作尚未结束或安全清理失败，程序将保持运行。请确认 RF 状态后重试。",
        )
        event.ignore()

    def _style_sheet(self) -> str:
        return """
            QMainWindow {
                background: #f3f5f7;
            }
            QWidget {
                font-family: "Microsoft YaHei", "Segoe UI", Arial;
                font-size: 12px;
                color: #20252b;
            }
            QGroupBox {
                font-weight: normal;
                border: 1px solid #c3cbd4;
                border-radius: 4px;
                margin-top: 10px;
                padding: 8px 6px 6px 6px;
                background: #fbfcfd;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 4px;
                color: #243447;
                font-weight: bold;
            }
            QPushButton {
                min-height: 28px;
                padding: 2px 10px;
                border: 1px solid #9aa8b5;
                border-radius: 3px;
                background: #eef2f5;
            }
            QPushButton:hover {
                background: #e2e8ee;
            }
            QPushButton:pressed {
                background: #d5dde5;
            }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                min-height: 24px;
                border: 1px solid #b7c1ca;
                border-radius: 3px;
                padding: 1px 5px;
                background: #ffffff;
            }
            QTabWidget::pane {
                border: 1px solid #c3cbd4;
                background: #ffffff;
            }
            QTabBar::tab {
                min-height: 26px;
                padding: 2px 12px;
                background: #e8edf2;
                border: 1px solid #c3cbd4;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #0d4f8b;
                font-weight: bold;
            }
            QHeaderView::section {
                font-weight: bold;
                background: #e5ebf0;
                border: 1px solid #c3cbd4;
                padding: 4px;
            }
            QTableWidget {
                gridline-color: #d5dce3;
                background: #ffffff;
                alternate-background-color: #f7f9fb;
            }
            QPlainTextEdit {
                border: 1px solid #b7c1ca;
                background: #111820;
                color: #d7e2ee;
                selection-background-color: #315b7d;
                font-family: Consolas, "Courier New", monospace;
            }
            QSplitter::handle {
                background: #d5dce3;
            }
        """
