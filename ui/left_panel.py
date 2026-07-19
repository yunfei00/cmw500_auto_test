from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import date, datetime
import hashlib
from pathlib import Path
import re
import uuid

from PySide6.QtCore import QObject, Qt, QSettings, QThread, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app_info import APP_BUILD_COMMIT, APP_BUILD_DIRTY, APP_BUILD_TIME, APP_VERSION
from core.channel_config import ChannelConfigManager
from core.lte_channel_config import (
    LTEChannelConfigError,
    LTEChannelConfigManager,
    default_lte_channel_config_path,
)
from core.fake_cmw500 import FakeCMW500
from core.models import LteTestConfig
from core.paths import ensure_user_data_dir, resource_path
from core.scpi_template import ScpiTemplateManager
from core.serial_config import SerialConfigManager
from core.test_worker import TestWorker
from devices.adb_client import AdbClient
from devices.cmw500_controller import RealCMW500
from devices.instrument_base import InstrumentBase
from devices.instrument_transport import (
    SocketTransport,
    VisaTransport,
    create_visa_resource_manager,
)


LogCallback = Callable[[str, str], None]
AddRowCallback = Callable[[object], None]
UpdateSummaryCallback = Callable[[dict], None]
RunCallback = Callable[[dict], None]
InstrumentAction = Callable[[], tuple[bool, str, object | None]]
InstrumentActionCallback = Callable[[bool, str, object | None], None]


class InstrumentActionWorker(QObject):
    finished_signal = Signal(str, bool, str, object)

    def __init__(self, task_id: str, action: InstrumentAction) -> None:
        super().__init__()
        self.task_id = task_id
        self.action = action

    def run(self) -> None:
        try:
            success, message, payload = self.action()
        except Exception as exc:
            success, message, payload = False, str(exc), None
        self.finished_signal.emit(self.task_id, success, message, payload)


