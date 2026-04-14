"""Reusable titled card container for grouped settings."""

from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel, QWidget

from src.gui.theme import SPACING


class SectionCard(QFrame):
    """A framed section with optional subtitle; body via .body_layout."""

    def __init__(self, title: str, subtitle: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(SPACING["lg"], SPACING["md"], SPACING["lg"], SPACING["lg"])
        outer.setSpacing(SPACING["md"])

        head = QLabel(title)
        head.setObjectName("sectionTitle")
        outer.addWidget(head)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("muted")
            sub.setWordWrap(True)
            outer.addWidget(sub)

        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(SPACING["md"])
        outer.addLayout(self.body_layout)
