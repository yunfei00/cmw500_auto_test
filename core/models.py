from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4


def local_now_iso() -> str:
    """Return an ISO-8601 timestamp with the local UTC offset."""

    return datetime.now().astimezone().isoformat(timespec="milliseconds")


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
    settle_time: float
    retry_count: int
    selected_bands: list[str]
    selected_channel_types: list[str]
    custom_channels: list[int]
    lte_test_items: list[str]
    test_mode: str
    data: list[dict[str, str | int | float]] = field(default_factory=list)
    run_id: str = ""
    com_port: int = 1
    pusch_open_loop_nom_power: float = 23.0
    pusch_closed_loop_target_power: float = 0.0
    scene_ids: list[str] = field(default_factory=list)
    scene_device_id: str = ""
    scene_package_name: str = "com.yunfei.autotestscene"
    scene_settle_time: float = 3.0
    scene_duration: int = 0
    scene_particles: int = 250
    scene_cpu_threads: int = 2
    scene_audio: bool = False
    scene_vibration: bool = False


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
    loss_db: float = 0.0
    scene_id: str = "idle"


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
    metric_value: float | None
    result: str
    status: str
    timestamp: str = field(default_factory=local_now_iso)
    run_id: str = ""
    data_source: str = "UNKNOWN"
    bw: float | None = None
    global_cable_loss: float = 0.0
    channel_loss: float = 0.0
    total_loss: float = 0.0
    instrument_level: float | None = None
    packet_count: int = 0
    bler_threshold: float = 0.0
    sensitivity_upper: float | None = None
    attempt: int = 1
    scan_phase: str = "COARSE"
    error_message: str = ""
    # Optional UE measurement-report values sampled at the final sensitivity point.
    # They are reference-only and never affect the sensitivity verdict.
    rsrp: float | None = None
    rsrq: float | None = None
    reference_metrics_status: str = ""
    scene_id: str = "idle"


@dataclass
class TestRunMetadata:
    """Traceability metadata for one isolated test run."""

    run_id: str = field(default_factory=lambda: str(uuid4()))
    start_time: str = field(default_factory=local_now_iso)
    end_time: str = ""
    status: str = "CREATED"
    data_source: str = "UNKNOWN"
    instrument_mode: str = ""
    instrument_idn: str = ""
    device_id: str = ""
    dut_serial: str = ""
    operator: str = ""
    package_name: str = ""
    apk_path: str = ""
    apk_sha256: str = ""
    software_version: str = ""
    build_commit: str = ""
    build_time: str = ""
    build_dirty: bool = False
    instrument_calibration_id: str = ""
    instrument_calibration_due_date: str = ""
    connection: dict[str, Any] = field(default_factory=dict)
    channel_config_path: str = ""
    channel_config_sha256: str = ""
    scpi_template_path: str = ""
    scpi_template_sha256: str = ""
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    command_trace: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
