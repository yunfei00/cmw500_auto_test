from __future__ import annotations

from core.models import TestResult as Result
from core.models import TestRunMetadata as RunMetadata
from core.result_judge import judge_bler
from core.result_summary import build_lte_summary


def result(
    *,
    run_id: str,
    level: float,
    verdict: str,
    attempt: int = 1,
    phase: str = "COARSE",
    upper: float = -85.0,
) -> Result:
    return Result(
        index=1,
        mode="LTE",
        band="B3",
        channel=1575,
        channel_type="转盘测试",
        test_mode="单主",
        rx_level=level,
        metric_type="BLER",
        metric_value=None if verdict == "ERROR" else (1.0 if verdict == "PASS" else 20.0),
        result=verdict,
        status="COMPLETED" if verdict != "ERROR" else "ERROR",
        run_id=run_id,
        data_source="INSTRUMENT",
        bw=20.0,
        sensitivity_upper=upper,
        attempt=attempt,
        scan_phase=phase,
    )


def test_summary_uses_terminal_retry_and_sensitivity_specification() -> None:
    rows = [
        result(run_id="r1", level=-80.0, verdict="PASS"),
        result(run_id="r1", level=-86.0, verdict="FAIL", attempt=1, phase="FINE"),
        result(run_id="r1", level=-86.0, verdict="PASS", attempt=2, phase="FINE"),
        result(run_id="r1", level=-87.0, verdict="FAIL", attempt=2, phase="FINE"),
    ]

    summary = build_lte_summary(rows)[0]

    assert summary.sensitivity == -86.0
    assert summary.sensitivity_upper == -85.0
    assert summary.result == "PASS"
    assert summary.pass_count == 2
    assert summary.fail_count == 2


def test_summary_fails_when_sensitivity_exceeds_upper_limit() -> None:
    rows = [result(run_id="r1", level=-86.0, verdict="PASS", upper=-87.0)]

    summary = build_lte_summary(rows)[0]

    assert summary.result == "FAIL"
    assert "exceeds upper limit" in summary.remark


def test_summary_keeps_runs_isolated_and_marks_terminal_error() -> None:
    rows = [
        result(run_id="r1", level=-86.0, verdict="PASS"),
        result(run_id="r2", level=-86.0, verdict="ERROR"),
    ]

    summaries = build_lte_summary(rows)

    assert len(summaries) == 2
    by_run = {item.run_id: item for item in summaries}
    assert by_run["r1"].result == "PASS"
    assert by_run["r2"].result == "ERROR"
    assert by_run["r2"].error_count == 1


def test_bler_judge_rejects_non_finite_and_out_of_range_values() -> None:
    for invalid in (float("nan"), float("inf"), -0.1, 100.1):
        try:
            judge_bler(invalid, 10.0)
        except ValueError:
            pass
        else:
            raise AssertionError(f"judge_bler accepted invalid value {invalid!r}")


def test_run_metadata_to_dict_returns_independent_containers() -> None:
    metadata = RunMetadata(
        run_id="run-1",
        config_snapshot={"packet_count": 1000},
        command_trace=[{"command": "*IDN?"}],
    )

    value = metadata.to_dict()
    value["config_snapshot"]["packet_count"] = 1

    assert metadata.config_snapshot["packet_count"] == 1000
