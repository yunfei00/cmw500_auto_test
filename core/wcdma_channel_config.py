from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WcdmaBandPlan:
    begin: int
    end: int
    step: int
    bw_mhz: float
    three_channels: tuple[int, int, int]


WCDMA_BAND_PLANS: dict[int, WcdmaBandPlan] = {
    1: WcdmaBandPlan(10575, 10825, 50, 5.0, (10562, 10700, 10838)),
    2: WcdmaBandPlan(9675, 9925, 50, 5.0, (9675, 9800, 9925)),
    4: WcdmaBandPlan(3325, 3500, 50, 5.0, (3325, 3410, 3500)),
    5: WcdmaBandPlan(4358, 4458, 5, 5.0, (4357, 4408, 4458)),
    6: WcdmaBandPlan(100, 200, 50, 5.0, (100, 150, 200)),
    8: WcdmaBandPlan(2950, 3075, 50, 5.0, (2937, 3013, 3088)),
    19: WcdmaBandPlan(550, 575, 50, 5.0, (550, 560, 575)),
}


def channels_for_band(band: int, mode: str) -> list[int]:
    plan = WCDMA_BAND_PLANS[int(band)]
    if mode == "三信道":
        return list(plan.three_channels)
    if mode == "遍历":
        channels = list(range(plan.begin, plan.end + 1, plan.step))
        if not channels or channels[-1] != plan.end:
            channels.append(plan.end)
        return channels
    raise ValueError(f"未知 WCDMA 信道模式：{mode}")
