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
    phase: str = "FINE",
    metric_value: float | None = None,
    error_message: str = "",
) -> Result:
    if metric_value is None and verdict not in {"ERROR", "FAILED"}:
        metric_value = 1.0 if verdict == "PASS" else 20.0
    return Result(
        index=1,
        mode="LTE",
        band="B3",
        channel=1575,
        channel_type="转盘测试",
        test_mode="单主",
        rx_level=level,
        metric_type="BLER",
        metric_value=metric_value,
        result=verdict,
        status="COMPLETED" if verdict not in {"ERROR", "FAILED"} else "FAILED",
        run_id=run_id,
        data_source="INSTRUMENT",
        bw=20.0,
        attempt=attempt,
        scan_phase=phase,
        error_message=error_message,
    )


def test_summary_uses_terminal_retry_and_reports_final_bler() -> None:
    rows = [
        result(run_id="r1", level=-80.0, verdict="PASS", phase="FAST"),
        result(run_id="r1", level=-86.0, verdict="FAIL", attempt=1, phase="FINE"),
        result(run_id="r1", level=-86.0, verdict="PASS", attempt=2, phase="FINE", metric_value=4.9),
        result(run_id="r1", level=-87.0, verdict="FAIL", attempt=2, phase="FINE"),
    ]

    summary = build_lte_summary(rows)[0]

    assert summary.sensitivity == -86.0
    assert summary.final_bler == 4.9
    assert summary.result == "PASS"
    assert summary.pass_count == 2
    assert summary.fail_count == 2


def test_summary_no_longer_applies_legacy_sensitivity_upper_limit() -> None:
    rows = [result(run_id="r1", level=-120.0, verdict="PASS", phase="FINE", metric_value=4.8)]

    summary = build_lte_summary(rows)[0]

    assert summary.sensitivity == -120.0
    assert summary.final_bler == 4.8
    assert summary.result == "PASS"


def test_summary_keeps_runs_isolated_and_marks_channel_failure() -> None:
    rows = [
        result(run_id="r1", level=-86.0, verdict="PASS", phase="FINE"),
        result(
            run_id="r2",
            level=-85.0,
            verdict="FAILED",
            phase="CHANNEL",
            error_message="UE Attach timeout",
        ),
    ]

    summaries = build_lte_summary(rows)

    assert len(summaries) == 2
    by_run = {item.run_id: item for item in summaries}
    assert by_run["r1"].result == "PASS"
    assert by_run["r2"].result == "FAILED"
    assert by_run["r2"].sensitivity is None
    assert by_run["r2"].final_bler is None
    assert by_run["r2"].error_count == 1
    assert "UE Attach timeout" in by_run["r2"].remark


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
