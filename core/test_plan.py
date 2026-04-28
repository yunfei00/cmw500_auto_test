from __future__ import annotations

from core.models import LteTestConfig, TestItem


DEFAULT_LTE_CHANNELS = {
    "B1": {"低频点": 0, "中频点": 300, "高频点": 599, "Top频点": 599},
    "B3": {"低频点": 1200, "中频点": 1575, "高频点": 1949, "Top频点": 1949},
    "B5": {"低频点": 2400, "中频点": 2525, "高频点": 2649, "Top频点": 2649},
    "B7": {"低频点": 2750, "中频点": 3100, "高频点": 3449, "Top频点": 3449},
    "B8": {"低频点": 3450, "中频点": 3625, "高频点": 3799, "Top频点": 3799},
    "B20": {"低频点": 6150, "中频点": 6300, "高频点": 6449, "Top频点": 6449},
    "B28": {"低频点": 9210, "中频点": 9435, "高频点": 9659, "Top频点": 9659},
    "B38": {"低频点": 37750, "中频点": 38000, "高频点": 38250, "Top频点": 38250},
    "B40": {"低频点": 38650, "中频点": 39150, "高频点": 39650, "Top频点": 39650},
    "B41": {"低频点": 39650, "中频点": 40620, "高频点": 41589, "Top频点": 41589},
}

FALLBACK_LTE_CHANNELS = {"低频点": 100, "中频点": 200, "高频点": 300, "Top频点": 300}
CUSTOM_CHANNEL_TYPE = "自定义频点"


def generate_lte_test_plan(config: LteTestConfig) -> list[TestItem]:
    bands = config.selected_bands or ["B3"]
    channel_types = config.selected_channel_types or ["中频点"]
    normal_channel_types = [channel_type for channel_type in channel_types if channel_type != CUSTOM_CHANNEL_TYPE]
    if not normal_channel_types and not config.custom_channels:
        normal_channel_types = ["中频点"]

    levels = _generate_levels(config.start_level, config.stop_level, config.min_step)
    items: list[TestItem] = []
    index = 1

    for band in bands:
        channel_map = DEFAULT_LTE_CHANNELS.get(band, FALLBACK_LTE_CHANNELS)
        for channel_type in normal_channel_types:
            channel = channel_map.get(channel_type, FALLBACK_LTE_CHANNELS.get(channel_type, 200))
            for level in levels:
                items.append(
                    TestItem(
                        index=index,
                        mode="LTE",
                        band=band,
                        channel=channel,
                        channel_type=channel_type,
                        test_mode=config.test_mode,
                        rx_level=level,
                    )
                )
                index += 1

        if CUSTOM_CHANNEL_TYPE in channel_types and config.custom_channels:
            for channel in config.custom_channels:
                for level in levels:
                    items.append(
                        TestItem(
                            index=index,
                            mode="LTE",
                            band=band,
                            channel=channel,
                            channel_type=CUSTOM_CHANNEL_TYPE,
                            test_mode=config.test_mode,
                            rx_level=level,
                        )
                    )
                    index += 1

    return items


def _generate_levels(start_level: float, stop_level: float, min_step: float) -> list[float]:
    step = abs(min_step) if min_step else 1.0
    step = step or 1.0

    levels: list[float] = []
    current = start_level
    if start_level >= stop_level:
        while current >= stop_level:
            levels.append(round(current, 2))
            current -= step
    else:
        while current <= stop_level:
            levels.append(round(current, 2))
            current += step

    return levels
