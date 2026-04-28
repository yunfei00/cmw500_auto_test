from __future__ import annotations


def judge_bler(bler: float, threshold: float) -> str:
    return "PASS" if bler <= threshold else "FAIL"
