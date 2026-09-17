from __future__ import annotations

"""Allow sub-second LTE settle time values in the operator UI.

The base UI historically used QSpinBox, which restricted settle time to whole
seconds.  LTE fast scanning needs sub-second experiments, so replace only this
control with a QDoubleSpinBox while preserving the existing configuration flow.
"""

from PySide6.QtWidgets import QDoubleSpinBox

from ui.left_panel import LeftPanel


_original_create_lte_instrument_group = LeftPanel._create_lte_instrument_group


def _create_lte_instrument_group_with_fractional_settle(self: LeftPanel):
    group = _original_create_lte_instrument_group(self)
    form = group.layout()
    old = self.settle_time_spin

    settle = QDoubleSpinBox()
    settle.setRange(0.0, 3600.0)
    settle.setDecimals(2)
    settle.setSingleStep(0.1)
    settle.setSuffix(" s")

    # Read the persisted value as float.  The fast-scan compatibility layer
    # previously read this setting as int, which would otherwise discard the
    # decimal part before this widget is created.
    saved = self.settings.value("lte/settle_time", old.value(), float)
    settle.setValue(float(saved))

    if hasattr(form, "replaceWidget"):
        form.replaceWidget(old, settle)
        old.hide()
        old.deleteLater()
    self.settle_time_spin = settle
    return group


def apply_lte_settle_time_policy() -> None:
    if getattr(LeftPanel, "_lte_settle_time_policy_applied", False):
        return
    LeftPanel._create_lte_instrument_group = _create_lte_instrument_group_with_fractional_settle
    LeftPanel._lte_settle_time_policy_applied = True
