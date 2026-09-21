from __future__ import annotations

from types import SimpleNamespace

from core.models import LteTestConfig
from core.test_plan import generate_lte_test_plan


def make_config(**overrides):
    values = dict(
        cable_loss=35.0,
        sensitivity_upper=-70.0,
        start_level=-70.0,
        stop_level=-120.0,
        packet_count=1000,
        max_step=4.0,
        min_step=1.0,
        bler_threshold=10.0,
        settle_time=0.0,
        retry_count=0,
        selected_bands=["B3"],
        selected_channel_types=[],
        custom_channels=[],
        lte_test_items=["三信道测试"],
        test_mode="默认",
        scenes=["灭屏", "亮屏", "音乐", "马达", "视频"],
    )
    values.update(overrides)
    return LteTestConfig(**values)


class FakeChannelManager:
    def has_config(self):
        return True

    def get_band_test_selections(self, band, selected_items):
        assert band == "B3"
        return [
            (
                "三信道测试",
                SimpleNamespace(channels=[1200, 1575], bw=20.0, loss_db=0.0),
            )
        ]


def test_original_test_mode_default_is_preserved():
    config = make_config()
    assert config.test_mode == "默认"


def test_scene_app_defaults_do_not_replace_original_scene_model():
    config = make_config()
    assert config.scenes[0:4] == ["灭屏", "亮屏", "音乐", "马达"]
    assert config.scene_package_name == "com.yunfei.autotestscene"


def test_plan_is_channel_outer_scene_inner():
    config = make_config()
    plan = generate_lte_test_plan(config, FakeChannelManager())

    assert [(item.channel, item.scene) for item in plan] == [
        (1200, "灭屏"),
        (1200, "亮屏"),
        (1200, "音乐"),
        (1200, "马达"),
        (1200, "视频"),
        (1575, "灭屏"),
        (1575, "亮屏"),
        (1575, "音乐"),
        (1575, "马达"),
        (1575, "视频"),
    ]


def test_default_scene_behavior_is_unchanged():
    config = make_config(scenes=None)
    plan = generate_lte_test_plan(config, FakeChannelManager())
    assert all(item.scene == "灭屏" for item in plan)
