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
    sensitivity_upper: float | None = None
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
        pass_items = [item for item in group if item.result.upper() == "PASS"]
        fail_items = [item for item in group if item.result.upper() == "FAIL"]
        error_items = [item for item in group if item.result.upper() == "ERROR"]
        terminal_items = _terminal_attempts(group)
        terminal_errors = [item for item in terminal_items if item.result.upper() == "ERROR"]
        terminal_passes = [item for item in terminal_items if item.result.upper() == "PASS"]
        sensitivity = min((item.rx_level for item in terminal_passes), default=None)
        sensitivity_upper = next(
            (item.sensitivity_upper for item in group if item.sensitivity_upper is not None),
            None,
        )

        if terminal_errors:
            summary_result = "ERROR"
            remark = "Measurement incomplete because the final retry ended with an error"
        elif sensitivity is None:
            summary_result = "FAIL"
            remark = "No PASS point found"
        elif sensitivity_upper is None:
            summary_result = "PASS"
            remark = f"Sensitivity = {sensitivity:g} dBm (no specification limit)"
        elif sensitivity <= sensitivity_upper:
            summary_result = "PASS"
            remark = (
                f"Sensitivity = {sensitivity:g} dBm, meets upper limit "
                f"{sensitivity_upper:g} dBm"
            )
        else:
            summary_result = "FAIL"
            remark = (
                f"Sensitivity = {sensitivity:g} dBm, exceeds upper limit "
                f"{sensitivity_upper:g} dBm"
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
                run_id=run_id,
                data_source=data_source,
                bw=bw,
                sensitivity_upper=sensitivity_upper,
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
