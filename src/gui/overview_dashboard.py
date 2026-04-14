"""Overview: system status, config snapshot, last run, quick navigation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QSizePolicy,
)
from PyQt6.QtCore import Qt

from src.gui.section_card import SectionCard
from src.gui.run_metrics_format import format_run_metrics_plain
from src.gui.theme import SPACING

if TYPE_CHECKING:
    from src.qt_gui import NewsScraperGUI


class OverviewDashboard(QWidget):
    """Primary landing view."""

    def __init__(self, main: "NewsScraperGUI", parent=None):
        super().__init__(parent)
        self._main = main
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACING["lg"])

        title = QLabel("Overview")
        title.setObjectName("sectionTitle")
        f = title.font()
        f.setPointSize(18)
        f.setBold(True)
        title.setFont(f)
        root.addWidget(title)

        row = QHBoxLayout()
        row.setSpacing(SPACING["lg"])

        status_card = SectionCard("System status", "Whether keys are set, validation passes, and a run can start.")
        self._status_body = QLabel("Loading…")
        self._status_body.setWordWrap(True)
        self._status_body.setObjectName("muted")
        status_card.body_layout.addWidget(self._status_body)
        row.addWidget(status_card, 1)

        cfg_card = SectionCard(
            "Workspace",
            "Draft vs saved: whether the form matches the configuration file after the last successful write.",
        )
        self._config_badge = QLabel("")
        self._config_badge.setObjectName("badge")
        cfg_card.body_layout.addWidget(self._config_badge)
        self._config_detail = QLabel("")
        self._config_detail.setWordWrap(True)
        self._config_detail.setObjectName("muted")
        cfg_card.body_layout.addWidget(self._config_detail)
        go_ws = QPushButton("Open Workspace")
        go_ws.clicked.connect(lambda: self._main._navigate_to(2))
        cfg_card.body_layout.addWidget(go_ws)
        row.addWidget(cfg_card, 1)

        root.addLayout(row)

        run_card = SectionCard(
            "Last completed run",
            "Funnel-style counts from the most recent finished pipeline run in this session (not the run in progress).",
        )
        self._run_summary = QTextBrowser()
        self._run_summary.setOpenExternalLinks(False)
        self._run_summary.setReadOnly(True)
        self._run_summary.setMinimumHeight(220)
        self._run_summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._run_summary.setPlaceholderText("Complete a pipeline run to see a structured summary here.")
        self._run_summary.setStyleSheet("QTextBrowser { font-family: 'Segoe UI', 'Ubuntu', sans-serif; }")
        run_card.body_layout.addWidget(self._run_summary)

        nav_row = QHBoxLayout()
        b_run = QPushButton("Open Run & pipeline")
        b_run.setObjectName("primary")
        b_run.clicked.connect(lambda: self._main._navigate_to(1))
        b_res = QPushButton("Open Results")
        b_res.clicked.connect(lambda: self._main._navigate_to(4))
        b_log = QPushButton("Open Diagnostics")
        b_log.clicked.connect(lambda: self._main._navigate_to(3))
        nav_row.addWidget(b_run)
        nav_row.addWidget(b_res)
        nav_row.addWidget(b_log)
        nav_row.addStretch()
        run_card.body_layout.addLayout(nav_row)

        root.addWidget(run_card, 1)

        hint = QLabel(
            "Workflow: edit in Workspace, use Save workspace… when you want an explicit file write, then start from "
            "Run & pipeline. A run always copies the current form into memory for the worker and attempts to save "
            "that full configuration to disk before starting (if save fails, the run still proceeds in memory)."
        )
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        root.addWidget(hint)

    def refresh(self) -> None:
        m = self._main
        # Status
        missing = m._missing_required_keys()
        if missing:
            self._status_body.setText(
                "Not ready: missing API keys in the active configuration. "
                "Add keys under Workspace → API connections, then save."
            )
        elif not m.config_manager.validate():
            self._status_body.setText("Configuration validation failed. Review Workspace settings.")
        else:
            terms = m.search_manager.get_search_terms()
            if not terms:
                self._status_body.setText("Ready, but no search terms are defined. Add terms under Workspace.")
            elif getattr(m, "_processing", False):
                self._status_body.setText("A pipeline run is in progress.")
            else:
                self._status_body.setText("Ready to run the pipeline.")

        dirty = m._workspace_is_dirty()
        self._config_badge.setText("Draft" if dirty else "Saved")
        self._config_detail.setText(
            "The form differs from the last configuration snapshot (successful write to your config file)."
            if dirty
            else "The form matches the last snapshot (API key values are not part of the comparison)."
        )

        last = getattr(m, "_last_pipeline_result", None)
        self._run_summary.setPlainText(format_run_metrics_plain(last))
