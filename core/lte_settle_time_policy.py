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


def _replace_form_widget(form, old, new) -> None:
    """Replace a field while preserving all rows inserted by earlier LTE policies."""
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
    # This calls the already-patched LTE V1 group builder first, so FAST packet,
    # PUSCH open-loop and PUSCH closed-loop controls are created before we touch
    # the settle-time row.
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

    # Defensive visibility assertions: these controls are required LTE V1 UI.
    for name in (
        "fast_packet_count_spin",
        "pusch_open_loop_nom_power_spin",
        "pusch_closed_loop_target_power_spin",
    ):
        widget = getattr(self, name, None)
        if widget is not None:
            widget.setVisible(True)
            if hasattr(form, "labelForField"):
                label = form.labelForField(widget)
                if label is not None:
                    label.setVisible(True)
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
