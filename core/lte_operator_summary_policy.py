from __future__ import annotations

"""Small LTE V1 operator-facing additions.

- Emit an explicit Cell ON log after the instrument command succeeds.
- Carry the BLER measured at the terminal FINE PASS into the channel summary.
"""

from core.result_summary import SummaryResult
from core.test_worker import TestWorker
from ui.center_panel import CenterPanel


_original_call_lte_cell_on = TestWorker._call_lte_cell_on
_original_summary_to_row = CenterPanel._summary_result_to_row_data


def _call_lte_cell_on_with_log(self: TestWorker, item) -> None:
    _original_call_lte_cell_on(self, item)
    self.log_signal.emit("INFO", f"LTE Cell ON：{item.band} 信道 {item.channel}")


def _summary_to_row_with_final_bler(self: CenterPanel, result: SummaryResult) -> dict:
    row = _original_summary_to_row(self, result)
    final_bler = getattr(result, "final_bler", None)
    row["最终BLER(%)"] = "N/A" if final_bler is None else f"{float(final_bler):.2f}"
    return row


def apply_lte_operator_summary_policy() -> None:
    if getattr(TestWorker, "_lte_operator_summary_policy_applied", False):
        return

    TestWorker._call_lte_cell_on = _call_lte_cell_on_with_log
    if "最终BLER(%)" not in CenterPanel.SUMMARY_HEADERS:
        sensitivity_index = CenterPanel.SUMMARY_HEADERS.index("灵敏度(dBm)")
        CenterPanel.SUMMARY_HEADERS.insert(sensitivity_index + 1, "最终BLER(%)")
    CenterPanel._summary_result_to_row_data = _summary_to_row_with_final_bler
    TestWorker._lte_operator_summary_policy_applied = True
