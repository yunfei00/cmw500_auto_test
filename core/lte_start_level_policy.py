from __future__ import annotations

"""Compatibility policy for LTE V1 after the stop-level setting was retired.

The active fast scan no longer uses ``stop_level``.  Older validation code still
compares ``start_level`` with the hidden legacy value (-120 dBm), which prevents
using -120 dBm (or lower) as the initial level.  This policy removes only that
obsolete dependency while keeping the rest of the existing validation intact.
"""

from core.test_worker import TestWorker
from ui.left_panel import LeftPanel


_original_worker_validate_config = TestWorker._validate_config
_original_panel_validate_channel_config = LeftPanel._validate_lte_channel_config


def _legacy_stop_below_start(config) -> float:
    """Return a temporary legacy stop value that can never constrain start."""
    return float(config.start_level) - 1.0


def _validate_worker_config_without_stop_level(self) -> None:
    original_stop = self.config.stop_level
    try:
        self.config.stop_level = _legacy_stop_below_start(self.config)
        _original_worker_validate_config(self)
    finally:
        self.config.stop_level = original_stop


def _validate_panel_config_without_stop_level(self, config) -> bool:
    original_stop = config.stop_level
    try:
        config.stop_level = _legacy_stop_below_start(config)
        return _original_panel_validate_channel_config(self, config)
    finally:
        config.stop_level = original_stop


def apply_lte_start_level_policy() -> None:
    if getattr(LeftPanel, "_lte_start_level_policy_applied", False):
        return

    TestWorker._validate_config = _validate_worker_config_without_stop_level
    LeftPanel._validate_lte_channel_config = _validate_panel_config_without_stop_level
    LeftPanel._lte_start_level_policy_applied = True
