from __future__ import annotations

from dataclasses import dataclass

from core.models import TestResult


@dataclass
class SummaryResult:
    mode: str
    band: str
    channel: int
    channel_type: str
    test_mode: str
    sensitivity: float | None
    pass_count: int
    fail_count: int
    total_count: int
    result: str
    remark: str


def build_lte_summary(results: list[TestResult]) -> list[SummaryResult]:
    grouped_results: dict[tuple[str, str, int, str, str], list[TestResult]] = {}
    for result in results:
        key = (result.mode, result.band, result.channel, result.channel_type, result.test_mode)
        grouped_results.setdefault(key, []).append(result)

    summary_results: list[SummaryResult] = []
    for (mode, band, channel, channel_type, test_mode), group in grouped_results.items():
        pass_items = [item for item in group if item.result.upper() == "PASS"]
        fail_items = [item for item in group if item.result.upper() == "FAIL"]
        sensitivity = min((item.rx_level for item in pass_items), default=None)
        summary_result = "PASS" if sensitivity is not None else "FAIL"
        remark = (
            f"Sensitivity = {sensitivity:g} dBm"
            if sensitivity is not None
            else "No PASS point found"
        )

        summary_results.append(
            SummaryResult(
                mode=mode,
                band=band,
                channel=channel,
                channel_type=channel_type,
                test_mode=test_mode,
                sensitivity=sensitivity,
                pass_count=len(pass_items),
                fail_count=len(fail_items),
                total_count=len(group),
                result=summary_result,
                remark=remark,
            )
        )

    return summary_results
