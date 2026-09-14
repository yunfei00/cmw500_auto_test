from __future__ import annotations

from typing import Any

from core.scpi_template import ScpiTemplateManager


_TDD_BANDS = set(range(33, 54))
_PATCHED = False


def _duplex_mode_from_context(context: dict[str, Any]) -> str:
    band = str(context.get("band", "B3")).strip()
    try:
        number = int(band.lstrip("Bb"))
    except ValueError:
        number = 3
    return "TDD" if number in _TDD_BANDS else "FDD"


def apply_scpi_duplex_compat() -> None:
    """Provide {duplex_mode} to SCPI templates during validation and rendering.

    The LTE V1 template now uses {duplex_mode}. RealCMW500 supplies it at runtime,
    but ScpiTemplateManager.validate_for_real_run() renders commands with its own
    static validation context. This hook keeps validation and runtime rendering
    consistent without weakening template validation.
    """

    global _PATCHED
    if _PATCHED:
        return
    _PATCHED = True

    original_render_command = ScpiTemplateManager.render_command

    def render_command_with_duplex(
        self: ScpiTemplateManager,
        command: str,
        context: dict[str, Any],
    ) -> str:
        full_context = dict(context)
        full_context.setdefault("duplex_mode", _duplex_mode_from_context(full_context))
        return original_render_command(self, command, full_context)

    ScpiTemplateManager.render_command = render_command_with_duplex  # type: ignore[method-assign]
