from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget


class CollapsibleGroup(QWidget):
    """Simple reusable collapsible container for future dense configuration panels."""

    def __init__(self, title: str, content: QWidget | None = None, expanded: bool = True) -> None:
        super().__init__()
        self.toggle_button = QPushButton(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.setStyleSheet("QPushButton { text-align: left; font-weight: bold; }")

        self.content_widget = content or QWidget()
        self.content_widget.setVisible(expanded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.content_widget)

        self.toggle_button.toggled.connect(self._set_expanded)
        self._set_expanded(expanded)

    def _set_expanded(self, expanded: bool) -> None:
        self.content_widget.setVisible(expanded)
        prefix = "[-]" if expanded else "[+]"
        title = self.toggle_button.text()
        if title.startswith(("[-] ", "[+] ")):
            title = title[4:]
        self.toggle_button.setText(f"{prefix} {title}")

    def setContentWidget(self, content: QWidget) -> None:
        old_content = self.content_widget
        self.layout().replaceWidget(old_content, content)
        old_content.setParent(None)
        self.content_widget = content
        self.content_widget.setVisible(self.toggle_button.isChecked())

    def setExpanded(self, expanded: bool) -> None:
        self.toggle_button.setChecked(expanded)

    def isExpanded(self) -> bool:
        return self.toggle_button.isChecked()
