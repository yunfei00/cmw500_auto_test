from __future__ import annotations

"""Allow sub-second LTE settle time values without regressing LTE V1 UI policy."""

from PySide6.QtWidgets import QDoubleSpinBox

from ui.left_panel import LeftPanel


DEFAULT_SETTLE_TIME = 0.1
_original_create_lte_instrument_group = LeftPanel._create_lte_instrument_group
_original_collect_lte_config = LeftPanel.collect_lte_config


def _hide_legacy_field(form, widget) -> None:
    """Keep legacy fields available internally while removing them from operator UI."""
    widget.setVisible(False)
    if hasattr(form, "labelForField"):
        label = form.labelForField(widget)
        if label is not None:
            label.setVisible(False)


def _create_lte_instrument_group_with_fractional_settle(self: LeftPanel):
    group = _original_create_lte_instrument_group(self)
    form = group.layout()

    # Re-assert the LTE V1 UI contract after wrapping the instrument group.
    # These legacy controls must never reappear because of policy composition.
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

    if hasattr(form, "replaceWidget"):
        form.replaceWidget(old, settle)
        old.hide()
        old.deleteLater()
    self.settle_time_spin = settle
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
