from __future__ import annotations

import math


def judge_bler(bler: float, threshold: float) -> str:
    if not math.isfinite(bler) or not 0.0 <= bler <= 100.0:
        raise ValueError(f"BLER must be finite and within 0..100, got {bler!r}")
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 100.0:
        raise ValueError(
            f"BLER threshold must be finite and within 0..100, got {threshold!r}"
        )
    return "PASS" if bler <= threshold else "FAIL"
