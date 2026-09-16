from __future__ import annotations

"""Remember and restore the last successfully loaded LTE channel configuration."""

from pathlib import Path

from core.lte_channel_config import LTEChannelConfigError, default_lte_channel_config_path
from ui.left_panel import LeftPanel

LAST_LTE_CHANNEL_CONFIG_KEY = "lte/last_channel_config_file"

_original_init_lte_channel_config = LeftPanel._init_lte_channel_config
_original_load_lte_channel_config_file = LeftPanel._load_lte_channel_config_file


def _init_lte_channel_config(self: LeftPanel) -> None:
    saved_text = str(self.settings.value(LAST_LTE_CHANNEL_CONFIG_KEY, "", str)).strip()
    if saved_text:
        saved_path = Path(saved_text)
        if saved_path.is_file():
            try:
                self.lte_channel_manager.load(saved_path)
                bands = self.lte_channel_manager.get_all_bands()
                self.channel_file_edit.setText(str(saved_path))
                self._log("INFO", f"已自动加载上次使用的 LTE 信道配置：{saved_path}")
                self._log("INFO", f"已配置 Band：{', '.join(bands)}")
                self._auto_select_configured_bands(bands)
                return
            except Exception as exc:
                self._log("WARNING", f"上次 LTE 信道配置加载失败，将使用默认配置：{exc}")
        else:
            self._log("WARNING", f"上次 LTE 信道配置文件不存在，将使用默认配置：{saved_path}")

    # Do not keep a failed remembered path inside the manager before fallback.
    self.lte_channel_manager.path = default_lte_channel_config_path()
    _original_init_lte_channel_config(self)


def _load_lte_channel_config_file(self: LeftPanel, path: str) -> None:
    config_path = path.strip()
    if not config_path:
        _original_load_lte_channel_config_file(self, path)
        return

    _original_load_lte_channel_config_file(self, path)

    # The original loader reports failures to the UI and returns normally, so only
    # persist when a valid band set was actually loaded from the requested path.
    try:
        requested = Path(config_path).resolve()
        loaded = Path(self.lte_channel_manager.path).resolve()
        bands = self.lte_channel_manager.get_all_bands()
    except Exception:
        return
    if requested != loaded or not bands:
        return

    self.channel_file_edit.setText(config_path)
    self.settings.setValue(LAST_LTE_CHANNEL_CONFIG_KEY, config_path)
    self.settings.sync()
    self._log("INFO", f"已记住 LTE 信道配置文件，下次启动将自动加载：{config_path}")


def apply_lte_channel_config_persistence() -> None:
    if getattr(LeftPanel, "_lte_channel_config_persistence_applied", False):
        return
    LeftPanel._init_lte_channel_config = _init_lte_channel_config
    LeftPanel._load_lte_channel_config_file = _load_lte_channel_config_file
    LeftPanel._lte_channel_config_persistence_applied = True
