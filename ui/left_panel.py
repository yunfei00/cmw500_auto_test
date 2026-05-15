from __future__ import annotations

from collections.abc import Callable

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
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.channel_config import ChannelConfigManager
from core.fake_cmw500 import FakeCMW500
from core.models import LteTestConfig
from core.scpi_template import ScpiTemplateManager
from core.serial_config import SerialConfigManager
from core.test_worker import TestWorker
from devices.adb_client import AdbClient
from devices.cmw500_controller import RealCMW500
from devices.instrument_base import InstrumentBase
from devices.instrument_transport import SocketTransport, VisaTransport


LogCallback = Callable[[str, str], None]
AddRowCallback = Callable[[object], None]
UpdateSummaryCallback = Callable[[dict], None]
FinishedCallback = Callable[[], None]
InstrumentAction = Callable[[], tuple[bool, str, object | None]]
InstrumentActionCallback = Callable[[bool, str, object | None], None]


class InstrumentActionWorker(QObject):
    finished_signal = Signal(bool, str, object)

    def __init__(self, action: InstrumentAction) -> None:
        super().__init__()
        self.action = action

    def run(self) -> None:
        try:
            success, message, payload = self.action()
        except Exception as exc:
            success, message, payload = False, str(exc), None
        self.finished_signal.emit(success, message, payload)


