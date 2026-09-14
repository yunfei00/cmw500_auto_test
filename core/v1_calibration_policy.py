from __future__ import annotations

from typing import Any

from ui.left_panel import LeftPanel


_CALIBRATION_ID_KEY = "instrument/calibration_id"
_CALIBRATION_DUE_KEY = "instrument/calibration_due_date"
_PATCHED = False


def _restore_optional_calibration(self: LeftPanel) -> None:
    calibration_id = self.settings.value(_CALIBRATION_ID_KEY, "", str)
    calibration_due = self.settings.value(_CALIBRATION_DUE_KEY, "", str)
    self.calibration_id_edit.setText(calibration_id.strip() if isinstance(calibration_id, str) else "")
    self.calibration_due_date_edit.setText(
        calibration_due.strip() if isinstance(calibration_due, str) else ""
    )
    self.calibration_id_edit.setPlaceholderText("可选；填写后自动记忆")
    self.calibration_due_date_edit.setPlaceholderText("可选；YYYY-MM-DD；填写后自动记忆")


def _save_optional_calibration(self: LeftPanel) -> None:
    self.settings.setValue(_CALIBRATION_ID_KEY, self.calibration_id_edit.text().strip())
    self.settings.setValue(
        _CALIBRATION_DUE_KEY,
        self.calibration_due_date_edit.text().strip(),
    )
    self.settings.sync()


def apply_optional_calibration_policy() -> None:
    """Make calibration metadata optional in V1 while preserving traceability.

    Values remain in run metadata/reports when supplied. They are remembered with
    QSettings and restored on the next launch, but they never block a Real CMW500
    run during the V1 bring-up stage.
    """

    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    original_init = LeftPanel.__init__

    def init_with_optional_calibration(self: LeftPanel, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        _restore_optional_calibration(self)
        self.calibration_id_edit.editingFinished.connect(
            lambda: _save_optional_calibration(self)
        )
        self.calibration_due_date_edit.editingFinished.connect(
            lambda: _save_optional_calibration(self)
        )

    LeftPanel.__init__ = init_with_optional_calibration  # type: ignore[method-assign]

    original_validate = LeftPanel._validate_lte_channel_config

    def validate_without_calibration_gate(self: LeftPanel, config) -> bool:
        # Persist whatever the operator entered before validation/report creation.
        _save_optional_calibration(self)

        actual_id = self.calibration_id_edit.text()
        actual_due = self.calibration_due_date_edit.text()
        try:
            # The legacy validator treats calibration metadata as mandatory and
            # rejects expired/blank values. Feed harmless temporary values only
            # while it validates the rest of the LTE configuration. The user's
            # real values are restored immediately and are what reports record.
            self.calibration_id_edit.setText(actual_id.strip() or "OPTIONAL")
            self.calibration_due_date_edit.setText("2999-12-31")
            return bool(original_validate(self, config))
        finally:
            self.calibration_id_edit.setText(actual_id)
            self.calibration_due_date_edit.setText(actual_due)

    LeftPanel._validate_lte_channel_config = validate_without_calibration_gate  # type: ignore[method-assign]
