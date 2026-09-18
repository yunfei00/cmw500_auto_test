from __future__ import annotations

from core.models import TestResult as Result
from core.result_summary import build_lte_summary
from devices.adb_client import AdbClient


class RecordingAdbClient(AdbClient):
    def __init__(self) -> None:
        super().__init__()
        self.commands: list[list[str]] = []

    def _adb_available(self) -> bool:
        return True

    def _run(self, command: list[str]) -> tuple[bool, str]:
        self.commands.append(command)
        if "dumpsys" in command:
            return (
                True,
                "mResumedActivity: ActivityRecord{1 u0 "
                "com.yunfei.autotestscene/.scene.MusicSceneActivity t1}",
            )
        return True, "OK"


def _result(scene_id: str, sensitivity: float) -> Result:
    return Result(
        index=1,
        mode="LTE",
        band="B3",
        channel=1575,
        channel_type="固定信道",
        test_mode="单主",
        rx_level=sensitivity,
        metric_type="BLER",
        metric_value=4.0,
        result="PASS",
        status="COMPLETED",
        run_id="scene-run",
        data_source="REAL",
        bw=20.0,
        attempt=1,
        scan_phase="FINE",
        scene_id=scene_id,
    )


def test_summary_groups_by_scene_and_calculates_idle_degradation() -> None:
    summaries = build_lte_summary(
        [
            _result("idle", -101.5),
            _result("video", -99.7),
        ]
    )

    by_scene = {item.scene_id: item for item in summaries}
    assert by_scene["idle"].delta_vs_idle == 0.0
    assert round(by_scene["video"].delta_vs_idle or 0.0, 1) == 1.8


def test_adb_scene_start_uses_exported_entry_and_verifies_activity() -> None:
    adb = RecordingAdbClient()

    success, message = adb.start_scene(
        "DEVICE123",
        "music",
        duration=120,
        particles=300,
        cpu_threads=3,
    )

    assert success is True
    assert message == "music RUNNING"
    start_commands = [cmd for cmd in adb.commands if "start" in cmd and "-W" in cmd]
    assert len(start_commands) == 1
    command = start_commands[0]
    assert "com.yunfei.autotestscene/.SceneEntryActivity" in command
    assert command[command.index("--es") + 1 : command.index("--es") + 3] == ["scene", "music"]
    assert "120" in command


def test_install_grants_runtime_permissions() -> None:
    adb = RecordingAdbClient()

    success, _ = adb.install_app("DEVICE123", "scene.apk")

    assert success is True
    assert adb.commands[-1] == [
        "adb",
        "-s",
        "DEVICE123",
        "install",
        "-r",
        "-g",
        "scene.apk",
    ]
