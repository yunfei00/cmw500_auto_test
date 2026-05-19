from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LteTestConfig:
    cable_loss: float
    sensitivity_upper: float
    start_level: float
    stop_level: float
    packet_count: int
    max_step: float
    min_step: float
    bler_threshold: float
    settle_time: int
    retry_count: int
    selected_bands: list[str]
    selected_channel_types: list[str]
    custom_channels: list[int]
    lte_test_item: str
    test_mode: str


@dataclass
class TestItem:
    index: int
    mode: str
    band: str
    channel: int
    channel_type: str
    test_mode: str
    rx_level: float
    bw: float | None = None


@dataclass
class TestResult:
    index: int
    mode: str
    band: str
    channel: int
    channel_type: str
    test_mode: str
    rx_level: float
    metric_type: str
    metric_value: float
    result: str
    status: str
    timestamp: str