class LeftPanel(QScrollArea):
    SETTINGS_ORG = "cmw500_tool"
    SETTINGS_APP = "cmw500_auto_test"
    LAST_VISA_RESOURCE_KEY = "instrument/last_visa_resource"

    def __init__(self) -> None:
        super().__init__()
        self._logger: LogCallback | None = None
        self._add_row_callback: AddRowCallback | None = None
        self._update_summary_callback: UpdateSummaryCallback | None = None
        self._run_started_callback: RunCallback | None = None
        self._finished_callback: RunCallback | None = None
        self._pause_state = False

        self.worker_thread: QThread | None = None
        self.worker: TestWorker | None = None
        self.channel_manager = ChannelConfigManager()
        self.lte_channel_manager = LTEChannelConfigManager(default_lte_channel_config_path())
        self.serial_config_manager = SerialConfigManager()
        self.scpi_template_manager: ScpiTemplateManager | None = None
        self.adb_client = AdbClient()
        self.instrument: InstrumentBase | None = None
        self.instrument_mode = "Fake"
        self.instrument_action_tasks: dict[
            str,
            tuple[QThread, InstrumentActionWorker, InstrumentActionCallback],
        ] = {}
        self.instrument_idn = ""
        self.current_run: dict = {}
        self._active_run_instrument: InstrumentBase | None = None
        self._worker_final_status = "IDLE"
        self._unsafe_exit_pending = False
        self._run_finalized = True
        self._test_running = False
        self.band_checkboxes: dict[int, QCheckBox] = {}
        self.lte_test_item_checkboxes: dict[str, QCheckBox] = {}
        self.device_combo = QComboBox()
        self.app_path_edit = QLineEdit()
        self.package_name_edit = QLineEdit()
        self.operator_edit = QLineEdit()
        self.dut_serial_edit = QLineEdit()
        self.start_button: QPushButton | None = None
        self.pause_button: QPushButton | None = None
        self.stop_button: QPushButton | None = None
        self.settings = QSettings(self.SETTINGS_ORG, self.SETTINGS_APP)

        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setMinimumWidth(380)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.standard_group = self._create_standard_group()
        self.instrument_connection_group = self._create_instrument_connection_group()
        self.file_group = self._create_file_group()
        self.phone_group = self._create_phone_group()
        self.scene_group = self._create_scene_group()
        self.control_group = self._create_control_group()
        self.adb_group = self._create_adb_group()
        self.test_sensitive_widgets = [
            self.standard_group,
            self.instrument_connection_group,
            self.file_group,
            self.phone_group,
            self.scene_group,
            self.adb_group,
        ]

        layout.addWidget(self.standard_group)
        layout.addWidget(self.instrument_connection_group)
        layout.addWidget(self.file_group)
        layout.addWidget(self.phone_group)
        layout.addWidget(self.scene_group)
        layout.addWidget(self.control_group)
        layout.addWidget(self.adb_group)
        layout.addStretch(1)

        self.setWidget(container)
        self._restore_last_instrument_resource()
        self._init_lte_channel_config()
        self._init_default_scpi_template()

    def set_logger(self, logger: LogCallback) -> None:
        self._logger = logger

    def set_add_row_callback(self, callback: AddRowCallback) -> None:
        self._add_row_callback = callback

    def set_update_summary_callback(self, callback: UpdateSummaryCallback) -> None:
        self._update_summary_callback = callback

    def set_run_started_callback(self, callback: RunCallback) -> None:
        self._run_started_callback = callback

    def set_finished_callback(self, callback: RunCallback) -> None:
        self._finished_callback = callback

    def _log(self, level: str, message: str) -> None:
        if self._logger:
            self._logger(level, message)

    def _create_standard_group(self) -> QGroupBox:
        group = QGroupBox("制式配置")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 14, 8, 8)

        tabs = QTabWidget()
        tabs.addTab(self._create_lte_tab(), "LTE")
        tabs.addTab(
            self._create_placeholder_tab(["仪表配置", "信道选择", "制式/速率配置"]),
            "WiFi",
        )
        tabs.addTab(
            self._create_placeholder_tab(["仪表配置", "信道选择", "Band 配置"]),
            "WCDMA",
        )
        tabs.addTab(
            self._create_placeholder_tab(["仪表配置", "信道选择", "Band 配置"]),
            "GSM",
        )
        for index in range(1, tabs.count()):
            tabs.setTabEnabled(index, False)
            tabs.setTabToolTip(index, "当前商业候选版本仅开放 LTE")

        layout.addWidget(tabs)
        return group

    def _create_lte_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(self._create_lte_instrument_group())
        layout.addWidget(self._create_lte_channel_group())
        layout.addWidget(self._create_lte_band_group())
        layout.addStretch(1)
        return tab

    def _create_lte_instrument_group(self) -> QGroupBox:
        group = QGroupBox("仪表配置")
        form = QFormLayout(group)
        form.setContentsMargins(8, 14, 8, 8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.cable_loss_spin = self._double_spin(0.0, " dB", 0.0, 100.0)
        self.sensitivity_upper_spin = self._double_spin(-70.0, " dBm", -200.0, 50.0)
        self.start_level_spin = self._double_spin(-70.0, " dBm", -200.0, 50.0)
        self.stop_level_spin = self._double_spin(-120.0, " dBm", -200.0, 50.0)
        self.packet_count_spin = self._spin(1000, 1, 999999)
        self.max_step_spin = self._double_spin(4.0, " dB", 0.1, 100.0)
        self.min_step_spin = self._double_spin(1.0, " dB", 0.1, 100.0)
        self.bler_threshold_spin = self._double_spin(10.0, " %", 0.0, 100.0)
        self.settle_time_spin = self._spin(2, 0, 3600, " s")
        self.retry_count_spin = self._spin(1, 0, 100)

        form.addRow("线损：", self.cable_loss_spin)
        form.addRow("灵敏度上限：", self.sensitivity_upper_spin)
        form.addRow("初始电平：", self.start_level_spin)
        form.addRow("结束电平：", self.stop_level_spin)
        form.addRow("测试包个数：", self.packet_count_spin)
        form.addRow("最大步长：", self.max_step_spin)
        form.addRow("最小步长：", self.min_step_spin)
        form.addRow("BLER门限：", self.bler_threshold_spin)
        form.addRow("稳定等待时间：", self.settle_time_spin)
        form.addRow("失败重试次数：", self.retry_count_spin)
        return group

    def _create_lte_channel_group(self) -> QGroupBox:
        group = QGroupBox("测试项选择")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 14, 8, 8)

        hint = QLabel("固定信道由 Excel「固定信道」列自动决定，无需勾选")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        grid = QGridLayout()
        test_items = ["转盘测试", "TOP测试", "三信道测试"]
        for index, name in enumerate(test_items):
            checkbox = QCheckBox(name)
            checkbox.setChecked(name == "三信道测试")
            self.lte_test_item_checkboxes[name] = checkbox
            grid.addWidget(checkbox, index // 2, index % 2)

        layout.addLayout(grid)
        return group

    def _create_lte_band_group(self) -> QGroupBox:
        group = QGroupBox("Band 配置")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(8)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        for band in range(1, 67):
            checkbox = QCheckBox(f"B{band}")
            self.band_checkboxes[band] = checkbox
            index = band - 1
            grid.addWidget(checkbox, index // 4, index % 4)

        button_layout = QHBoxLayout()
        select_all_button = QPushButton("全选")
        clear_button = QPushButton("清空")
        common_button = QPushButton("常用Band")
        select_all_button.clicked.connect(self._select_all_bands)
        clear_button.clicked.connect(self._clear_bands)
        common_button.clicked.connect(self._select_common_bands)
        button_layout.addWidget(select_all_button)
        button_layout.addWidget(clear_button)
        button_layout.addWidget(common_button)

        layout.addLayout(grid)
        layout.addLayout(button_layout)
        return group

    def _create_instrument_connection_group(self) -> QGroupBox:
        group = QGroupBox("仪表连接配置")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(8)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.instrument_mode_combo = QComboBox()
        self.instrument_mode_combo.addItems(["Fake", "Real CMW500"])
        self.instrument_mode_combo.currentTextChanged.connect(self._on_instrument_mode_changed)
        self.connection_type_combo = QComboBox()
        self.connection_type_combo.addItems(["VISA（推荐）", "SOCKET"])
        self.connection_type_combo.currentTextChanged.connect(self._on_connection_type_changed)

        self.visa_resource_edit = QLineEdit("TCPIP0::169.254.65.34::inst0::INSTR")
        self.visa_timeout_spin = QSpinBox()
        self.visa_timeout_spin.setRange(100, 600000)
        self.visa_timeout_spin.setSuffix(" ms")
        self.visa_timeout_spin.setValue(10000)

        self.instrument_host_edit = QLineEdit("169.254.65.34")
        self.instrument_port_spin = QSpinBox()
        self.instrument_port_spin.setRange(1, 65535)
        self.instrument_port_spin.setValue(5025)
        self.instrument_timeout_spin = QSpinBox()
        self.instrument_timeout_spin.setRange(100, 600000)
        self.instrument_timeout_spin.setSuffix(" ms")
        self.instrument_timeout_spin.setValue(10000)

        self.instrument_status_label = QLabel("未连接")
        self.instrument_mode_warning_label = QLabel(
            "当前为 SIMULATION 模式，结果不得作为正式实测报告"
        )
        self.instrument_mode_warning_label.setStyleSheet(
            "background:#9b1c1c;color:white;font-weight:bold;padding:4px;border-radius:3px;"
        )
        self.instrument_mode_warning_label.setWordWrap(True)
        self.calibration_id_edit = QLineEdit()
        self.calibration_id_edit.setPlaceholderText("校准证书/资产编号")
        self.calibration_due_date_edit = QLineEdit()
        self.calibration_due_date_edit.setPlaceholderText("YYYY-MM-DD")

        form.addRow("仪表模式：", self.instrument_mode_combo)
        form.addRow("连接方式：", self.connection_type_combo)
        self.transport_stack = QStackedWidget()
        self.transport_stack.addWidget(self._create_visa_form_widget())
        self.transport_stack.addWidget(self._create_socket_form_widget())
        form.addRow("连接参数：", self.transport_stack)
        form.addRow("状态：", self.instrument_status_label)
        form.addRow("校准标识：", self.calibration_id_edit)
        form.addRow("校准有效期：", self.calibration_due_date_edit)
        form.addRow("", self.instrument_mode_warning_label)
        form.addRow("", QLabel("推荐：VISA / TCPIP INSTR，适合 CMW500 长时间自动化测试"))
        form.addRow("", QLabel("备用：SOCKET / 5025，适合无 VISA 环境"))

        button_layout = QHBoxLayout()
        connect_button = QPushButton("连接仪表")
        disconnect_button = QPushButton("断开仪表")
        idn_button = QPushButton("测试连接")
        connect_button.clicked.connect(lambda: self._connect_instrument())
        disconnect_button.clicked.connect(lambda: self._disconnect_instrument())
        idn_button.clicked.connect(lambda: self._query_instrument_idn())
        button_layout.addWidget(connect_button)
        button_layout.addWidget(disconnect_button)
        button_layout.addWidget(idn_button)

        layout.addLayout(form)
        layout.addLayout(button_layout)
        return group

    def _create_visa_form_widget(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        form.addRow("VISA Resource：", self.visa_resource_edit)
        form.addRow("超时：", self.visa_timeout_spin)
        button_layout = QHBoxLayout()
        scan_button = QPushButton("扫描 VISA 设备")
        scan_button.clicked.connect(self._scan_visa_resources)
        button_layout.addWidget(scan_button)
        button_layout.addStretch(1)
        layout.addLayout(form)
        layout.addLayout(button_layout)
        return widget

    def _create_socket_form_widget(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.addRow("IP 地址：", self.instrument_host_edit)
        form.addRow("端口：", self.instrument_port_spin)
        form.addRow("超时：", self.instrument_timeout_spin)
        return widget

    def _create_placeholder_tab(self, titles: list[str]) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        for title in titles:
            group = QGroupBox(title)
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(8, 14, 8, 8)
            group_layout.addWidget(QLabel("当前为占位配置，后续扩展"))
            layout.addWidget(group)
        layout.addStretch(1)
        return tab

    def _create_file_group(self) -> QGroupBox:
        group = QGroupBox("配置文件加载")
        layout = QGridLayout(group)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setColumnStretch(1, 1)

        self.channel_file_edit = QLineEdit()
        self.serial_file_edit = QLineEdit()
        self.scpi_template_file_edit = QLineEdit()

        self._add_file_row(layout, 0, "信道配置文件", self.channel_file_edit)
        self._add_file_row(layout, 1, "串口配置文件", self.serial_file_edit)
        self._add_file_row(layout, 2, "CMW500命令模板", self.scpi_template_file_edit)
        return group

    def _add_file_row(
        self,
        layout: QGridLayout,
        row: int,
        label_text: str,
        line_edit: QLineEdit,
    ) -> None:
        browse_button = QPushButton("浏览")
        load_button = QPushButton("加载")
        browse_button.clicked.connect(lambda: self._browse_config_file(label_text, line_edit))
        load_button.clicked.connect(lambda: self._load_config_file(label_text, line_edit.text()))

        layout.addWidget(QLabel(f"{label_text}："), row, 0)
        layout.addWidget(line_edit, row, 1)
        layout.addWidget(browse_button, row, 2)
        layout.addWidget(load_button, row, 3)

    def _create_phone_group(self) -> QGroupBox:
        group = QGroupBox("手机设置")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(8)

        device_layout = QHBoxLayout()
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self._refresh_devices)
        device_layout.addWidget(QLabel("设备序列号："))
        device_layout.addWidget(self.device_combo, 1)
        device_layout.addWidget(refresh_button)

        self.app_path_edit.setPlaceholderText("选择待安装 App")
        app_layout = QHBoxLayout()
        browse_button = QPushButton("浏览")
        install_button = QPushButton("安装")
        browse_button.clicked.connect(self._browse_app)
        install_button.clicked.connect(self._install_app)
        app_layout.addWidget(QLabel("安装App："))
        app_layout.addWidget(self.app_path_edit, 1)
        app_layout.addWidget(browse_button)
        app_layout.addWidget(install_button)

        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("测试模式："))
        self.single_main_radio = QRadioButton("单主")
        self.single_div_radio = QRadioButton("单分")
        self.main_div_radio = QRadioButton("主分集")
        self.single_main_radio.setChecked(True)
        self.mode_group = QButtonGroup(self)
        for radio in (self.single_main_radio, self.single_div_radio, self.main_div_radio):
            self.mode_group.addButton(radio)
            mode_layout.addWidget(radio)
        mode_layout.addStretch(1)

        trace_layout = QGridLayout()
        self.operator_edit.setPlaceholderText("测试人员")
        self.dut_serial_edit.setPlaceholderText("DUT 序列号/资产号")
        trace_layout.addWidget(QLabel("测试人员："), 0, 0)
        trace_layout.addWidget(self.operator_edit, 0, 1)
        trace_layout.addWidget(QLabel("DUT标识："), 1, 0)
        trace_layout.addWidget(self.dut_serial_edit, 1, 1)

        layout.addLayout(device_layout)
        layout.addLayout(app_layout)
        layout.addLayout(mode_layout)
        layout.addLayout(trace_layout)
        return group

    def _create_scene_group(self) -> QGroupBox:
        group = QGroupBox("测试场景选择")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(8)

        label = QLabel("LTE 灵敏度扫描（粗扫 + 细扫 + 失败重试）")
        label.setWordWrap(True)
        layout.addWidget(label)
        return group

    def _create_control_group(self) -> QGroupBox:
        group = QGroupBox("测试控制")
        layout = QHBoxLayout(group)
        layout.setContentsMargins(8, 14, 8, 8)

        self.start_button = QPushButton("开始测试")
        self.pause_button = QPushButton("暂停测试")
        self.stop_button = QPushButton("停止测试")
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)

        self.start_button.clicked.connect(self._start_test)
        self.pause_button.clicked.connect(self._toggle_pause)
        self.stop_button.clicked.connect(self._stop_test)

        layout.addWidget(self.start_button)
        layout.addWidget(self.pause_button)
        layout.addWidget(self.stop_button)
        return group

    def _create_adb_group(self) -> QGroupBox:
        group = QGroupBox("常用ADB操作")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(8)

        self.package_name_edit.setPlaceholderText("例如：com.xxx.testapp")
        package_layout = QHBoxLayout()
        package_layout.addWidget(QLabel("App包名："))
        package_layout.addWidget(self.package_name_edit, 1)

        button_grid = QGridLayout()
        actions = [
            ("刷新设备", self._refresh_devices),
            ("重启", self._adb_reboot),
            ("停止App", self._adb_stop_app),
            ("启动App", self._adb_start_app),
            ("清除数据", self._adb_clear_app_data),
            ("截图", self._adb_screenshot),
        ]
        for index, (button_text, handler) in enumerate(actions):
            button = QPushButton(button_text)
            button.clicked.connect(lambda checked=False, action=handler: action())
            button_grid.addWidget(button, index // 3, index % 3)

        layout.addLayout(package_layout)
        layout.addLayout(button_grid)
        return group

    def _double_spin(
        self,
        value: float,
        suffix: str,
        minimum: float,
        maximum: float,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(1)
        spin.setSingleStep(1.0)
        spin.setSuffix(suffix)
        spin.setValue(value)
        return spin

    def _spin(
        self,
        value: int,
        minimum: int,
        maximum: int,
        suffix: str = "",
    ) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(1)
        spin.setSuffix(suffix)
        spin.setValue(value)
        return spin

    def _select_all_bands(self) -> None:
        for checkbox in self.band_checkboxes.values():
            checkbox.setChecked(True)
        self._log("INFO", "已全选 LTE Band")

    def _clear_bands(self) -> None:
        for checkbox in self.band_checkboxes.values():
            checkbox.setChecked(False)
        self._log("INFO", "已清空 LTE Band")

    def _select_common_bands(self) -> None:
        common_bands = {1, 3, 5, 7, 8, 20, 28, 38, 40, 41}
        for band, checkbox in self.band_checkboxes.items():
            checkbox.setChecked(band in common_bands)
        self._log("INFO", "已选择常用 LTE Band")

    def _browse_config_file(self, label_text: str, line_edit: QLineEdit) -> None:
        if label_text == "信道配置文件":
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择信道配置文件",
                "",
                "Excel 工作簿 (*.xlsx);;所有文件 (*.*)",
            )
        elif label_text == "串口配置文件":
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择串口配置文件",
                "",
                "串口配置文件 (*.yaml *.yml *.json);;所有文件 (*.*)",
            )
        elif label_text == "CMW500命令模板":
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择 CMW500 命令模板",
                "",
                "模板文件 (*.yaml *.yml *.json);;所有文件 (*.*)",
            )
        else:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择配置文件",
                "",
                "配置文件 (*.json *.ini *.txt *.csv);;所有文件 (*.*)",
            )
        if path:
            line_edit.setText(path)

    def _load_config_file(self, label_text: str, path: str) -> None:
        if label_text == "信道配置文件":
            self._load_lte_channel_config_file(path)
            return
        if label_text == "串口配置文件":
            self._load_serial_config_file(path)
            return
        if label_text == "CMW500命令模板":
            self._load_scpi_template_file(path)
            return
        display_path = path.strip() or "未选择文件"
        self._log("INFO", f"已加载 {label_text} 配置文件：{display_path}")

    def _init_lte_channel_config(self) -> None:
        default_path = default_lte_channel_config_path()
        self.channel_file_edit.setText(str(default_path))
        try:
            self.lte_channel_manager.ensure_default_file()
            self.lte_channel_manager.load()
            bands = self.lte_channel_manager.get_all_bands()
            self._log("INFO", f"已加载 LTE 信道配置：{self.lte_channel_manager.path}")
            self._log("INFO", f"已配置 Band：{', '.join(bands)}")
            self._auto_select_configured_bands(bands)
        except LTEChannelConfigError as exc:
            self._log("ERROR", str(exc))
        except Exception as exc:
            self._log("ERROR", f"LTE 信道配置加载失败：{exc}")

    def _init_default_scpi_template(self) -> None:
        default_path = resource_path("config/cmw500_lte_scpi_template.cmw500_recommended.yaml")
        if not default_path.is_file():
            return
        self.scpi_template_file_edit.setText(str(default_path))
        self._load_scpi_template_file(str(default_path))

    def _load_lte_channel_config_file(self, path: str) -> None:
        config_path = path.strip()
        if not config_path:
            self._log("ERROR", "请选择 LTE 信道配置文件")
            return

        try:
            self.lte_channel_manager.load(config_path)
        except LTEChannelConfigError as exc:
            self._log("ERROR", str(exc))
            QMessageBox.warning(self, "配置加载失败", str(exc))
            return
        except Exception as exc:
            self._log("ERROR", f"LTE 信道配置文件加载失败：{exc}")
            QMessageBox.warning(self, "配置加载失败", f"LTE 信道配置文件加载失败：{exc}")
            return

        bands = self.lte_channel_manager.get_all_bands()
        self._log("INFO", f"已加载 LTE 信道配置：{config_path}")
        self._log("INFO", f"已配置 Band：{', '.join(bands)}")
        checked_bands = self._auto_select_configured_bands(bands)
        if checked_bands:
            self._log("INFO", f"已自动勾选 LTE Band：{', '.join(checked_bands)}")

    def _load_serial_config_file(self, path: str) -> None:
        config_path = path.strip()
        if not config_path:
            self._log("ERROR", "请选择串口配置文件")
            return

        try:
            self.serial_config_manager.load_file(config_path)
        except Exception as exc:
            self._log("ERROR", f"串口配置文件加载失败：{exc}")
            return

        port_count = len(self.serial_config_manager.get_ports())
        self._log("INFO", f"已加载串口配置文件：{config_path}")
        self._log("INFO", f"共加载 {port_count} 个串口配置")

    def _load_scpi_template_file(self, path: str) -> None:
        config_path = path.strip()
        if not config_path:
            self._log("ERROR", "请选择 CMW500 命令配置文件")
            return

        manager = ScpiTemplateManager()
        try:
            manager.load_file(config_path)
        except Exception as exc:
            self._log("ERROR", f"CMW500 命令配置文件加载失败：{exc}")
            return

        template = manager.get_lte_template()
        if not template:
            self._log("ERROR", "CMW500 命令配置文件未包含 LTE 模板")
            return

        self.scpi_template_manager = manager
        if isinstance(self.instrument, RealCMW500):
            self.instrument.set_scpi_template_manager(manager)
            self._log("INFO", "已将 SCPI 模板绑定到 RealCMW500")

        self._log("INFO", f"已加载 CMW500 命令配置文件：{config_path}")
        self._log("INFO", f"LTE setup 命令数：{len(template.setup)}")
        self._log("INFO", f"LTE cell_on 命令数：{len(template.cell_on)}")
        if template.wait_attach:
            self._log(
                "INFO",
                f"LTE wait_attach parser：{template.wait_attach.parser}，timeout：{template.wait_attach.timeout_sec:g}s",
            )
        else:
            self._log("WARNING", "LTE wait_attach 未配置，Real 模式无法确认 UE Attach")
        self._log("INFO", f"LTE set_rx_level 命令数：{len(template.set_rx_level)}")
        self._log("INFO", f"LTE measure_bler parser：{template.measure_bler.parser}")

    def _on_instrument_mode_changed(self, mode: str) -> None:
        self.instrument_mode = mode
        if self.instrument:
            try:
                self.instrument.disconnect()
            except Exception:
                pass
        self.instrument = None
        self.instrument_idn = ""
        self.instrument_status_label.setText("未连接")
        self.instrument_mode_warning_label.setVisible(mode == "Fake")
        self._log("INFO", f"仪表模式切换：{mode}")

    def _on_connection_type_changed(self, mode: str) -> None:
        index_map = {"VISA（推荐）": 0, "SOCKET": 1, "SERIAL（预留）": 2, "USBTMC（预留）": 3}
        self.transport_stack.setCurrentIndex(index_map.get(mode, 0))

    def _connect_instrument(self) -> None:
        if self._background_action_running():
            self._log("WARNING", "已有后台设备操作正在执行，请等待完成")
            return
        if self._instrument_connected():
            self._log("WARNING", "仪表已连接；如需更换连接，请先断开当前仪表")
            return
        mode = self.instrument_mode_combo.currentText()
        self.instrument_mode = mode
        if mode == "Fake":
            instrument = FakeCMW500()
            instrument.connect()
            self.instrument = instrument
            self.instrument_idn = instrument.query_idn()
            self.instrument_status_label.setText("Fake 已连接")
            self._log("INFO", "Fake CMW500 已连接")
            return

        connection_type = self.connection_type_combo.currentText()
        if connection_type == "VISA（推荐）":
            resource = self.visa_resource_edit.text().strip()
            if not resource:
                self._log("ERROR", "请填写 VISA Resource")
                return
            transport = VisaTransport(resource, self.visa_timeout_spin.value())
            desc = resource
        elif connection_type == "SOCKET":
            host = self.instrument_host_edit.text().strip()
            if not host:
                self._log("ERROR", "请填写 CMW500 IP")
                return
            transport = SocketTransport(host, self.instrument_port_spin.value(), self.instrument_timeout_spin.value())
            desc = f"{host}:{self.instrument_port_spin.value()}"
        else:
            self._log("ERROR", "该连接方式暂未开放")
            return

        instrument = RealCMW500(transport, fallback_simulation=False)
        if self.scpi_template_manager:
            instrument.set_scpi_template_manager(self.scpi_template_manager)
        self.instrument_status_label.setText("连接中")
        connection_info: dict[str, str] = {}

        def action() -> tuple[bool, str, object | None]:
            instrument.connect()
            validate_idn = getattr(instrument, "query_and_validate_idn", None)
            try:
                idn = validate_idn() if validate_idn else instrument.query("*IDN?")
                if "CMW" not in idn.upper():
                    raise RuntimeError(f"目标设备不是 CMW：{idn}")
            finally:
                instrument.disconnect()
            connection_info["idn"] = idn
            return True, f"Real CMW500 身份验证通过：{desc}，*IDN? -> {idn}", instrument

        def on_finished(success: bool, message: str, payload: object | None) -> None:
            if success and isinstance(payload, RealCMW500):
                self.instrument = payload
                self.instrument_idn = connection_info.get("idn", "")
                self.instrument_status_label.setText("身份已验证（测试时自动连接）")
                self._log("INFO", message)
                self._save_last_instrument_resource()
                if self.scpi_template_manager:
                    self._log("INFO", "已将 SCPI 模板绑定到 RealCMW500")
            else:
                self.instrument = None
                self.instrument_idn = ""
                self.instrument_status_label.setText(f"连接失败：{message}")
                self._log("ERROR", f"Real CMW500 连接失败：{message}")

        self._run_instrument_action(action, on_finished)

    def _handle_scanned_cmw_candidates(self, cmw_candidates: list[tuple[str, str]]) -> None:
        if not cmw_candidates:
            self._log("WARNING", "扫描到的 VISA 设备中未识别到 CMW（*IDN? 不包含 CMW）")
            return
        preferred_resource = self._pick_preferred_cmw_resource(cmw_candidates)
        self.visa_resource_edit.setText(preferred_resource)
        self._save_last_instrument_resource(preferred_resource)
        self._log("INFO", f"已自动刷新仪表资源描述符：{preferred_resource}")
        for resource, idn in cmw_candidates:
            self._log("INFO", f"CMW候选：{resource} -> {idn}")

    def _pick_preferred_cmw_resource(self, cmw_candidates: list[tuple[str, str]]) -> str:
        last_resource = self._last_saved_instrument_resource()
        for resource, _idn in cmw_candidates:
            if resource == last_resource:
                return resource
        return cmw_candidates[0][0]

    def _restore_last_instrument_resource(self) -> None:
        last_resource = self._last_saved_instrument_resource()
        if not last_resource:
            return
        self.visa_resource_edit.setText(last_resource)
        self._log("INFO", f"默认加载上次连接仪表资源：{last_resource}")

    def _last_saved_instrument_resource(self) -> str:
        value = self.settings.value(self.LAST_VISA_RESOURCE_KEY, "", str)
        return value.strip() if isinstance(value, str) else ""

    def _save_last_instrument_resource(self, resource: str | None = None) -> None:
        target = resource.strip() if isinstance(resource, str) else self.visa_resource_edit.text().strip()
        if not target:
            return
        self.settings.setValue(self.LAST_VISA_RESOURCE_KEY, target)

    def _scan_visa_resources(self) -> None:
        if self._background_action_running():
            self._log("WARNING", "已有后台设备操作正在执行，请等待完成")
            return
        timeout_ms = min(self.visa_timeout_spin.value(), 2000)

        def action() -> tuple[bool, str, object | None]:
            try:
                import pyvisa
            except ImportError as exc:
                return False, f"缺少 pyvisa：{exc}", None
            rm = create_visa_resource_manager(pyvisa)
            try:
                resources = rm.list_resources()
                cmw_candidates: list[tuple[str, str]] = []
                for resource in resources:
                    try:
                        inst = rm.open_resource(resource)
                        try:
                            inst.timeout = timeout_ms
                            idn = str(inst.query("*IDN?")).strip()
                        finally:
                            inst.close()
                    except Exception:
                        continue
                    if "CMW" in idn.upper():
                        cmw_candidates.append((resource, idn))
            finally:
                rm.close()
            if not resources:
                return True, "未扫描到 VISA 设备", None
            return True, "扫描结果：" + "，".join(resources), cmw_candidates

        def on_finished(success: bool, message: str, payload: object | None) -> None:
            if success:
                self._log("INFO", message)
                if isinstance(payload, list):
                    self._handle_scanned_cmw_candidates(payload)
            else:
                self._log("ERROR", message)

        self._run_instrument_action(action, on_finished)

    def _disconnect_instrument(self) -> None:
        if self._background_action_running():
            self._log("WARNING", "后台设备操作尚未结束，暂不能断开仪表")
            return
        if self.instrument:
            try:
                self.instrument.disconnect()
            except Exception as exc:
                self._log("ERROR", f"仪表断开异常：{exc}")
        self.instrument = None
        self.instrument_idn = ""
        self.instrument_status_label.setText("未连接")
        self._log("INFO", "仪表已断开")

    def _query_instrument_idn(self) -> None:
        if self._background_action_running():
            self._log("WARNING", "已有后台设备操作正在执行，请等待完成")
            return
        if not self.instrument:
            self._log("ERROR", "请先完成仪表身份验证")
            return

        instrument = self.instrument

        def action() -> tuple[bool, str, object | None]:
            if not instrument:
                return False, "请先完成仪表身份验证", None
            opened_here = not instrument.is_connected()
            if opened_here:
                instrument.connect()
            try:
                validate_idn = getattr(instrument, "query_and_validate_idn", None)
                idn = validate_idn() if callable(validate_idn) else instrument.query_idn()
                return True, idn, None
            finally:
                if opened_here:
                    instrument.disconnect()

        def on_finished(success: bool, message: str, payload: object | None) -> None:
            if success:
                self.instrument_idn = message
                self._log("INFO", f"IDN 返回：{message}")
            else:
                self._log("ERROR", f"查询 IDN 失败：{message}")

        self._run_instrument_action(action, on_finished)

    def _run_instrument_action(
        self,
        action: InstrumentAction,
        on_finished: InstrumentActionCallback,
    ) -> bool:
        if self._test_running:
            self._log("WARNING", "测试运行中不能启动其他设备操作")
            return False
        if self._background_action_running():
            self._log("WARNING", "已有后台设备操作正在执行，请等待完成")
            return False
        task_id = uuid.uuid4().hex
        thread = QThread(self)
        worker = InstrumentActionWorker(task_id, action)
        worker.moveToThread(thread)
        self.instrument_action_tasks[task_id] = (thread, worker, on_finished)

        thread.started.connect(worker.run)
        worker.finished_signal.connect(self._on_instrument_action_finished)
        worker.finished_signal.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda task=task_id: self.instrument_action_tasks.pop(task, None))
        self.instrument_connection_group.setEnabled(False)
        thread.start()
        return True

    def _on_instrument_action_finished(
        self,
        task_id: str,
        success: bool,
        message: str,
        payload: object | None,
    ) -> None:
        task = self.instrument_action_tasks.get(task_id)
        if not task:
            return
        thread, _worker, callback = task
        try:
            callback(success, message, payload)
        finally:
            thread.quit()
            if not self._test_running:
                self.instrument_connection_group.setEnabled(True)

    def _background_action_running(self) -> bool:
        return bool(self.instrument_action_tasks)

    def _instrument_connected(self) -> bool:
        if not self.instrument:
            return False
        try:
            return self.instrument.is_connected()
        except Exception:
            return False

    def _refresh_devices(self) -> None:
        def action() -> tuple[bool, str, object | None]:
            devices = self.adb_client.list_devices()
            if self.adb_client.last_error:
                return False, self.adb_client.last_error, devices
            return True, f"检测到 {len(devices)} 台设备", devices

        def finished(success: bool, message: str, payload: object | None) -> None:
            devices = payload if isinstance(payload, list) else []
            self.device_combo.clear()
            self.device_combo.addItems(devices)
            if success and devices:
                self._log("INFO", message)
            elif success:
                self._log("WARNING", "未检测到 ADB 设备")
            else:
                self._log("ERROR", message)

        self._run_instrument_action(action, finished)

    def _browse_app(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 App 安装包", "", "Android Package (*.apk);;所有文件 (*.*)")
        if path:
            self.app_path_edit.setText(path)

    def _install_app(self) -> None:
        device_id = self._current_device_id()
        if not device_id:
            return

        app_path = self.app_path_edit.text().strip()
        if not app_path or not Path(app_path).is_file() or Path(app_path).suffix.lower() != ".apk":
            self._log("ERROR", "请先选择 APK 文件")
            return

        answer = QMessageBox.question(
            self,
            "安装确认",
            f"将在设备 {device_id} 上覆盖安装：\n{app_path}\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._log("INFO", f"开始安装 App：{app_path}")
        self._run_adb_action("安装 App", lambda: self.adb_client.install_app(device_id, app_path))

    def _current_test_mode(self) -> str:
        checked = self.mode_group.checkedButton()
        return checked.text() if checked else "单主"

    def _selected_lte_test_items(self) -> list[str]:
        return [
            name
            for name, checkbox in self.lte_test_item_checkboxes.items()
            if checkbox.isChecked()
        ]

    @staticmethod
    def _expand_selection_channels(raw_channels: object) -> list[int]:
        """展开信道列表，兼容逗号分隔字符串输入。"""
        if raw_channels is None:
            return []

        if isinstance(raw_channels, str):
            candidates = [part.strip() for part in raw_channels.replace("，", ",").split(",")]
        else:
            try:
                iterable = list(raw_channels)  # type: ignore[arg-type]
            except TypeError:
                iterable = [raw_channels]
            candidates = []
            for item in iterable:
                if isinstance(item, str):
                    candidates.extend(
                        part.strip()
                        for part in item.replace("，", ",").split(",")
                    )
                else:
                    candidates.append(str(item).strip())

        channels: list[int] = []
        for item in candidates:
            if not item:
                continue
            channels.append(int(float(item)))
        return channels

    def collect_lte_config(self) -> LteTestConfig:
        selected_bands = [
            f"B{band}" for band, checkbox in self.band_checkboxes.items() if checkbox.isChecked()
        ]
        data: list[dict[str, str | int | float]] = []
        if self.lte_channel_manager.has_config():
            for band in selected_bands:
                try:
                    selections = self.lte_channel_manager.get_band_test_selections(
                        band, self._selected_lte_test_items()
                    )
                except (KeyError, ValueError):
                    continue
                for test_item_name, selection in selections:
                    for channel in self._expand_selection_channels(selection.channels):
                        data.append(
                            {
                                "band": band,
                                "channel": channel,
                                "bw": selection.bw,
                                "loss_db": selection.loss_db,
                                "desc": test_item_name,
                            }
                        )

        return LteTestConfig(
            cable_loss=self.cable_loss_spin.value(),
            sensitivity_upper=self.sensitivity_upper_spin.value(),
            start_level=self.start_level_spin.value(),
            stop_level=self.stop_level_spin.value(),
            packet_count=self.packet_count_spin.value(),
            max_step=self.max_step_spin.value(),
            min_step=self.min_step_spin.value(),
            bler_threshold=self.bler_threshold_spin.value(),
            settle_time=self.settle_time_spin.value(),
            retry_count=self.retry_count_spin.value(),
            selected_bands=selected_bands,
            selected_channel_types=[],
            custom_channels=[],
            lte_test_items=self._selected_lte_test_items(),
            test_mode=self._current_test_mode(),
            data=data,
        )

    def _validate_lte_channel_config(self, config: LteTestConfig) -> bool:
        if config.start_level <= config.stop_level:
            QMessageBox.warning(self, "参数错误", "初始电平必须高于结束电平（例如 -70 > -120 dBm）")
            return False
        if config.max_step < config.min_step:
            QMessageBox.warning(self, "参数错误", "最大步长不能小于最小步长")
            return False
        if config.cable_loss < 0:
            QMessageBox.warning(self, "参数错误", "全局线损不能为负数")
            return False
        for row in config.data:
            bandwidth = float(row.get("bw", 0.0))
            channel_loss = float(row.get("loss_db", 0.0))
            if bandwidth <= 0:
                QMessageBox.warning(self, "参数错误", f"{row.get('band', '')} 带宽必须大于 0 MHz")
                return False
            if channel_loss < 0:
                QMessageBox.warning(self, "参数错误", f"{row.get('band', '')} Excel 线损不能为负数")
                return False

        if not config.selected_bands:
            QMessageBox.warning(self, "提示", "请至少选择一个 Band")
            return False

        if not self.lte_channel_manager.has_config():
            QMessageBox.warning(self, "提示", "LTE 信道配置未加载，请检查配置文件")
            return False

        for band in config.selected_bands:
            try:
                self.lte_channel_manager.get_band_config(band)
            except KeyError:
                message = f"未找到 Band 配置：{band}"
                self._log("ERROR", message)
                QMessageBox.warning(self, "提示", message)
                return False

            try:
                selections = self.lte_channel_manager.get_band_test_selections(
                    band, config.lte_test_items
                )
            except ValueError as exc:
                self._log("ERROR", str(exc))
                QMessageBox.warning(self, "提示", str(exc))
                return False

            if not selections:
                message = (
                    f"{band} 未配置任何测试信道，"
                    "请检查 Excel「固定信道」列或勾选测试项"
                )
                self._log("ERROR", message)
                QMessageBox.warning(self, "提示", message)
                return False

        if self.instrument_mode_combo.currentText() == "Real CMW500":
            operator = self.operator_edit.text().strip()
            dut_serial = self.dut_serial_edit.text().strip()
            calibration_id = self.calibration_id_edit.text().strip()
            calibration_due_text = self.calibration_due_date_edit.text().strip()
            if not operator or not dut_serial:
                QMessageBox.warning(
                    self,
                    "追溯信息缺失",
                    "Real CMW500 正式测试必须填写测试人员和 DUT 标识",
                )
                return False
            if not calibration_id or not calibration_due_text:
                QMessageBox.warning(
                    self,
                    "校准信息缺失",
                    "Real CMW500 正式测试必须填写校准标识和校准有效期",
                )
                return False
            try:
                calibration_due = date.fromisoformat(calibration_due_text)
            except ValueError:
                QMessageBox.warning(self, "校准信息错误", "校准有效期必须使用 YYYY-MM-DD 格式")
                return False
            if calibration_due < date.today():
                QMessageBox.warning(
                    self,
                    "校准已过期",
                    f"仪表校准有效期 {calibration_due_text} 已过期，禁止开始正式测试",
                )
                return False
            if not self.scpi_template_manager or not self.scpi_template_manager.has_template():
                QMessageBox.warning(self, "配置缺失", "Real CMW500 测试必须加载经过审核的 SCPI 模板")
                return False
            try:
                self.scpi_template_manager.validate_for_real_run()
            except ValueError as exc:
                self._log("ERROR", f"SCPI 模板预检失败：{exc}")
                QMessageBox.warning(self, "SCPI 模板预检失败", str(exc))
                return False

        return True

    def _log_test_channel_summary(self, config: LteTestConfig) -> None:
        self._log("INFO", "======== 本次测试信道信息 ========")
        optional_items = config.lte_test_items
        if optional_items:
            self._log("INFO", f"已勾选测试项：{', '.join(optional_items)}")
        else:
            self._log("INFO", "已勾选测试项：无（仅使用 Excel 固定信道）")

        for band in config.selected_bands:
            self._log("INFO", f"--- {band} ---")
            fixed = self.lte_channel_manager.get_fixed_channel_selection(band)
            if fixed is not None:
                self._log(
                    "INFO",
                    f"  固定信道: bw={fixed.bw:g} MHz, channels={fixed.channels}",
                )
            else:
                self._log("INFO", "  固定信道: 未配置")

            for test_item in optional_items:
                selection = self.lte_channel_manager.get_channels_for_test_item(
                    band, test_item
                )
                self._log(
                    "INFO",
                    f"  {test_item}: bw={selection.bw:g} MHz, channels={selection.channels}",
                )

        self._log("INFO", "==================================")

    def _start_test(self) -> None:
        if self._test_running:
            self._log("WARNING", "测试正在运行中")
            return
        if self.requires_unsafe_exit_acknowledgement():
            self._log("ERROR", "上一次测试的安全清理尚未人工确认，禁止开始新测试")
            QMessageBox.warning(
                self,
                "安全处置待确认",
                "上一次测试未能确认 Cell OFF/Cleanup。请先人工确认仪表 RF/Cell OFF "
                "状态并重新打开程序，当前会话不能开始新测试。",
            )
            return
        if self._background_action_running():
            self._log("WARNING", "后台设备操作尚未完成，不能开始测试")
            return

        config = self.collect_lte_config()
        if not self._validate_lte_channel_config(config):
            return

        if self.instrument_mode_combo.currentText() == "Fake":
            answer = QMessageBox.warning(
                self,
                "模拟测试确认",
                "当前为 Fake 模拟模式，结果不能作为正式实测报告。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self._log_test_channel_summary(config)

        instrument = self._prepare_instrument_for_test()
        if not instrument:
            return

        clear_trace = getattr(instrument, "clear_command_trace", None)
        if clear_trace:
            clear_trace()
        clear_cancel = getattr(instrument, "clear_cancel", None)
        if clear_cancel:
            clear_cancel()
        self.current_run = self._build_run_metadata(config, instrument)
        self._active_run_instrument = instrument
        self._worker_final_status = "RUNNING"
        self._run_finalized = False
        if self._run_started_callback:
            self._run_started_callback(dict(self.current_run))

        self.worker_thread = QThread(self)
        self.worker = TestWorker(
            config,
            self.lte_channel_manager,
            instrument,
            run_id=self.current_run["run_id"],
        )
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.log_signal.connect(self._log)
        self.worker.row_signal.connect(self._handle_worker_row)
        self.worker.summary_signal.connect(self._handle_worker_summary)
        self.worker.finished_signal.connect(self.on_test_finished)
        self.worker.finished_signal.connect(self.worker.deleteLater)
        self.worker.finished_signal.connect(
            self.worker_thread.quit,
            Qt.ConnectionType.DirectConnection,
        )
        self.worker.state_signal.connect(
            self._capture_worker_state,
            Qt.ConnectionType.DirectConnection,
        )
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self._set_test_buttons_running()
        self._log("INFO", f"测试开始时使用的仪表模式：{self.instrument_mode}")
        if isinstance(instrument, RealCMW500):
            if self.scpi_template_manager and self.scpi_template_manager.has_template():
                self._log("INFO", "使用 CMW500 SCPI 模板执行 LTE 测试")
        self._log("INFO", "开始测试")
        self.worker_thread.start()

    def _toggle_pause(self) -> None:
        if not self.worker or not self._test_running or not self.pause_button:
            return

        self._pause_state = not self._pause_state
        if self._pause_state:
            self.worker.pause()
            self.pause_button.setText("继续测试")
            self._log("INFO", "测试已暂停")
        else:
            self.worker.resume()
            self.pause_button.setText("暂停测试")
            self._log("INFO", "测试继续")

    def _stop_test(self) -> None:
        if not self.worker or not self._test_running:
            return
        self.worker.stop()
        if self.pause_button:
            self.pause_button.setEnabled(False)
        if self.stop_button:
            self.stop_button.setEnabled(False)
        self._log("INFO", "请求停止测试")

    def _adb_reboot(self) -> None:
        device_id = self._current_device_id()
        if not device_id:
            return
        answer = QMessageBox.question(
            self,
            "重启确认",
            f"确定重启设备 {device_id}？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._run_adb_action("重启设备", lambda: self.adb_client.reboot(device_id))

    def _adb_stop_app(self) -> None:
        device_id = self._current_device_id()
        package_name = self._package_name()
        if not device_id or not package_name:
            return
        self._run_adb_action("停止App", lambda: self.adb_client.stop_app(device_id, package_name))

    def _adb_start_app(self) -> None:
        device_id = self._current_device_id()
        package_name = self._package_name()
        if not device_id or not package_name:
            return
        self._run_adb_action("启动App", lambda: self.adb_client.start_app(device_id, package_name))

    def _adb_clear_app_data(self) -> None:
        device_id = self._current_device_id()
        package_name = self._package_name()
        if not device_id or not package_name:
            return
        answer = QMessageBox.warning(
            self,
            "清除数据确认",
            f"将永久清除设备 {device_id} 上 {package_name} 的全部数据。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._run_adb_action(
                "清除数据",
                lambda: self.adb_client.clear_app_data(device_id, package_name),
            )

    def _adb_screenshot(self) -> None:
        device_id = self._current_device_id()
        if not device_id:
            return
        screenshot_dir = ensure_user_data_dir() / "screenshots"
        self._run_adb_action(
            "截图",
            lambda: self.adb_client.screenshot(device_id, str(screenshot_dir)),
        )

    def on_test_finished(self) -> None:
        self._finalize_test_run()
        thread = self.worker_thread
        if thread and thread.isRunning() and not thread.wait(5000):
            self._log("ERROR", "测试工作线程未能在 5 秒内退出")
            return
        self.worker = None
        self.worker_thread = None

    def _capture_worker_state(self, state: str) -> None:
        # This slot is deliberately safe for DirectConnection from the worker thread:
        # it only replaces simple Python state and never touches a Qt widget.
        self._worker_final_status = str(state)
        if self._worker_final_status == "FAILED_UNSAFE":
            # Latch across subsequent state changes/runs until explicit operator action.
            self._unsafe_exit_pending = True

    def _finalize_test_run(self) -> None:
        if self._run_finalized:
            return
        self._run_finalized = True
        final_status = self._worker_final_status
        if final_status not in {"COMPLETED", "STOPPED", "FAILED", "FAILED_UNSAFE"}:
            final_status = "FAILED"
        self.current_run["status"] = final_status
        self.current_run["end_time"] = datetime.now().astimezone().isoformat(timespec="seconds")
        trace = getattr(self._active_run_instrument, "command_trace", None)
        if isinstance(trace, list):
            self.current_run["command_trace"] = list(trace)
        self._restore_test_buttons()
        if self._finished_callback:
            self._finished_callback(dict(self.current_run))
        self._active_run_instrument = None
        if isinstance(self.instrument, RealCMW500) and self.instrument_idn:
            self.instrument_status_label.setText("身份已验证（测试时自动连接）")
        elif isinstance(self.instrument, FakeCMW500):
            self.instrument_status_label.setText("Fake 已就绪")
        self._log("INFO", "测试任务已结束")

    def _build_run_metadata(self, config: LteTestConfig, instrument: InstrumentBase) -> dict:
        channel_path = Path(self.lte_channel_manager.path)
        template_path = Path(self.scpi_template_file_edit.text().strip()) if self.scpi_template_file_edit.text().strip() else None
        apk_path = Path(self.app_path_edit.text().strip()) if self.app_path_edit.text().strip() else None
        mode = "SIMULATION" if bool(getattr(instrument, "is_simulation", False)) else "REAL"
        return {
            "run_id": uuid.uuid4().hex,
            "start_time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "end_time": "",
            "status": "RUNNING",
            "data_source": mode,
            "instrument_mode": self.instrument_mode,
            "instrument_idn": self.instrument_idn or instrument.query_idn(),
            "connection": self._connection_snapshot(mode, instrument),
            "device_id": self.device_combo.currentText().strip(),
            "dut_serial": self.dut_serial_edit.text().strip(),
            "operator": self.operator_edit.text().strip(),
            "package_name": self.package_name_edit.text().strip(),
            "apk_path": str(apk_path) if apk_path else "",
            "apk_sha256": self._file_sha256(apk_path),
            "instrument_calibration_id": self.calibration_id_edit.text().strip(),
            "instrument_calibration_due_date": self.calibration_due_date_edit.text().strip(),
            "software_version": APP_VERSION,
            "build_commit": APP_BUILD_COMMIT,
            "build_time": APP_BUILD_TIME,
            "build_dirty": APP_BUILD_DIRTY,
            "channel_config_path": str(channel_path),
            "channel_config_sha256": self._file_sha256(channel_path),
            "scpi_template_path": str(template_path) if template_path else "",
            "scpi_template_sha256": self._file_sha256(template_path),
            "config_snapshot": asdict(config),
            "command_trace": [],
        }

    def _connection_snapshot(
        self,
        mode: str,
        instrument: InstrumentBase,
    ) -> dict[str, object]:
        if mode == "SIMULATION":
            return {"type": "FAKE"}
        if self.connection_type_combo.currentText() == "VISA（推荐）":
            connection: dict[str, object] = {
                "type": "VISA",
                "resource": self.visa_resource_edit.text().strip(),
                "timeout_ms": self.visa_timeout_spin.value(),
            }
            transport = getattr(instrument, "transport", None)
            backend = str(getattr(transport, "backend", "")).strip()
            if backend:
                connection["backend"] = backend
            return connection
        return {
            "type": "SOCKET",
            "host": self.instrument_host_edit.text().strip(),
            "port": self.instrument_port_spin.value(),
            "timeout_ms": self.instrument_timeout_spin.value(),
        }

    @staticmethod
    def _file_sha256(path: Path | None) -> str:
        if path is None or not path.is_file():
            return ""
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _handle_worker_row(self, result: object) -> None:
        if self._add_row_callback:
            self._add_row_callback(result)

    def _handle_worker_summary(self, summary: dict) -> None:
        if self._update_summary_callback:
            self._update_summary_callback(summary)

    def _set_test_buttons_running(self) -> None:
        self._test_running = True
        self._pause_state = False
        for widget in self.test_sensitive_widgets:
            widget.setEnabled(False)
        if self.start_button:
            self.start_button.setEnabled(False)
        if self.pause_button:
            self.pause_button.setEnabled(True)
            self.pause_button.setText("暂停测试")
        if self.stop_button:
            self.stop_button.setEnabled(True)

    def _restore_test_buttons(self) -> None:
        self._test_running = False
        self._pause_state = False
        for widget in self.test_sensitive_widgets:
            widget.setEnabled(True)
        if self.start_button:
            self.start_button.setEnabled(True)
        if self.pause_button:
            self.pause_button.setEnabled(False)
            self.pause_button.setText("暂停测试")
        if self.stop_button:
            self.stop_button.setEnabled(False)

    def is_test_running(self) -> bool:
        return self._test_running or bool(self.worker_thread and self.worker_thread.isRunning())

    def requires_unsafe_exit_acknowledgement(self) -> bool:
        return self._unsafe_exit_pending

    def acknowledge_unsafe_exit(self) -> None:
        if not self._unsafe_exit_pending:
            return
        self._unsafe_exit_pending = False
        self._log("WARNING", "操作员已确认人工完成 RF/Cell OFF 安全处置，允许退出")

    def shutdown(self, timeout_ms: int = 15000) -> bool:
        thread = self.worker_thread
        if self.worker and thread and thread.isRunning():
            self.worker.stop()
            # quit() is thread-safe and lets wait() complete after worker.run() returns,
            # even though the UI event loop is blocked inside closeEvent.
            thread.quit()
            if not thread.wait(timeout_ms):
                return False
        if self._test_running:
            self._finalize_test_run()
        self.worker = None
        self.worker_thread = None
        for thread, _worker, _callback in list(self.instrument_action_tasks.values()):
            thread.quit()
            if thread.isRunning() and not thread.wait(min(timeout_ms, 3000)):
                return False
        if self.instrument:
            try:
                self.instrument.disconnect()
            except Exception as exc:
                self._log("ERROR", f"退出时仪表断开异常：{exc}")
                return False
        if self.requires_unsafe_exit_acknowledgement():
            self._log(
                "ERROR",
                "测试安全清理失败：退出已阻止，必须先人工确认 RF/Cell OFF 状态",
            )
            return False
        return True

    def _prepare_instrument_for_test(self) -> InstrumentBase | None:
        mode = self.instrument_mode_combo.currentText()
        self.instrument_mode = mode
        if mode == "Fake":
            if not isinstance(self.instrument, FakeCMW500):
                self.instrument = FakeCMW500()
            if not self.instrument.is_connected():
                self.instrument.connect()
                self.instrument_status_label.setText("Fake 已连接")
                self._log("INFO", "Fake CMW500 已连接")
            self.instrument_idn = self.instrument.query_idn()
            return self.instrument

        if not isinstance(self.instrument, RealCMW500) or not self.instrument_idn:
            self._log("ERROR", "请先完成 Real CMW500 身份验证")
            return None
        return self.instrument

    def _auto_select_configured_bands(self, supported_bands: list[str]) -> list[str]:
        checked_bands: list[str] = []
        for band in supported_bands:
            try:
                band_number = int(band.replace("B", ""))
            except ValueError:
                continue
            checkbox = self.band_checkboxes.get(band_number)
            if checkbox:
                checkbox.setChecked(True)
                checked_bands.append(band)
        return checked_bands

    def _current_device_id(self) -> str:
        device_id = self.device_combo.currentText().strip()
        if not device_id:
            self._log("ERROR", "请先选择设备序列号")
        return device_id

    def _package_name(self) -> str:
        package_name = self.package_name_edit.text().strip()
        if not package_name:
            self._log("ERROR", "请先填写 App 包名")
        elif not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", package_name):
            self._log("ERROR", "App 包名格式无效")
            return ""
        return package_name

    def _run_adb_action(
        self,
        action_text: str,
        action: Callable[[], tuple[bool, str]],
    ) -> None:
        def background_action() -> tuple[bool, str, object | None]:
            success, message = action()
            return success, message, None

        def finished(success: bool, message: str, _payload: object | None) -> None:
            self._log_adb_result(success, action_text, message)

        self._run_instrument_action(background_action, finished)

    def _log_adb_result(self, success: bool, action_text: str, message: str) -> None:
        level = "INFO" if success else "ERROR"
        output = message.strip() if message else "命令执行成功"
        self._log(level, f"执行ADB操作：{action_text}，{output}")