class LeftPanel(QScrollArea):
    SETTINGS_ORG = "cmw500_tool"
    SETTINGS_APP = "cmw500_auto_test"
    LAST_VISA_RESOURCE_KEY = "instrument/last_visa_resource"

    def __init__(self) -> None:
        super().__init__()
        self._logger: LogCallback | None = None
        self._add_row_callback: AddRowCallback | None = None
        self._update_summary_callback: UpdateSummaryCallback | None = None
        self._finished_callback: FinishedCallback | None = None
        self._pause_state = False

        self.worker_thread: QThread | None = None
        self.worker: TestWorker | None = None
        self.channel_manager = ChannelConfigManager()
        self.serial_config_manager = SerialConfigManager()
        self.scpi_template_manager: ScpiTemplateManager | None = None
        self.adb_client = AdbClient()
        self.instrument: InstrumentBase | None = None
        self.instrument_mode = "Fake"
        self.instrument_action_tasks: list[tuple[QThread, InstrumentActionWorker]] = []
        self._test_running = False
        self.band_checkboxes: dict[int, QCheckBox] = {}
        self.channel_type_checkboxes: dict[str, QCheckBox] = {}
        self.device_combo = QComboBox()
        self.app_path_edit = QLineEdit()
        self.package_name_edit = QLineEdit()
        self.custom_channel_edit = QLineEdit()
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

        layout.addWidget(self._create_standard_group())
        layout.addWidget(self._create_instrument_connection_group())
        layout.addWidget(self._create_file_group())
        layout.addWidget(self._create_phone_group())
        layout.addWidget(self._create_scene_group())
        layout.addWidget(self._create_control_group())
        layout.addWidget(self._create_adb_group())
        layout.addStretch(1)

        self.setWidget(container)
        self._restore_last_instrument_resource()

    def set_logger(self, logger: LogCallback) -> None:
        self._logger = logger

    def set_add_row_callback(self, callback: AddRowCallback) -> None:
        self._add_row_callback = callback

    def set_update_summary_callback(self, callback: UpdateSummaryCallback) -> None:
        self._update_summary_callback = callback

    def set_finished_callback(self, callback: FinishedCallback) -> None:
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

        self.cable_loss_spin = self._double_spin(0.0, " dB", -200.0, 200.0)
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
        group = QGroupBox("测试信道选择")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 14, 8, 8)

        grid = QGridLayout()
        names = ["Top频点", "高频点", "中频点", "低频点", "自定义频点"]
        for index, name in enumerate(names):
            checkbox = QCheckBox(name)
            checkbox.setChecked(name in {"高频点", "中频点", "低频点"})
            self.channel_type_checkboxes[name] = checkbox
            grid.addWidget(checkbox, index // 2, index % 2)

        self.custom_channel_edit.setPlaceholderText("例如：1300,1575,1850")

        layout.addLayout(grid)
        layout.addWidget(self.custom_channel_edit)
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
        self.connection_type_combo.addItems(["VISA（推荐）", "SOCKET", "SERIAL（预留）", "USBTMC（预留）"])
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

        form.addRow("仪表模式：", self.instrument_mode_combo)
        form.addRow("连接方式：", self.connection_type_combo)
        self.transport_stack = QStackedWidget()
        self.transport_stack.addWidget(self._create_visa_form_widget())
        self.transport_stack.addWidget(self._create_socket_form_widget())
        self.transport_stack.addWidget(QLabel("SERIAL 模式预留（暂不可用）"))
        self.transport_stack.addWidget(QLabel("USBTMC 模式预留（暂不可用）"))
        form.addRow("连接参数：", self.transport_stack)
        form.addRow("状态：", self.instrument_status_label)
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
        self._add_file_row(layout, 2, "CMW500命令配置文件", self.scpi_template_file_edit)
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

        layout.addLayout(device_layout)
        layout.addLayout(app_layout)
        layout.addLayout(mode_layout)
        return group

    def _create_scene_group(self) -> QGroupBox:
        group = QGroupBox("测试场景选择")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(8)

        item_layout = QHBoxLayout()
        item_layout.addWidget(QLabel("测试项："))
        for name in ["LTE", "WiFi", "WCDMA", "GSM"]:
            checkbox = QCheckBox(name)
            checkbox.setChecked(name == "LTE")
            item_layout.addWidget(checkbox)
        item_layout.addStretch(1)

        strategy_layout = QHBoxLayout()
        strategy_layout.addWidget(QLabel("测试策略："))
        self.fast_radio = QRadioButton("快速测试")
        self.standard_radio = QRadioButton("标准测试")
        self.full_radio = QRadioButton("全量测试")
        self.standard_radio.setChecked(True)
        self.strategy_group = QButtonGroup(self)
        for radio in (self.fast_radio, self.standard_radio, self.full_radio):
            self.strategy_group.addButton(radio)
            strategy_layout.addWidget(radio)
        strategy_layout.addStretch(1)

        layout.addLayout(item_layout)
        layout.addLayout(strategy_layout)
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
        elif label_text == "CMW500命令配置文件":
            path, _ = QFileDialog.getOpenFileName(
                self,
                "选择 CMW500 命令配置文件",
                "",
                "SCPI 模板文件 (*.yaml *.yml *.json);;所有文件 (*.*)",
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
            self._load_channel_config_file(path)
            return
        if label_text == "串口配置文件":
            self._load_serial_config_file(path)
            return
        if label_text == "CMW500命令配置文件":
            self._load_scpi_template_file(path)
            return
        display_path = path.strip() or "未选择文件"
        self._log("INFO", f"已加载 {label_text} 配置文件：{display_path}")

    def _load_channel_config_file(self, path: str) -> None:
        config_path = path.strip()
        if not config_path:
            self._log("ERROR", "请选择信道配置文件")
            return

        try:
            self.channel_manager.load_excel(config_path)
        except Exception as exc:
            self._log("ERROR", f"信道配置文件加载失败：{exc}")
            return

        supported_bands = self.channel_manager.get_supported_bands("LTE")
        self._log("INFO", f"已加载信道配置文件：{config_path}")
        self._log("INFO", f"LTE支持Band数量：{len(supported_bands)}")
        checked_bands = self._check_loaded_lte_bands(supported_bands)
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
        self.instrument_status_label.setText("未连接")
        self._log("INFO", f"仪表模式切换：{mode}")

    def _on_connection_type_changed(self, mode: str) -> None:
        index_map = {"VISA（推荐）": 0, "SOCKET": 1, "SERIAL（预留）": 2, "USBTMC（预留）": 3}
        self.transport_stack.setCurrentIndex(index_map.get(mode, 0))

    def _connect_instrument(self) -> None:
        mode = self.instrument_mode_combo.currentText()
        self.instrument_mode = mode
        if mode == "Fake":
            instrument = FakeCMW500()
            instrument.connect()
            self.instrument = instrument
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

        instrument = RealCMW500(transport)
        if self.scpi_template_manager:
            instrument.set_scpi_template_manager(self.scpi_template_manager)
        self.instrument_status_label.setText("连接中")

        def action() -> tuple[bool, str, object | None]:
            instrument.connect()
            idn = instrument.query("*IDN?")
            return True, f"Real CMW500 已连接：{desc}，*IDN? -> {idn}", instrument

        def on_finished(success: bool, message: str, payload: object | None) -> None:
            if success and isinstance(payload, RealCMW500):
                self.instrument = payload
                self.instrument_status_label.setText("已连接")
                self._log("INFO", message)
                self._save_last_instrument_resource()
                if self.scpi_template_manager:
                    self._log("INFO", "已将 SCPI 模板绑定到 RealCMW500")
            else:
                self.instrument = None
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
        def action() -> tuple[bool, str, object | None]:
            try:
                import pyvisa
            except ImportError as exc:
                return False, f"缺少 pyvisa：{exc}", None
            rm = pyvisa.ResourceManager()
            try:
                resources = rm.list_resources()
                cmw_candidates: list[tuple[str, str]] = []
                for resource in resources:
                    try:
                        inst = rm.open_resource(resource)
                        try:
                            inst.timeout = min(self.visa_timeout_spin.value(), 2000)
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
        if self.instrument:
            try:
                self.instrument.disconnect()
            except Exception as exc:
                self._log("ERROR", f"仪表断开异常：{exc}")
        self.instrument = None
        self.instrument_status_label.setText("未连接")
        self._log("INFO", "仪表已断开")

    def _query_instrument_idn(self) -> None:
        if not self._instrument_connected():
            self._log("ERROR", "请先连接仪表")
            return

        instrument = self.instrument

        def action() -> tuple[bool, str, object | None]:
            if not instrument:
                return False, "请先连接仪表", None
            return True, instrument.query_idn(), None

        def on_finished(success: bool, message: str, payload: object | None) -> None:
            if success:
                self._log("INFO", f"IDN 返回：{message}")
            else:
                self._log("ERROR", f"查询 IDN 失败：{message}")

        self._run_instrument_action(action, on_finished)

    def _run_instrument_action(
        self,
        action: InstrumentAction,
        on_finished: InstrumentActionCallback,
    ) -> None:
        """执行仪表动作。

        这里使用同步执行，避免将 VISA/Socket 连接对象在 Qt 线程间传递，
        导致底层驱动对象线程归属异常并触发闪退。
        """
        try:
            success, message, payload = action()
        except Exception as exc:
            success, message, payload = False, str(exc), None
        on_finished(success, message, payload)

    def _instrument_connected(self) -> bool:
        if not self.instrument:
            return False
        try:
            return self.instrument.is_connected()
        except Exception:
            return False

    def _refresh_devices(self) -> None:
        devices = self.adb_client.list_devices()
        self.device_combo.clear()
        self.device_combo.addItems(devices)
        if devices:
            self._log("INFO", f"检测到 {len(devices)} 台设备")
        elif self.adb_client.last_error:
            self._log("ERROR", self.adb_client.last_error)
        else:
            self._log("WARNING", "未检测到 ADB 设备")

    def _browse_app(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 App 安装包", "", "Android Package (*.apk);;所有文件 (*.*)")
        if path:
            self.app_path_edit.setText(path)

    def _install_app(self) -> None:
        device_id = self._current_device_id()
        if not device_id:
            return

        app_path = self.app_path_edit.text().strip()
        if not app_path:
            self._log("ERROR", "请先选择 APK 文件")
            return

        self._log("INFO", f"开始安装 App：{app_path}")
        success, message = self.adb_client.install_app(device_id, app_path)
        self._log_adb_result(success, "安装 App", message)

    def _current_test_mode(self) -> str:
        checked = self.mode_group.checkedButton()
        return checked.text() if checked else "单主"

    def collect_lte_config(self) -> LteTestConfig:
        selected_bands = [
            f"B{band}" for band, checkbox in self.band_checkboxes.items() if checkbox.isChecked()
        ]
        selected_channel_types = [
            name for name, checkbox in self.channel_type_checkboxes.items() if checkbox.isChecked()
        ]

        custom_channels: list[int] = []
        raw_custom_channels = self.custom_channel_edit.text().strip()
        if raw_custom_channels:
            try:
                custom_channels = [
                    int(value.strip()) for value in raw_custom_channels.split(",") if value.strip()
                ]
            except ValueError:
                self._log("WARNING", "自定义频点格式错误，已忽略")

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
            selected_channel_types=selected_channel_types,
            custom_channels=custom_channels,
            test_mode=self._current_test_mode(),
        )

    def _start_test(self) -> None:
        if self._test_running:
            self._log("WARNING", "测试正在运行中")
            return

        config = self.collect_lte_config()
        instrument = self._prepare_instrument_for_test()
        if not instrument:
            return

        self.worker_thread = QThread(self)
        self.worker = TestWorker(config, self.channel_manager, instrument)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.log_signal.connect(self._log)
        self.worker.row_signal.connect(self._handle_worker_row)
        self.worker.summary_signal.connect(self._handle_worker_summary)
        self.worker.finished_signal.connect(self.on_test_finished)
        self.worker.finished_signal.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self._set_test_buttons_running()
        self._log("INFO", f"测试开始时使用的仪表模式：{self.instrument_mode}")
        if isinstance(instrument, RealCMW500):
            if self.scpi_template_manager and self.scpi_template_manager.has_template():
                self._log("INFO", "使用 CMW500 SCPI 模板执行 LTE 测试")
            else:
                self._log("WARNING", "未加载 CMW500 命令配置文件，RealCMW500 无法确认 UE Attach 状态")
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
        self._log("INFO", "请求停止测试")

    def _adb_reboot(self) -> None:
        device_id = self._current_device_id()
        if not device_id:
            return
        success, message = self.adb_client.reboot(device_id)
        self._log_adb_result(success, "重启设备", message)

    def _adb_stop_app(self) -> None:
        device_id = self._current_device_id()
        package_name = self._package_name()
        if not device_id or not package_name:
            return
        success, message = self.adb_client.stop_app(device_id, package_name)
        self._log_adb_result(success, "停止App", message)

    def _adb_start_app(self) -> None:
        device_id = self._current_device_id()
        package_name = self._package_name()
        if not device_id or not package_name:
            return
        success, message = self.adb_client.start_app(device_id, package_name)
        self._log_adb_result(success, "启动App", message)

    def _adb_clear_app_data(self) -> None:
        device_id = self._current_device_id()
        package_name = self._package_name()
        if not device_id or not package_name:
            return
        success, message = self.adb_client.clear_app_data(device_id, package_name)
        self._log_adb_result(success, "清除数据", message)

    def _adb_screenshot(self) -> None:
        device_id = self._current_device_id()
        if not device_id:
            return
        success, message = self.adb_client.screenshot(device_id, "data/screenshots")
        self._log_adb_result(success, "截图", message)

    def on_test_finished(self) -> None:
        self._restore_test_buttons()
        if self._finished_callback:
            self._finished_callback()
        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()
        self.worker = None
        self.worker_thread = None
        self._log("INFO", "测试任务已结束")

    def _handle_worker_row(self, result: object) -> None:
        if self._add_row_callback:
            self._add_row_callback(result)

    def _handle_worker_summary(self, summary: dict) -> None:
        if self._update_summary_callback:
            self._update_summary_callback(summary)

    def _set_test_buttons_running(self) -> None:
        self._test_running = True
        self._pause_state = False
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
        if self.start_button:
            self.start_button.setEnabled(True)
        if self.pause_button:
            self.pause_button.setEnabled(False)
            self.pause_button.setText("暂停测试")
        if self.stop_button:
            self.stop_button.setEnabled(False)

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
            return self.instrument

        if not self._instrument_connected():
            self._log("ERROR", "请先连接 Real CMW500")
            return None
        return self.instrument

    def _check_loaded_lte_bands(self, supported_bands: list[str]) -> list[str]:
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
        return package_name

    def _log_adb_result(self, success: bool, action_text: str, message: str) -> None:
        level = "INFO" if success else "ERROR"
        output = message.strip() if message else "命令执行成功"
        self._log(level, f"执行ADB操作：{action_text}，{output}")
