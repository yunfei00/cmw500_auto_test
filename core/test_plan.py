from __future__ import annotations

from core.lte_channel_config import LTEChannelConfigManager, LteTestChannelSelection
from core.models import LteTestConfig, TestItem


def generate_lte_test_plan(
    config: LteTestConfig,
    lte_channel_manager: LTEChannelConfigManager | None = None,
) -> list[TestItem]:
    if lte_channel_manager is None or not lte_channel_manager.has_config():
        return []

    bands = config.selected_bands or []
    levels = _generate_levels(config.start_level, config.stop_level, config.min_step)
    items: list[TestItem] = []
    index = 1

    for band in bands:
        selections = lte_channel_manager.get_band_test_selections(band, config.lte_test_items)
        for test_item_name, selection in selections:
            channel_type = _channel_type_label(test_item_name, selection)
            for channel in selection.channels:
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
                            bw=selection.bw,
                        )
                    )
                    index += 1

    return items


def _channel_type_label(test_item: str, selection: LteTestChannelSelection) -> str:
    if len(selection.channels) > 1:
        return f"{test_item}({len(selection.channels)}信道)"
    return test_item


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
