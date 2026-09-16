from __future__ import annotations

"""Keep LTE V1 running when one channel fails.

This policy is applied after ``apply_lte_fast_scan_policy`` so it wraps the
final LTE cell-preparation and scan implementations without changing global
safety behavior. A Cell OFF failure is still treated as unsafe and is allowed
to abort the whole run.
"""

from dataclasses import replace
from typing import Any

from core.test_worker import TestWorker


def apply_lte_channel_resilience() -> None:
    if getattr(TestWorker, "_lte_channel_resilience_applied", False):
        return

    strict_prepare_cell = TestWorker._prepare_cell
    strict_measure_item = TestWorker._measure_item

    def emit_channel_failure(worker: TestWorker, item: Any, message: str) -> None:
        measured_item = replace(item, rx_level=float(worker.config.start_level))
        result = worker._build_result(
            measured_item,
            None,
            "FAILED",
            "FAILED",
            attempt=1,
            phase="CHANNEL",
            instrument_level=worker._instrument_level_for_dut(
                item, float(worker.config.start_level)
            ),
            error_message=message,
        )
        worker.row_signal.emit(result)
        worker.log_signal.emit(
            "ERROR",
            f"{item.band}/{item.channel} 信道测试失败，已记录 FAILED；跳过该信道并继续后续测试：{message}",
        )

    def prepare_cell_resilient(worker: TestWorker, item: Any) -> None:
        worker._channel_prepare_failed_key = None
        try:
            strict_prepare_cell(worker, item)
        except Exception as exc:
            # Stop requests and RF-safety failures must keep the original global
            # abort semantics. In particular, never continue if Cell OFF failed.
            if worker._is_stopped() or "Cell OFF" in str(exc):
                raise
            key = (item.band, item.channel, item.bw)
            worker._channel_prepare_failed_key = key
            emit_channel_failure(worker, item, str(exc))

    def measure_item_resilient(
        worker: TestWorker, item: Any, current: int, total: int
    ) -> bool:
        key = (item.band, item.channel, item.bw)
        if getattr(worker, "_channel_prepare_failed_key", None) == key:
            worker._channel_prepare_failed_key = None
            return True

        completed = strict_measure_item(worker, item, current, total)
        if completed:
            return True

        last_result = getattr(worker, "_last_built_test_result", None)
        message = "灵敏度扫描失败"
        if last_result is not None:
            detail = str(getattr(last_result, "error_message", "") or "").strip()
            if detail:
                message = detail
        emit_channel_failure(worker, item, message)
        # Returning True tells the outer test-plan loop that this item has been
        # handled. The next item will perform the normal Cell OFF/channel switch.
        return True

    TestWorker._prepare_cell = prepare_cell_resilient
    TestWorker._measure_item = measure_item_resilient
    TestWorker._lte_channel_resilience_applied = True
