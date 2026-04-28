from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QSplitter

from ui.center_panel import CenterPanel
from ui.left_panel import LeftPanel
from ui.right_panel import RightPanel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("CMW500 手机灵敏度自动化测试工具")
        self.resize(1500, 900)

        self.left_panel = LeftPanel()
        self.center_panel = CenterPanel()
        self.right_panel = RightPanel()

        self.left_panel.set_logger(self.right_panel.append_log)
        self.center_panel.set_logger(self.right_panel.append_log)
        self.left_panel.set_add_row_callback(self.center_panel.add_test_row)
        self.left_panel.set_update_summary_callback(self.center_panel.update_summary)
        self.left_panel.set_finished_callback(self.center_panel.generate_summary_from_current_results)

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
        self.right_panel.append_log("INFO", "UI 原型已启动")

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
