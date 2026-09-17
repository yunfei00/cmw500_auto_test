from __future__ import annotations

"""Allow sub-second LTE settle time values end-to-end."""

from PySide6.QtWidgets import QDoubleSpinBox

from ui.left_panel import LeftPanel


DEFAULT_SETTLE_TIME = 0.1
_original_create_lte_instrument_group = LeftPanel._create_lte_instrument_group
_original_collect_lte_config = LeftPanel.collect_lte_config


def _create_lte_instrument_group_with_fractional_settle(self: LeftPanel):
    group = _original_create_lte_instrument_group(self)
    form = group.layout()
    old = self.settle_time_spin

    settle = QDoubleSpinBox()
    settle.setRange(0.0, 3600.0)
    settle.setDecimals(2)
    settle.setSingleStep(0.1)
    settle.setSuffix(" s")
    settle.setKeyboardTracking(False)

    # Persisted values remain supported.  For a fresh installation the default
    # is 0.1 s.  Read as float so values such as 0.1 are never truncated.
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
    # The legacy collection path may cast the value to int.  Override it from
    # the QDoubleSpinBox so the worker always receives the exact decimal value.
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
