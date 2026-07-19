from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from ui.left_panel import LeftPanel


def test_shutdown_during_active_run_is_safe_and_does_not_deadlock(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app = QApplication.instance() or QApplication([])
    panel = LeftPanel()
    completed_runs: list[dict] = []
    panel.set_finished_callback(completed_runs.append)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    panel.start_level_spin.setValue(-70.0)
    panel.stop_level_spin.setValue(-71.0)
    panel.max_step_spin.setValue(1.0)
    panel.min_step_spin.setValue(1.0)
    panel.settle_time_spin.setValue(0)

    panel._start_test()
    assert panel.worker_thread is not None

    started = time.monotonic()
    assert panel.shutdown(timeout_ms=5000)
    elapsed = time.monotonic() - started

    assert elapsed < 5.0
    assert completed_runs
    assert completed_runs[-1]["status"] == "STOPPED"
    assert completed_runs[-1]["data_source"] == "SIMULATION"
    assert completed_runs[-1]["connection"] == {"type": "FAKE"}
    assert len(completed_runs[-1]["channel_config_sha256"]) == 64
    assert len(completed_runs[-1]["scpi_template_sha256"]) == 64
    assert completed_runs[-1]["build_commit"]
    assert panel.worker is None
    assert panel.worker_thread is None

    panel._capture_worker_state("FAILED_UNSAFE")
    assert panel.requires_unsafe_exit_acknowledgement()
    panel._capture_worker_state("COMPLETED")
    panel._start_test()
    assert panel.worker is None
    assert panel.worker_thread is None
    assert panel.requires_unsafe_exit_acknowledgement()
    assert not panel.shutdown()
    panel.acknowledge_unsafe_exit()
    assert not panel.requires_unsafe_exit_acknowledgement()
    assert panel.shutdown()
    panel.deleteLater()
    app.processEvents()
