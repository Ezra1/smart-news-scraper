"""Run controls, pipeline stage visualization, and DB sample previews."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QGridLayout,
    QProgressBar,
    QCheckBox,
    QSpinBox,
    QTreeWidget,
    QSizePolicy,
    QSplitter,
)
from PyQt6.QtCore import Qt, pyqtSignal

from src.gui.section_card import SectionCard
from src.gui.theme import SPACING


class RunPipelineView(QWidget):
    """Dedicated run surface: progression, limits, previews."""

    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SPACING["lg"])

        head = QLabel("Run & pipeline")
        head.setObjectName("sectionTitle")
        hf = head.font()
        hf.setPointSize(18)
        hf.setBold(True)
        head.setFont(hf)
        root.addWidget(head)

        ctrl = QHBoxLayout()
        self.start_btn = QPushButton("Start pipeline")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start_requested.emit)
        self.stop_btn = QPushButton("Stop run")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        ctrl.addWidget(self.start_btn)
        ctrl.addWidget(self.stop_btn)
        ctrl.addStretch()
        root.addLayout(ctrl)

        status_card = SectionCard("Run status", "Same line as the status bar at the bottom of the window.")
        row = QHBoxLayout()
        self.status_icon = QLabel("●")
        self.status_icon.setFixedWidth(24)
        self.status_label = QLabel("Idle")
        self.status_label.setWordWrap(True)
        row.addWidget(self.status_icon)
        row.addWidget(self.status_label, 1)
        status_card.body_layout.addLayout(row)
        status_card.setMinimumHeight(72)
        root.addWidget(status_card)

        stages = SectionCard(
            "Pipeline stages",
            "Typical flow: fetch articles, validate content, optional pre-AI filtering, then relevance scoring.",
        )
        grid = QGridLayout()
        self._stage_rows = []
        for i, (key, title) in enumerate(
            [
                ("fetch", "1 · Fetch from API"),
                ("clean", "2 · Validate content"),
                ("gate", "3 · Pre-AI gate"),
                ("analyze", "4 · Relevance scoring"),
            ]
        ):
            icon = QLabel("○")
            lab = QLabel(f"{title}: waiting")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(True)
            bar.setFormat("%p%")
            bar.setMinimumHeight(18)
            bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            grid.addWidget(icon, i, 0)
            grid.addWidget(lab, i, 1)
            grid.addWidget(bar, i, 2)
            self._stage_rows.append((key, icon, lab, bar))
        stages.body_layout.addLayout(grid)
        stages.setMinimumHeight(168)
        root.addWidget(stages)

        prog_card = SectionCard(
            "Scoring progress",
            "Fills only during relevance scoring (after fetch, clean, and gate). Fetch uses the pipeline stage row above.",
        )
        h = QHBoxLayout()
        self.progress_counter = QLabel("0 / 0 articles scored")
        h.addWidget(self.progress_counter)
        h.addStretch()
        prog_card.body_layout.addLayout(h)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setMinimumHeight(18)
        self.progress_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        prog_card.body_layout.addWidget(self.progress_bar)
        prog_card.setMinimumHeight(96)
        root.addWidget(prog_card)

        limits = SectionCard(
            "This run only",
            "These caps apply when you start a run. A run start also copies the full workspace form into memory "
            "and attempts to save the entire configuration file (not only these numbers). "
            "All candidates that pass cleaning and the optional pre-AI gate are sent to relevance scoring.",
        )
        lr = QHBoxLayout()
        lr.addWidget(QLabel("Max URLs to keep after fetch:"))
        self.max_articles_run_spin = QSpinBox()
        self.max_articles_run_spin.setRange(1, 50000)
        lr.addWidget(self.max_articles_run_spin)
        lr.addStretch()
        limits.body_layout.addLayout(lr)
        lq = QHBoxLayout()
        lq.addWidget(QLabel("Max articles per API query (pagination cap):"))
        self.max_articles_per_query_spin = QSpinBox()
        self.max_articles_per_query_spin.setRange(1, 10000)
        lq.addWidget(self.max_articles_per_query_spin)
        lq.addStretch()
        limits.body_layout.addLayout(lq)
        self.processing_enable_prellm = QCheckBox(
            "Enable pre-AI filtering (length, keyword overlap, deduplication)"
        )
        limits.body_layout.addWidget(self.processing_enable_prellm)
        limits.setMinimumHeight(200)
        root.addWidget(limits)

        samples = SectionCard(
            "Database samples",
            "Latest 100 rows per side from the local database. Totals reflect saved rows; during a run they often stay "
            "at zero until the pipeline writes to the database.",
        )
        split = QSplitter(Qt.Orientation.Horizontal)

        raw_col = QWidget()
        rl = QVBoxLayout(raw_col)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(SPACING["sm"])
        raw_head = QLabel("Fetched articles")
        raw_head.setObjectName("subsectionTitle")
        rl.addWidget(raw_head)
        cap_row = QHBoxLayout()
        self.fetch_count_caption = QLabel("Fetch count (this run):")
        self.fetched_count_label = QLabel("0")
        cap_row.addWidget(self.fetch_count_caption)
        cap_row.addWidget(self.fetched_count_label)
        cap_row.addStretch()
        rl.addLayout(cap_row)
        self.raw_preview = QTreeWidget()
        self.raw_preview.setHeaderLabels(["ID", "Title", "URL"])
        self.raw_preview.setMinimumHeight(180)
        rl.addWidget(self.raw_preview, 1)
        rc = QHBoxLayout()
        rc.addWidget(QLabel("All rows saved in DB:"))
        self.raw_count_label = QLabel("0")
        rc.addWidget(self.raw_count_label)
        rc.addStretch()
        self.clear_raw_btn = QPushButton("Clear fetched articles…")
        rc.addWidget(self.clear_raw_btn)
        rl.addLayout(rc)
        split.addWidget(raw_col)

        cl_col = QWidget()
        cl = QVBoxLayout(cl_col)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(SPACING["sm"])
        kept_head = QLabel("Kept after scoring")
        kept_head.setObjectName("subsectionTitle")
        cl.addWidget(kept_head)
        self.cleaned_preview = QTreeWidget()
        self.cleaned_preview.setHeaderLabels(["ID", "Title", "Score"])
        self.cleaned_preview.setMinimumHeight(180)
        cl.addWidget(self.cleaned_preview, 1)
        cc = QHBoxLayout()
        cc.addWidget(QLabel("All rows saved in DB:"))
        self.cleaned_count_label = QLabel("0")
        cc.addWidget(self.cleaned_count_label)
        cc.addStretch()
        self.clear_kept_btn = QPushButton("Clear kept articles…")
        cc.addWidget(self.clear_kept_btn)
        cl.addLayout(cc)
        split.addWidget(cl_col)

        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setMinimumHeight(220)
        samples.body_layout.addWidget(split)
        root.addWidget(samples, 1)

        inspect = SectionCard(
            "Last run inspection",
            "Aggregate counts and settings from the last finished run when telemetry is present (same data as Diagnostics, compact view).",
        )
        self.inspection_browser = QLabel(
            "Complete a pipeline run to see aggregate counts and limits here."
        )
        self.inspection_browser.setWordWrap(True)
        self.inspection_browser.setObjectName("muted")
        self.inspection_browser.setTextFormat(Qt.TextFormat.RichText)
        self.inspection_browser.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.inspection_browser.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.MinimumExpanding,
        )
        self.inspection_browser.setMinimumHeight(80)
        inspect.body_layout.addWidget(self.inspection_browser)
        inspect.setMinimumHeight(120)
        root.addWidget(inspect)

    def stage_widgets(self, key: str):
        for k, icon, lab, bar in self._stage_rows:
            if k == key:
                return icon, lab, bar
        return None, None, None

    def set_inspection_html(self, html: str) -> None:
        self.inspection_browser.setText(html)
