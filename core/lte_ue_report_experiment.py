from __future__ import annotations

"""CMW500 UE-report experiment support.

This policy is deliberately isolated from the LTE UI.  It configures the CMW500 UE
measurement-report interval to 120 ms and samples the serving-cell report after every
BLER measurement.  Sampling failures are non-fatal because the experiment must not
change the sensitivity verdict.
"""

import re
from typing import Any

from devices.cmw500_controller import RealCMW500


UE_REPORT_INTERVAL_COMMAND = "CONFigure:LTE:SIGN:UEReport:RINTerval I120"
UE_REPORT_INTERVAL_QUERY = "CONFigure:LTE:SIGN:UEReport:RINTerval?"
UE_REPORT_SCELL_QUERY = "SENSe:LTE:SIGN:UEReport:PCC:SCELl?"
UE_REPORT_SCELL_RANGE_QUERY = "SENSe:LTE:SIGN:UEReport:PCC:SCELl:RANGe?"


def _numbers(value: Any) -> list[float]:
    return [float(item) for item in re.findall(r"[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?", str(value))]


def _sample_ue_report(self: RealCMW500, bler: float) -> None:
    try:
        raw_index = self.query(UE_REPORT_SCELL_QUERY)
        raw_range = self.query(UE_REPORT_SCELL_RANGE_QUERY)
        index_values = _numbers(raw_index)
        range_values = _numbers(raw_range)
        if len(index_values) < 2 or len(range_values) < 4:
            raise ValueError(f"unexpected UE report: index={raw_index!r}, range={raw_range!r}")

        sample = {
            "band": self.current_band,
            "channel": self.current_channel,
            "rs_epre_dbm": float(self.current_rx_level),
            "packet_count": int(self.current_packet_count),
            "bler_pct": float(bler),
            "rsrp_index": int(index_values[0]),
            "rsrq_index": int(index_values[1]),
            "rsrp_lower_dbm": float(range_values[0]),
            "rsrp_upper_dbm": float(range_values[1]),
            "rsrq_lower_db": float(range_values[2]),
            "rsrq_upper_db": float(range_values[3]),
        }
        history = getattr(self, "ue_report_experiment_samples", None)
        if history is None:
            history = []
            self.ue_report_experiment_samples = history
        history.append(sample)

        # Reuse the existing worker warning bridge so the sample is visible in the
        # operator log without coupling the instrument controller to Qt signals.
        self.last_warning = (
            "UE实验采样 "
            f"RS_EPRe={sample['rs_epre_dbm']:g} dBm, "
            f"RSRP={sample['rsrp_index']} [{sample['rsrp_lower_dbm']:g},{sample['rsrp_upper_dbm']:g}] dBm, "
            f"RSRQ={sample['rsrq_index']} [{sample['rsrq_lower_db']:g},{sample['rsrq_upper_db']:g}] dB, "
            f"BLER={sample['bler_pct']:.2f}%"
        )
    except Exception as exc:
        self.last_warning = f"UE实验采样失败（不影响灵敏度结果）：{exc}"


def apply_lte_ue_report_experiment() -> None:
    if getattr(RealCMW500, "_ue_report_experiment_applied", False):
        return

    original_prepare_run = RealCMW500.lte_prepare_run
    original_measure_bler = RealCMW500.measure_bler

    def prepare_run(self: RealCMW500, *args: Any, **kwargs: Any) -> None:
        original_prepare_run(self, *args, **kwargs)
        # Configure interval before enabling/using report data for the experiment.
        self.write(UE_REPORT_INTERVAL_COMMAND)
        actual = str(self.query(UE_REPORT_INTERVAL_QUERY)).strip().upper()
        if "I120" not in actual:
            raise RuntimeError(f"UE Report interval 回读异常：期望 I120，实际 {actual!r}")
        self.ue_report_experiment_samples = []

    def measure_bler(self: RealCMW500, packet_count: int) -> float:
        result = float(original_measure_bler(self, packet_count))
        _sample_ue_report(self, result)
        return result

    RealCMW500.lte_prepare_run = prepare_run
    RealCMW500.measure_bler = measure_bler
    RealCMW500._ue_report_experiment_applied = True
