"""Structured run summary, issue list, and raw logs."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QTextBrowser,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QTextCursor, QFont

from src.gui.section_card import SectionCard
from src.gui.theme import SPACING


class DiagnosticsView(QWidget):
    _ISSUES_EMPTY_ROLE = Qt.ItemDataRole.UserRole + 64  # marks synthetic empty-state row

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING["lg"])

        title = QLabel("Diagnostics")
        title.setObjectName("sectionTitle")
        tf = title.font()
        tf.setPointSize(18)
        tf.setBold(True)
        title.setFont(tf)
        layout.addWidget(title)

        top = SectionCard(
            "Last run summary (structured)",
            "Markdown outline: fetch → validate → pre-AI gate → scoring → output, using the last completed run in this session.",
        )
        self.structured_browser = QTextBrowser()
        self.structured_browser.setReadOnly(True)
        self.structured_browser.setMinimumHeight(160)
        self.structured_browser.setPlaceholderText(
            "No completed run in this session yet, or the last run did not produce summary text."
        )
        top.body_layout.addWidget(self.structured_browser)
        layout.addWidget(top)

        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)

        issues_wrap = SectionCard(
            "Warnings and errors",
            "Lines parsed from logger severity in this session (not a substitute for the full log below).",
        )
        self.issues_list = QListWidget()
        self.issues_list.setMaximumHeight(140)
        self._add_issues_placeholder_row()
        issues_wrap.body_layout.addWidget(self.issues_list)
        split.addWidget(issues_wrap)

        raw_wrap = SectionCard(
            "Verbose log (session)",
            "Unstructured logger output; use for stack traces, timing, and anything missing from the summary above.",
        )
        self.raw_log = QPlainTextEdit()
        self.raw_log.setReadOnly(True)
        self.raw_log.setPlaceholderText("Log lines appear here when a run is active or when logging emits output.")
        mono = QFont("Consolas, Monaco, monospace")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.raw_log.setFont(mono)
        self.raw_log.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        raw_wrap.body_layout.addWidget(self.raw_log)
        btn_row = QHBoxLayout()
        clear_btn = QPushButton("Clear log view")
        clear_btn.clicked.connect(self.clear_raw)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        raw_wrap.body_layout.addLayout(btn_row)
        split.addWidget(raw_wrap)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)

    def clear_raw(self) -> None:
        self.raw_log.clear()

    def clear_issues(self) -> None:
        self.issues_list.clear()
        self._add_issues_placeholder_row()

    def _add_issues_placeholder_row(self) -> None:
        ph = QListWidgetItem("No warnings or errors recorded yet.")
        ph.setFlags(Qt.ItemFlag.NoItemFlags)
        ph.setData(self._ISSUES_EMPTY_ROLE, True)
        self.issues_list.addItem(ph)

    def set_structured_markdown(self, text: str) -> None:
        self.structured_browser.setMarkdown(text or "")

    def append_issue(self, severity: str, message: str) -> None:
        for i in range(self.issues_list.count() - 1, -1, -1):
            it = self.issues_list.item(i)
            if it and it.data(self._ISSUES_EMPTY_ROLE):
                self.issues_list.takeItem(i)
                break
        item = QListWidgetItem(f"[{severity.upper()}] {message}")
        if severity.lower() == "error":
            item.setForeground(QColor("#E05555"))
        elif severity.lower() == "warning":
            item.setForeground(QColor("#E8A54B"))
        self.issues_list.addItem(item)
        self.issues_list.scrollToBottom()

    def append_raw_line(self, message: str) -> None:
        if not message:
            return
        self.raw_log.appendPlainText(message)
        self._trim_raw_blocks()

    def _trim_raw_blocks(self) -> None:
        doc = self.raw_log.document()
        max_blocks = 2500
        if doc.blockCount() <= max_blocks:
            return
        cur = self.raw_log.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.Start)
        for _ in range(doc.blockCount() - max_blocks):
            cur.select(QTextCursor.SelectionType.BlockUnderCursor)
            cur.removeSelectedText()
            cur.deleteChar()
