from __future__ import annotations

"""Allow sub-second LTE settle time values without bypassing LTE UI policies."""

from PySide6.QtWidgets import QDoubleSpinBox

from ui.left_panel import LeftPanel


DEFAULT_SETTLE_TIME = 0.1


def _hide_legacy_field(form, widget) -> None:
    widget.setVisible(False)
    if hasattr(form, "labelForField"):
        label = form.labelForField(widget)
        if label is not None:
            label.setVisible(False)


def _ensure_form_row(form, label_text: str, widget) -> None:
    row = -1
    if hasattr(form, "getWidgetPosition"):
        row, _role = form.getWidgetPosition(widget)
    if row < 0:
        form.addRow(label_text, widget)
    widget.setVisible(True)
    if hasattr(form, "labelForField"):
        label = form.labelForField(widget)
        if label is not None:
            label.setVisible(True)


def _replace_form_widget(form, old, new) -> None:
    label = form.labelForField(old) if hasattr(form, "labelForField") else None
    if hasattr(form, "getWidgetPosition") and hasattr(form, "removeRow"):
        row, _role = form.getWidgetPosition(old)
        if row >= 0:
            label_text = label.text() if label is not None else "稳定等待时间："
            form.removeRow(row)
            form.insertRow(row, label_text, new)
            return
    if hasattr(form, "replaceWidget"):
        form.replaceWidget(old, new)
        old.hide()
        old.deleteLater()


def apply_lte_settle_time_policy() -> None:
    if getattr(LeftPanel, "_lte_settle_time_policy_applied", False):
        return

    # Capture at APPLY time. main.py applies fast-scan first, so these methods
    # already contain the fast-packet and PUSCH controls. Import-time capture
    # bypassed that wrapper and caused those controls to disappear.
    previous_create = LeftPanel._create_lte_instrument_group
    previous_collect = LeftPanel.collect_lte_config

    def create_with_fractional_settle(self: LeftPanel):
        group = previous_create(self)
        form = group.layout()

        _hide_legacy_field(form, self.sensitivity_upper_spin)
        _hide_legacy_field(form, self.stop_level_spin)

        old = self.settle_time_spin
        settle = QDoubleSpinBox()
        settle.setRange(0.0, 3600.0)
        settle.setDecimals(2)
        settle.setSingleStep(0.1)
        settle.setSuffix(" s")
        settle.setKeyboardTracking(False)
        saved = self.settings.value("lte/settle_time", DEFAULT_SETTLE_TIME, float)
        settle.setValue(float(saved))
        _replace_form_widget(form, old, settle)
        self.settle_time_spin = settle

        required_rows = (
            ("快速测试包个数：", "fast_packet_count_spin"),
            ("PUSCH开环标称功率：", "pusch_open_loop_nom_power_spin"),
            ("PUSCH闭环目标功率：", "pusch_closed_loop_target_power_spin"),
        )
        for label_text, name in required_rows:
            widget = getattr(self, name, None)
            if widget is None:
                raise RuntimeError(f"LTE 必需控件未创建：{name}")
            _ensure_form_row(form, label_text, widget)
        return group

    def collect_with_fractional_settle(self: LeftPanel):
        config = previous_collect(self)
        config.settle_time = float(self.settle_time_spin.value())
        self.settings.setValue("lte/settle_time", config.settle_time)
        self.settings.sync()
        return config

    LeftPanel._create_lte_instrument_group = create_with_fractional_settle
    LeftPanel.collect_lte_config = collect_with_fractional_settle
    LeftPanel._lte_settle_time_policy_applied = True
