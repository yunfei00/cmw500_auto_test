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
    items: list[TestItem] = []
    index = 1

    if config.data:
        for row in config.data:
            band = str(row.get("band", "")).strip()
            channel_raw = row.get("channel")
            if not band or channel_raw is None:
                continue

            channel = int(channel_raw)
            loss_db = _row_loss_db(row, band, lte_channel_manager)
            items.append(
                TestItem(
                    index=index,
                    mode="LTE",
                    band=band,
                    channel=channel,
                    channel_type=str(row.get("desc", "")) or "固定信道",
                    test_mode=config.test_mode,
                    rx_level=config.start_level,
                    bw=_parse_optional_float(row.get("bw")),
                    loss_db=loss_db,
                )
            )
            index += 1
        return items

    for band in bands:
        selections = lte_channel_manager.get_band_test_selections(band, config.lte_test_items)
        for test_item_name, selection in selections:
            channel_type = _channel_type_label(test_item_name, selection)
            for channel in selection.channels:
                items.append(
                    TestItem(
                        index=index,
                        mode="LTE",
                        band=band,
                        channel=channel,
                        channel_type=channel_type,
                        test_mode=config.test_mode,
                        rx_level=config.start_level,
                        bw=selection.bw,
                        loss_db=selection.loss_db,
                    )
                )
                index += 1

    return items


def _channel_type_label(test_item: str, selection: LteTestChannelSelection) -> str:
    if len(selection.channels) > 1:
        return f"{test_item}({len(selection.channels)}信道)"
    return test_item


def _parse_optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _row_loss_db(
    row: dict[str, str | int | float],
    band: str,
    manager: LTEChannelConfigManager | None,
) -> float:
    for key in ("loss_db", "loss", "线损"):
        value = row.get(key)
        if value not in (None, ""):
            return float(value)
    if manager is not None and manager.has_config():
        try:
            return float(manager.get_band_config(band).loss_db)
        except KeyError:
            pass
    return 0.0
