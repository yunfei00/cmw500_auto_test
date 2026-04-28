from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QThread
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
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core.channel_config import ChannelConfigManager
from core.models import LteTestConfig
from core.test_worker import TestWorker


LogCallback = Callable[[str, str], None]
AddRowCallback = Callable[[object], None]
UpdateSummaryCallback = Callable[[dict], None]
FinishedCallback = Callable[[], None]


class LeftPanel(QScrollArea):
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

        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setMinimumWidth(380)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(self._create_standard_group())
        layout.addWidget(self._create_file_group())
        layout.addWidget(self._create_phone_group())
        layout.addWidget(self._create_scene_group())
        layout.addWidget(self._create_control_group())
        layout.addWidget(self._create_adb_group())
        layout.addStretch(1)

        self.setWidget(container)

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

        self._add_file_row(layout, 0, "信道配置文件", self.channel_file_edit)
        self._add_file_row(layout, 1, "串口配置文件", self.serial_file_edit)
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
            ("刷新设备", "刷新设备"),
            ("重启", "重启设备"),
            ("停止App", "停止App"),
            ("启动App", "启动App"),
            ("清除数据", "清除数据"),
            ("截图", "截图"),
        ]
        for index, (button_text, action_text) in enumerate(actions):
            button = QPushButton(button_text)
            button.clicked.connect(lambda checked=False, text=action_text: self._adb_action(text))
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

    def _refresh_devices(self) -> None:
        self.device_combo.clear()
        self.device_combo.addItems(["device_001", "device_002"])
        self._log("INFO", "已刷新设备列表：device_001, device_002")

    def _browse_app(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 App 安装包", "", "Android Package (*.apk);;所有文件 (*.*)")
        if path:
            self.app_path_edit.setText(path)

    def _install_app(self) -> None:
        app_path = self.app_path_edit.text().strip() or "未选择 App"
        self._log("INFO", f"开始安装 App：{app_path}")

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
        self.worker_thread = QThread(self)
        self.worker = TestWorker(config, self.channel_manager)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.log_signal.connect(self._log)
        self.worker.row_signal.connect(self._handle_worker_row)
        self.worker.summary_signal.connect(self._handle_worker_summary)
        self.worker.finished_signal.connect(self.on_test_finished)
        self.worker.finished_signal.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)

        self._set_test_buttons_running()
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

    def _adb_action(self, action_text: str) -> None:
        self._log("INFO", f"执行ADB操作：{action_text}")

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
