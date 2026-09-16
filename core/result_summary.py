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
    run_id: str = ""
    data_source: str = "UNKNOWN"
    bw: float | None = None
    error_count: int = 0


def build_lte_summary(results: list[TestResult]) -> list[SummaryResult]:
    grouped_results: dict[
        tuple[str, str, str, str, int, str, str, float | None], list[TestResult]
    ] = {}
    for result in results:
        key = (
            result.run_id,
            result.data_source,
            result.mode,
            result.band,
            result.channel,
            result.channel_type,
            result.test_mode,
            result.bw,
        )
        grouped_results.setdefault(key, []).append(result)

    summary_results: list[SummaryResult] = []
    for (
        run_id,
        data_source,
        mode,
        band,
        channel,
        channel_type,
        test_mode,
        bw,
    ), group in grouped_results.items():
        terminal_items = _terminal_attempts(group)
        # The fast sensitivity policy completes a channel only when the fine scan
        # finds its first PASS point. Do not expose intermediate FAST/CONFIRM
        # points as a summary row.
        fine_passes = [
            item
            for item in terminal_items
            if item.scan_phase.upper() == "FINE" and item.result.upper() == "PASS"
        ]
        if not fine_passes:
            continue

        sensitivity = min(item.rx_level for item in fine_passes)
        pass_items = [item for item in group if item.result.upper() == "PASS"]
        fail_items = [item for item in group if item.result.upper() == "FAIL"]
        error_items = [item for item in group if item.result.upper() == "ERROR"]

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
                result="PASS",
                remark=f"Sensitivity = {sensitivity:g} dBm",
                run_id=run_id,
                data_source=data_source,
                bw=bw,
                error_count=len(error_items),
            )
        )

    return summary_results


def _terminal_attempts(group: list[TestResult]) -> list[TestResult]:
    latest: dict[tuple[str, float], TestResult] = {}
    for item in group:
        key = (item.scan_phase, item.rx_level)
        previous = latest.get(key)
        if previous is None or item.attempt >= previous.attempt:
            latest[key] = item
    return list(latest.values())
