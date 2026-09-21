from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class WcdmaSearchResult:
    sensitivity: float
    ber: float
    phase: str
    measurements: int


def fast_step_for_ber(ber: float, max_step: float) -> float:
    """Return the V1 WCDMA fast-search step using raw CMW500 BER values."""
    value = float(ber)
    cap = float(max_step)
    if value > 0.05:
        return min(0.3, cap)
    if value > 0.01:
        return min(0.5, cap)
    if value > 0.005:
        return min(0.7, cap)
    if value > 0.001:
        return min(1.0, cap)
    return cap


def search_wcdma_sensitivity(
    *,
    start_level: float,
    max_step: float,
    min_step: float,
    threshold: float,
    fast_packet_count: int,
    confirm_packet_count: int,
    set_level: Callable[[float], None],
    ensure_connected: Callable[[], bool],
    measure_ber: Callable[[int], float],
    cooperate: Callable[[], None] | None = None,
    max_fast_iterations: int = 200,
    max_backtrack_iterations: int = 200,
) -> WcdmaSearchResult:
    """WCDMA sensitivity-search V1 agreed with the existing robot workflow.

    BER is compared exactly as returned by the instrument; no percent scaling is
    performed. Fast scan walks downward until BER exceeds threshold. The point
    is then confirmed with the normal packet count. A confirmed BER in 0.08..0.12
    returns directly; BER above threshold backtracks upward using min_step until
    BER falls below threshold.
    """
    level = float(start_level)
    threshold = float(threshold)
    measurements = 0

    def one(packet_count: int) -> float:
        nonlocal measurements
        if cooperate:
            cooperate()
        if not ensure_connected():
            raise RuntimeError("WCDMA 测量前连接检查失败")
        set_level(level)
        ber = float(measure_ber(int(packet_count)))
        measurements += 1
        return ber

    for _ in range(int(max_fast_iterations)):
        ber = one(fast_packet_count)
        if ber > threshold:
            confirm_ber = one(confirm_packet_count)
            if 0.08 <= confirm_ber <= 0.12:
                return WcdmaSearchResult(level, confirm_ber, "CONFIRM_WINDOW", measurements)
            if confirm_ber > threshold:
                for _ in range(int(max_backtrack_iterations)):
                    level = round(level + float(min_step), 10)
                    confirm_ber = one(confirm_packet_count)
                    if confirm_ber < threshold:
                        return WcdmaSearchResult(level, confirm_ber, "BACKTRACK", measurements)
                raise RuntimeError("WCDMA 灵敏度向上回找超过 200 次仍未低于 BER 门限")
            # Confirmation fell below the threshold: continue downward from the
            # same point using the confirmed BER to choose the next V1 step.
            ber = confirm_ber
        level = round(level - fast_step_for_ber(ber, max_step), 10)

    raise RuntimeError("WCDMA 快速灵敏度搜索超过 200 次仍未找到 BER 门限点")
