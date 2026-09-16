import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app_info import APP_ID, APP_NAME, APP_VERSION, ORGANIZATION_NAME
from core.lte_fast_scan_policy import apply_lte_fast_scan_policy
from core.lte_channel_resilience import apply_lte_channel_resilience
from core.lte_channel_config_persistence import apply_lte_channel_config_persistence
from core.lte_start_level_policy import apply_lte_start_level_policy
from core.lte_operator_summary_policy import apply_lte_operator_summary_policy

# Apply the LTE V1 scan behavior before MainWindow/LeftPanel instances are created.
apply_lte_fast_scan_policy()
# A single channel failure is recorded and skipped; RF-safety failures still abort.
apply_lte_channel_resilience()
# Restore the last successfully loaded LTE channel configuration on next startup.
apply_lte_channel_config_persistence()
# The fast scan no longer uses the hidden legacy stop level.
apply_lte_start_level_policy()
# Keep operator logs explicit and expose the terminal FINE-pass BLER in summaries.
apply_lte_operator_summary_policy()

from ui.main_window import MainWindow  # noqa: E402


def verify_runtime_dependencies() -> None:
    """Exercise dependencies that are otherwise loaded only on hardware paths."""

    import pyvisa
    import pyvisa_py  # noqa: F401 - verifies the bundled pure-Python backend

    resource_manager = pyvisa.ResourceManager("@py")
    resource_manager.close()


def main() -> int:
    smoke_test = "--smoke-test" in sys.argv
    if smoke_test:
        verify_runtime_dependencies()
    qt_args = [argument for argument in sys.argv if argument != "--smoke-test"]
    app = QApplication(qt_args)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(ORGANIZATION_NAME)

    window = MainWindow()
    window.show()
    if smoke_test:
        QTimer.singleShot(0, window.close)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
