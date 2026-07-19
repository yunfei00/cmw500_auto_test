import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app_info import APP_ID, APP_NAME, APP_VERSION, ORGANIZATION_NAME
from ui.main_window import MainWindow


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
