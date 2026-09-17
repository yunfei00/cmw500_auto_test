from __future__ import annotations

"""Allow sub-second LTE settle time values without regressing LTE V1 UI policy."""

from PySide6.QtWidgets import QDoubleSpinBox

from ui.left_panel import LeftPanel


DEFAULT_SETTLE_TIME = 0.1
_original_create_lte_instrument_group = LeftPanel._create_lte_instrument_group
_original_collect_lte_config = LeftPanel.collect_lte_config


def _hide_legacy_field(form, widget) -> None:
    widget.setVisible(False)
    if hasattr(form, "labelForField"):
        label = form.labelForField(widget)
        if label is not None:
            label.setVisible(False)


def _ensure_form_row(form, label_text: str, widget) -> None:
    """Ensure a required LTE control has an actual QFormLayout row."""
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


def _create_lte_instrument_group_with_fractional_settle(self: LeftPanel):
    group = _original_create_lte_instrument_group(self)
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

    # These four rows are part of the current LTE operator contract.  Merely
    # setting a widget visible is insufficient if an earlier layout operation
    # removed its row, so explicitly restore missing rows.
    required_rows = (
        ("快速测试包个数：", "fast_packet_count_spin"),
        ("PUSCH开环标称功率：", "pusch_open_loop_nom_power_spin"),
        ("PUSCH闭环目标功率：", "pusch_closed_loop_target_power_spin"),
    )
    for label_text, name in required_rows:
        widget = getattr(self, name, None)
        if widget is not None:
            _ensure_form_row(form, label_text, widget)
    return group


def _collect_lte_config_with_fractional_settle(self: LeftPanel):
    config = _original_collect_lte_config(self)
    config.settle_time = float(self.settle_time_spin.value())
    self.settings.setValue("lte/settle_time", config.settle_time)
    self.settings.sync()
    return config


def apply_lte_settle_time_policy() -> None:
    if getattr(LeftPanel, "_lte_settle_time_policy_applied", False):
        return
    LeftPanel._create_lte_instrument_group = _create_lte_instrument_group_with_fractional_settle
    LeftPanel.collect_lte_config = _collect_lte_config_with_fractional_settle
    LeftPanel._lte_settle_time_policy_applied = True
