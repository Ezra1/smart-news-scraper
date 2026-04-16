"""PyQt6 desktop interface for the Smart News Scraper.

The GUI lets users configure API keys, manage search terms, launch the end-to-end
scraping pipeline, and review/export relevance-scored articles. Launch from the
repository root with:

    python -m src.qt_gui

Navigation: Overview, Run & pipeline, Workspace, Diagnostics, Results.
"""

from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtWidgets import (
    QMainWindow, QApplication, QWidget, QPushButton, QLabel, QVBoxLayout,
    QHBoxLayout, QStackedWidget, QLineEdit, QFrame, QListWidget, QProgressBar,
    QScrollArea, QTreeWidget, QTreeWidgetItem, QMessageBox, QFileDialog,
    QComboBox, QSlider, QInputDialog, QGroupBox, QMenu, QGridLayout, QTextEdit,
    QRadioButton, QDateEdit, QButtonGroup, QCheckBox, QSpinBox, QToolButton, QStyle,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QSizePolicy,
    QSplitter,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate, QObject, QSize
from PyQt6.QtGui import QFont, QIcon, QAction
from pathlib import Path
from datetime import datetime, timedelta
import asyncio
import json
import logging
import re
import sys
from queue import Queue
from copy import deepcopy
import html

from src.logger_config import setup_logging
from src.config import ConfigManager
from src.database_manager import DatabaseManager, ArticleManager, SearchTermManager
from src.pipeline_manager import PipelineManager
from src.pipeline_result import PipelineRunResult
from src.pipeline_factory import create_pipeline
from src.api_validator import validate_news_api_key, validate_openai_api_key
from src.openai_client import get_client
from src.gui.flow_layout import FlowLayout
from src.gui.status_parser import StatusParser, StatusUpdate
from src.gui.processing_state import ProcessingState
from src.gui.date_range_widget import DateRangeWidget
from src.gui.constants import (
    FILTER_PRESET_MAP,
    RESULTS_TABLE_COLUMNS,
    RESULTS_TABLE_COLUMNS_ANALYST,
    SUPPORTED_LANGUAGES,
)
from src.gui.theme import app_stylesheet, SPACING
from src.gui.overview_dashboard import OverviewDashboard
from src.gui.diagnostics_view import DiagnosticsView
from src.gui.run_pipeline_view import RunPipelineView
from src.gui.run_metrics_format import format_run_metrics_markdown, format_run_metrics_plain
from src.utils.article_normalization import extract_source_name

logger = setup_logging(__name__)


class LanguageChipButton(QPushButton):
    """Checkable pill-style control for selecting a query expansion language."""

    def __init__(self, label: str, parent: QWidget | None = None):
        super().__init__(label, parent)
        self.setCheckable(True)
        self.setObjectName("language_chip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)


class GuiLogBridge(QObject):
    """Qt signal bridge for forwarding logging lines to the UI thread."""
    log_message = pyqtSignal(str)


class GuiLogHandler(logging.Handler):
    """Logging handler that emits formatted records over a Qt signal."""

    def __init__(self, bridge: GuiLogBridge):
        super().__init__()
        self.bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            self.bridge.log_message.emit(message)
        except Exception:
            self.handleError(record)


class ApiValidationWorker(QThread):
    finished = pyqtSignal(tuple)  # (news_valid, openai_valid, error_message)

    def __init__(self, news_key: str, openai_key: str):
        super().__init__()
        self.news_key = news_key
        self.openai_key = openai_key

    def run(self):
        try:
            # Validate TheNewsAPI token
            news_valid = asyncio.run(validate_news_api_key(self.news_key))
            
            # Validate OpenAI API
            openai_valid = validate_openai_api_key(self.openai_key)
            
            self.finished.emit((news_valid, openai_valid, None))
        except Exception as e:
            self.finished.emit((False, False, str(e)))

class ProcessingWorker(QThread):
    progress_updated = pyqtSignal(int, int)
    status_updated = pyqtSignal(str, bool, bool, bool)
    completed = pyqtSignal(object)

    def __init__(self, pipeline: PipelineManager, search_terms: list, date_params: dict | None = None):
        super().__init__()
        self.pipeline = pipeline
        self.search_terms = search_terms
        self.date_params = date_params or {}
        self._is_running = True
        
        # Connect pipeline callbacks
        self.pipeline.set_callbacks(
            progress_callback=lambda current, total: self.progress_updated.emit(current, total),
            status_callback=lambda msg, err, warn, succ: self.status_updated.emit(msg, err, warn, succ)
        )

    def run(self):
        asyncio.run(self._process_pipeline())

    async def _process_pipeline(self):
        try:
            results = await self.pipeline.execute_pipeline(self.search_terms, date_params=self.date_params)
            self.completed.emit(results)
            if getattr(self.pipeline, "cancelled", False):
                self.status_updated.emit("Processing stopped by user", False, True, False)
            elif isinstance(results, PipelineRunResult):
                if results.completed_successfully:
                    self.status_updated.emit("Processing completed successfully.", False, False, True)
                else:
                    msg = results.completion_detail or "Processing completed with errors."
                    self.status_updated.emit(msg, True, False, True)
            else:
                self.status_updated.emit("Processing completed successfully.", False, False, True)
        except Exception as e:
            logger.error(f"Worker error: {e}")
            self.status_updated.emit(f"Error: {str(e)}", True, False, False)

    def stop(self):
        self._is_running = False
        try:
            if self.pipeline:
                self.pipeline.cancel()
        except Exception as e:
            logger.error(f"Error while cancelling pipeline: {e}")


class NewsScraperGUI(QMainWindow):
    def __init__(self):
        """Initialize the main window, services, and processing pipeline.

        Sets up validators, config/database managers, search/article managers,
        the processing queue, and GUI scaffolding. Processor creation is deferred
        until configuration is validated to avoid stale API keys.
        """
        super().__init__()
        self.setWindowTitle("Smart News Scraper")
        self.setMinimumSize(1200, 800)

        # Initialize base components via shared factory to keep CLI/GUI consistent
        pipeline_components = create_pipeline(include_processor=False)
        self.validator = pipeline_components["validator"]
        self.config_manager = pipeline_components["config"]
        self.db_manager = pipeline_components["db_manager"]
        self.search_manager = SearchTermManager(self.db_manager)
        self.article_manager = ArticleManager(self.db_manager)
        self.processing_queue = Queue()
        self._processing = False
        self.worker = None
        
        # Initialize pipeline without processor
        self.pipeline = PipelineManager(self.db_manager, self.config_manager)
        self.status_parser = StatusParser()
        self.state = ProcessingState()
        self._gui_log_bridge = GuiLogBridge()
        # Log lines are shown on Diagnostics; bridge connected after diagnostics_view exists.
        self._gui_log_handler = None
        self._gui_log_targets = []
        
        # Defer processor initialization until needed
        self.processor = None
        self.results_exported_this_session = False
        self._last_pipeline_result: Optional[PipelineRunResult] = None
        self._saved_workspace_snapshot: dict[str, Any] = {}
        # progress_callback is reused for fetch (queries), clean (articles), then analyze (articles).
        self._allow_llm_progress_bar: bool = False

        # Setup UI (stylesheet before widgets for consistent polish)
        self._setup_styles()
        self._setup_ui()
        self._snapshot_saved_workspace()
        self._connect_workspace_dirty_signals()
        self._show_startup_validation_hint()

    def _missing_required_keys(self) -> list[str]:
        """Return required config keys that are currently missing."""
        required_keys = ("NEWS_API_KEY", "OPENAI_API_KEY")
        return [key for key in required_keys if not self.config_manager.get(key)]

    def _show_startup_validation_hint(self):
        """Show a non-blocking startup hint when required keys are missing."""
        missing_keys = self._missing_required_keys()
        if not missing_keys:
            return

        missing_labels = ", ".join(key.replace("_", " ").title() for key in missing_keys)
        self.statusBar().showMessage(
            f"Configuration needed: add {missing_labels} under Workspace before running the pipeline."
        )

    def _navigate_to(self, index: int) -> None:
        if not hasattr(self, "_nav_list"):
            return
        self._nav_list.blockSignals(True)
        self._nav_list.setCurrentRow(index)
        self._nav_list.blockSignals(False)
        self._stack.setCurrentIndex(index)

    def _on_nav_changed(self, index: int) -> None:
        if index < 0:
            return
        self._stack.setCurrentIndex(index)
        if index == 0 and hasattr(self, "overview_dashboard"):
            self.overview_dashboard.refresh()

    def _make_tab_scroll(self, content: QWidget) -> QScrollArea:
        """Wrap a stacked page so vertical/horizontal scrollbars appear when content overflows."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(content)
        return scroll

    def _setup_ui(self):
        """Build sidebar navigation and stacked primary views."""
        central_widget = QWidget()
        outer = QHBoxLayout(central_widget)
        outer.setContentsMargins(SPACING["lg"], SPACING["lg"], SPACING["lg"], SPACING["lg"])
        outer.setSpacing(SPACING["md"])

        self._nav_list = QListWidget()
        self._nav_list.setObjectName("sidebar")
        self._nav_list.setFixedWidth(216)
        for label in (
            "Overview",
            "Run & pipeline",
            "Workspace",
            "Diagnostics",
            "Results",
        ):
            self._nav_list.addItem(label)
        self._nav_list.currentRowChanged.connect(self._on_nav_changed)
        outer.addWidget(self._nav_list)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)

        self.overview_dashboard = OverviewDashboard(self)
        self._stack.addWidget(self._make_tab_scroll(self.overview_dashboard))

        self.run_page = RunPipelineView()
        self.run_page.start_requested.connect(self._start_processing)
        self.run_page.stop_requested.connect(self._stop_processing)
        self.start_btn = self.run_page.start_btn
        self.stop_btn = self.run_page.stop_btn
        self.status_icon = self.run_page.status_icon
        self.status_label = self.run_page.status_label
        self.progress_bar = self.run_page.progress_bar
        self.progress_counter = self.run_page.progress_counter
        self.raw_preview = self.run_page.raw_preview
        self.cleaned_preview = self.run_page.cleaned_preview
        self.raw_count_label = self.run_page.raw_count_label
        self.cleaned_count_label = self.run_page.cleaned_count_label
        self.fetch_count_caption = self.run_page.fetch_count_caption
        self.fetched_count_label = self.run_page.fetched_count_label
        self.processing_enable_prellm = self.run_page.processing_enable_prellm
        self.max_articles_run_spin = self.run_page.max_articles_run_spin
        self.max_articles_per_query_spin = self.run_page.max_articles_per_query_spin
        self.processing_enable_prellm.blockSignals(True)
        self.processing_enable_prellm.setChecked(
            bool(self.config_manager.get("PRELLM_ENABLE_FILTERING", False))
        )
        self.processing_enable_prellm.blockSignals(False)
        self.processing_enable_prellm.toggled.connect(self._on_processing_prellm_filtering_toggled)
        self.max_articles_run_spin.setValue(int(self.config_manager.get("FETCH_MAX_ARTICLES_PER_RUN", 2000)))
        self.max_articles_per_query_spin.setValue(
            int(self.config_manager.get("FETCH_MAX_ARTICLES_PER_QUERY", 500))
        )
        self.run_page.clear_raw_btn.clicked.connect(self._clear_raw_articles)
        self.run_page.clear_kept_btn.clicked.connect(self._clear_cleaned_articles)
        self._stack.addWidget(self._make_tab_scroll(self.run_page))
        self._apply_prellm_filtering_controls_enabled(self.processing_enable_prellm.isChecked())

        workspace_host = QWidget()
        ws_layout = QVBoxLayout(workspace_host)
        ws_layout.setContentsMargins(SPACING["md"], SPACING["md"], SPACING["md"], SPACING["md"])
        ws_layout.setSpacing(SPACING["lg"])
        ws_title = QLabel("Workspace")
        tf = ws_title.font()
        tf.setPointSize(18)
        tf.setBold(True)
        ws_title.setFont(tf)
        ws_layout.addWidget(ws_title)

        self._workspace_state_banner = QLabel("")
        self._workspace_state_banner.setObjectName("muted")
        self._workspace_state_banner.setWordWrap(True)
        ws_layout.addWidget(self._workspace_state_banner)

        self._create_config_tab(ws_layout)
        self._create_search_terms_tab(ws_layout)
        self._create_filtering_controls_tab(ws_layout)

        footer = QHBoxLayout()
        save_ws = QPushButton("Save workspace…")
        save_ws.setObjectName("primary")
        save_ws.clicked.connect(self._save_config)
        reset_ws = QPushButton("Reset draft")
        reset_ws.clicked.connect(self._reset_workspace_draft)
        reload_ws = QPushButton("Reload from disk")
        reload_ws.clicked.connect(self._reload_workspace_from_disk)
        save_filter = QPushButton("Save gate rules only")
        save_filter.clicked.connect(self._save_filtering_settings)
        footer.addWidget(save_ws)
        footer.addWidget(reset_ws)
        footer.addWidget(reload_ws)
        footer.addStretch()
        footer.addWidget(save_filter)
        ws_layout.addLayout(footer)

        self._stack.addWidget(self._make_tab_scroll(workspace_host))

        self.diagnostics_view = DiagnosticsView()
        self._stack.addWidget(self._make_tab_scroll(self.diagnostics_view))
        self._gui_log_bridge.log_message.connect(self._append_run_log_line)

        self._create_results_tab()
        self._stack.addWidget(self._make_tab_scroll(self.results_host))

        self.setCentralWidget(central_widget)
        self._nav_list.setCurrentRow(0)
        self._stack.setCurrentIndex(0)
        self.statusBar().showMessage("Ready")
        self._update_workspace_state_banner()
        self._update_previews()
        self.overview_dashboard.refresh()

    def _setup_styles(self):
        # Dark mode color palette
        colors = {
            'primary': '#2D3250',      # Deep blue-gray
            'secondary': '#424769',    # Muted blue
            'accent': '#7077A1',       # Periwinkle
            'light': '#F6B17A',        # Soft orange (for highlights/accents)
            'text': '#E1E1E1',         # Light text
            'text_dark': '#1A1A1A',    # Dark text
            'bg_dark': '#1A1A1A',      # Dark background
            'bg_darker': '#141414',    # Darker background
            'bg_light': '#2D2D2D',     # Light background for contrast
            'success': '#4CAF50',      # Green
            'warning': '#FF9800',      # Orange
            'error': '#F44336',        # Red
            'border': '#3D3D3D'        # Dark gray border
        }

        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background-color: {colors['bg_dark']};
                color: {colors['text']};
            }}
            
            QWidget {{
                font-family: 'Segoe UI', 'Arial', sans-serif;
            }}
            
            QTabWidget::pane {{
                border: 1px solid {colors['border']};
                background-color: {colors['bg_darker']};
                border-radius: 4px;
            }}
            
            QTabBar::tab {{
                background-color: {colors['bg_light']};
                color: {colors['text']};
                padding: 12px 25px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                font-weight: 500;
            }}
            
            QTabBar::tab:selected {{
                background-color: {colors['bg_darker']};
                color: {colors['light']};
                border-top: 3px solid {colors['accent']};
            }}
            
            QTabBar::tab:hover {{
                background-color: {colors['secondary']};
                color: {colors['light']};
            }}
            
            QPushButton {{  
                background-color: {colors['primary']};
                color: {colors['text']};
                border: none;           
                border-radius: 4px;
                padding: 8px 16px;
                font-weight: 500;
                min-width: 80px;
            }}
            
            QPushButton:hover {{
                background-color: {colors['secondary']};
            }}
            
            QPushButton:pressed {{
                background-color: {colors['accent']};
            }}
            
            QPushButton:disabled {{
                background-color: #444444;
                color: #888888;
            }}

            QPushButton#language_chip {{
                min-width: 0;
                min-height: 0;
                padding: 4px 12px;
                border-radius: 12px;
                border: 1px solid {colors['border']};
                background-color: {colors['bg_light']};
                color: {colors['text']};
                font-weight: 400;
            }}
            QPushButton#language_chip:hover {{
                background-color: {colors['secondary']};
                border-color: {colors['accent']};
            }}
            QPushButton#language_chip:checked {{
                background-color: {colors['accent']};
                color: {colors['text']};
                border-color: {colors['secondary']};
            }}
            QPushButton#language_chip:checked:hover {{
                background-color: {colors['secondary']};
            }}
            QPushButton#language_chip:pressed {{
                background-color: {colors['primary']};
            }}
            
            QLineEdit {{
                padding: 8px;
                border: 2px solid {colors['border']};
                border-radius: 4px;
                background-color: {colors['bg_darker']};
                color: {colors['text']};
                selection-background-color: {colors['accent']};
            }}
            
            QLineEdit:focus {{
                border-color: {colors['accent']};
            }}
            
            QProgressBar {{
                border: none;
                border-radius: 4px;
                background-color: {colors['bg_light']};
                min-height: 14px;
                max-height: 24px;
                text-align: center;
                color: {colors['text']};
            }}
            
            QProgressBar::chunk {{
                background-color: {colors['accent']};
                border-radius: 4px;
            }}
            
            QGroupBox {{
                font-weight: 500;
                border: 1px solid {colors['border']};
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 24px;
                color: {colors['text']};
            }}
            
            QGroupBox::title {{
                color: {colors['light']};
                subcontrol-origin: margin;
                padding: 0 8px;
            }}
            
            QTreeWidget {{
                border: 1px solid {colors['border']};
                border-radius: 4px;
                background-color: {colors['bg_darker']};
                color: {colors['text']};
            }}
            
            QTreeWidget::item {{
                padding: 6px;
            }}
            
            QTreeWidget::item:selected {{
                background-color: {colors['accent']};
                color: {colors['text']};
            }}
            
            QHeaderView::section {{
                background-color: {colors['bg_light']};
                padding: 8px;
                border: none;
                font-weight: 500;
                color: {colors['text']};
            }}
            
            QComboBox {{
                padding: 8px;
                border: 2px solid {colors['border']};
                border-radius: 4px;
                background-color: {colors['bg_darker']};
                color: {colors['text']};
            }}
            
            QComboBox QAbstractItemView {{
                background-color: {colors['bg_darker']};
                color: {colors['text']};
                selection-background-color: {colors['accent']};
                selection-color: {colors['text']};
            }}
            
            QComboBox::drop-down {{
                border: none;
            }}
            
            QSlider::groove:horizontal {{
                border: none;
                height: 8px;
                background: {colors['bg_light']};
                border-radius: 4px;
            }}
            
            QSlider::handle:horizontal {{
                background: {colors['accent']};
                width: 18px;
                height: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }}
            
            QSlider::sub-page:horizontal {{
                background: {colors['accent']};
                border-radius: 4px;
            }}
            
            QLabel {{
                color: {colors['text']};
            }}
            
            QStatusBar {{
                background-color: {colors['bg_darker']};
                color: {colors['text']};
                padding: 8px;
            }}
            
            QMenu {{
                background-color: {colors['bg_darker']};
                color: {colors['text']};
                border: 1px solid {colors['border']};
                border-radius: 4px;
                padding: 4px;
            }}
            
            QMenu::item {{
                padding: 8px 24px;
            }}
            
            QMenu::item:selected {{
                background-color: {colors['accent']};
                color: {colors['text']};
            }}
            
            QListWidget {{
                background-color: {colors['bg_darker']};
                color: {colors['text']};
                border: 1px solid {colors['border']};
                border-radius: 4px;
            }}
            
            QListWidget::item:selected {{
                background-color: {colors['accent']};
                color: {colors['text']};
            }}
        """ + "\n" + app_stylesheet())

    def _create_config_tab(self, ws_layout: QVBoxLayout):
        layout = ws_layout
        layout.setSpacing(SPACING["lg"])

        # API Configuration Group
        api_group = QGroupBox("API connections")
        api_group.setToolTip("News provider and OpenAI keys used for fetch and relevance scoring.")
        api_layout = QVBoxLayout(api_group)

        # TheNewsAPI token
        news_api_layout = QHBoxLayout()
        news_api_layout.addWidget(QLabel("News API token:"))
        self.news_api_key = QLineEdit()
        self.news_api_key.setText(self.config_manager.get("NEWS_API_KEY", ""))
        self.news_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        news_api_layout.addWidget(self.news_api_key)
        toggle_news = QPushButton("Show")
        toggle_news.clicked.connect(lambda: self._toggle_password_visibility(self.news_api_key))
        news_api_layout.addWidget(toggle_news)
        api_layout.addLayout(news_api_layout)

        # OpenAI API
        openai_api_layout = QHBoxLayout()
        openai_api_layout.addWidget(QLabel("OpenAI API key (for scoring):"))
        self.openai_api_key = QLineEdit()
        self.openai_api_key.setText(self.config_manager.get("OPENAI_API_KEY", ""))
        self.openai_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        openai_api_layout.addWidget(self.openai_api_key)
        toggle_openai = QPushButton("Show")
        toggle_openai.clicked.connect(lambda: self._toggle_password_visibility(self.openai_api_key))
        openai_api_layout.addWidget(toggle_openai)
        api_layout.addLayout(openai_api_layout)

        layout.addWidget(api_group)

        # Relevance Threshold Group
        threshold_group = QGroupBox("Relevance cutoff")
        threshold_group.setToolTip("Articles at or above this score are kept in results and the database.")
        threshold_layout = QHBoxLayout(threshold_group)
        
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setMinimum(0)
        self.threshold_slider.setMaximum(100)
        self.threshold_slider.setValue(int(self.config_manager.get("RELEVANCE_THRESHOLD", 0.7) * 100))
        self.threshold_slider.valueChanged.connect(self._update_threshold_label)
        
        self.threshold_label = QLabel(f"{self.threshold_slider.value() / 100:.2f}")
        
        threshold_layout.addWidget(self.threshold_slider)
        threshold_layout.addWidget(self.threshold_label)
        
        layout.addWidget(threshold_group)

        # Date Range Group
        self.date_range_widget = DateRangeWidget(self.config_manager)
        layout.addWidget(self.date_range_widget)

        # High Recall + Multilingual Expansion Group
        multilingual_group = QGroupBox("Languages and recall")
        multilingual_group.setToolTip("Query expansion languages and fetch volume tradeoffs.")
        multilingual_layout = QVBoxLayout(multilingual_group)
        self.high_recall_enabled = QCheckBox("Enable high-recall mode (balanced quality, higher volume)")
        self.high_recall_enabled.setChecked(bool(self.config_manager.get("HIGH_RECALL_MODE", True)))
        multilingual_layout.addWidget(
            self._create_checkbox_with_help(
                self.high_recall_enabled,
                "When enabled: multilingual query expansion (languages below), higher per-run request budget, "
                "and AI term expansion run as configured. When disabled: English-only queries, a capped request "
                "budget, and query expansion is turned off in saved settings so fetch volume stays lower.",
            )
        )

        multilingual_layout.addWidget(QLabel("Query languages:"))
        self.language_checkboxes = {}
        language_chips_host = QWidget()
        language_flow = FlowLayout(language_chips_host, margin=0, h_spacing=8, v_spacing=6)
        selected_languages = {
            part.strip().lower()
            for part in str(self.config_manager.get("QUERY_EXPANSION_LANGUAGES", "en")).split(",")
            if part.strip()
        }
        for code, label in SUPPORTED_LANGUAGES:
            chip = LanguageChipButton(label)
            chip.setChecked(code in selected_languages or (not selected_languages and code == "en"))
            self.language_checkboxes[code] = chip
            language_flow.addWidget(chip)
        multilingual_layout.addWidget(language_chips_host)

        layout.addWidget(multilingual_group)

        # Add ChatGPT Context Message group
        context_group = QGroupBox("Scoring instructions for the model")
        context_layout = QVBoxLayout(context_group)
        
        context_label = QLabel("Describe what counts as relevant and how strictly to score:")
        context_layout.addWidget(context_label)
        
        self.context_message = QTextEdit()
        self.context_message.setPlaceholderText(
            "Describe what “relevant” means for your topics, incident language, and how strict scoring should be."
        )
        default_message = self.config_manager.get_context_message().get("content", "")
        self.context_message.setText(default_message)
        context_layout.addWidget(self.context_message)
        
        layout.addWidget(context_group)

    def _create_filtering_controls_tab(self, ws_layout: QVBoxLayout):
        layout = ws_layout

        self._advanced_filter_toggle = QPushButton()
        self._advanced_filter_toggle.setObjectName("linkToggle")
        self._advanced_filter_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._advanced_filter_toggle.clicked.connect(self._toggle_advanced_filter_panel)
        layout.addWidget(self._advanced_filter_toggle)

        adv = QGroupBox("Pre-AI filtering")
        adv.setToolTip(
            "Heuristic rules before paid relevance scoring. Turn the stage on or off from Run & pipeline "
            "(that toggle is saved to your configuration file)."
        )
        self.advanced_filter_panel = adv
        adv_outer = QVBoxLayout(adv)
        adv_outer.setSpacing(SPACING["md"])

        info = QLabel(
            "Presets control how aggressively articles drop out before scoring. "
            "In the current backend, non-English articles skip this gate."
        )
        info.setWordWrap(True)
        info.setObjectName("muted")
        adv_outer.addWidget(info)

        self.filter_preset_group = QWidget()
        fp_outer = QVBoxLayout(self.filter_preset_group)
        fp_outer.setContentsMargins(0, 0, 0, 0)
        fp_outer.setSpacing(SPACING["sm"])
        fp_head = QLabel("Filter strength")
        fp_head.setObjectName("subsectionTitle")
        fp_outer.addWidget(fp_head)
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(
            self._create_help_label(
                "Preset:",
                "Chooses a ready-made strictness level. More permissive keeps more articles; "
                "more aggressive removes more before scoring."
            )
        )
        self.filter_preset_combo = QComboBox()
        self.filter_preset_combo.addItem("More Permissive (recommended)", "more_permissive")
        self.filter_preset_combo.addItem("Medium", "medium")
        self.filter_preset_combo.addItem("Most Aggressive", "most_aggressive")
        saved_preset = str(self.config_manager.get("PRELLM_FILTER_PRESET", "more_permissive")).strip().lower()
        preset_index = max(0, self.filter_preset_combo.findData(saved_preset))
        self.filter_preset_combo.setCurrentIndex(preset_index)
        self.filter_preset_combo.currentIndexChanged.connect(self._on_filter_preset_changed)
        preset_layout.addWidget(self.filter_preset_combo)
        preset_layout.addStretch()
        fp_outer.addLayout(preset_layout)
        adv_outer.addWidget(self.filter_preset_group)

        self.filter_global_group = QWidget()
        g_outer = QVBoxLayout(self.filter_global_group)
        g_outer.setContentsMargins(0, 0, 0, 0)
        g_outer.setSpacing(SPACING["sm"])
        g_head = QLabel("Limits and deduplication")
        g_head.setObjectName("subsectionTitle")
        g_outer.addWidget(g_head)
        global_layout = QGridLayout()
        g_outer.addLayout(global_layout)
        self.filter_min_chars_spin = QSpinBox()
        self.filter_min_chars_spin.setRange(0, 200000)
        self.filter_min_chars_spin.setValue(int(self.config_manager.get("PRELLM_MIN_CONTENT_CHARS", 120)))
        self.filter_min_chars_spin.setSuffix(" characters")
        self.filter_max_chars_spin = QSpinBox()
        self.filter_max_chars_spin.setRange(1, 500000)
        self.filter_max_chars_spin.setValue(int(self.config_manager.get("PRELLM_MAX_CONTENT_CHARS", 20000)))
        self.filter_max_chars_spin.setSuffix(" characters")
        self.filter_min_overlap_spin = QSpinBox()
        self.filter_min_overlap_spin.setRange(0, 20)
        self.filter_min_overlap_spin.setValue(int(self.config_manager.get("PRELLM_MIN_QUERY_TOKEN_OVERLAP", 1)))
        self.filter_min_overlap_spin.setSuffix(" matches")
        self.filter_require_incident = QCheckBox("Only keep articles that clearly describe an incident")
        self.filter_require_incident.setChecked(bool(self.config_manager.get("PRELLM_REQUIRE_INCIDENT_SIGNAL", False)))
        self.filter_dedup_url = QCheckBox("Remove duplicate URLs")
        self.filter_dedup_url.setChecked(bool(self.config_manager.get("PRELLM_DEDUP_BY_URL", True)))
        self.filter_dedup_title = QCheckBox("Remove duplicate titles")
        self.filter_dedup_title.setChecked(bool(self.config_manager.get("PRELLM_DEDUP_BY_TITLE", True)))

        global_layout.addWidget(
            self._create_help_label(
                "Minimum content length:",
                "Rejects articles that are too short to be useful."
            ),
            0, 0
        )
        global_layout.addWidget(self.filter_min_chars_spin, 0, 1)
        global_layout.addWidget(
            self._create_help_label(
                "Maximum content length:",
                "Rejects articles that are unusually long and often noisy or off-topic."
            ),
            1, 0
        )
        global_layout.addWidget(self.filter_max_chars_spin, 1, 1)
        global_layout.addWidget(
            self._create_help_label(
                "Minimum keyword matches with topic:",
                "Minimum number of topic words that must appear in the article."
            ),
            2, 0
        )
        global_layout.addWidget(self.filter_min_overlap_spin, 2, 1)
        global_layout.addWidget(
            self._create_checkbox_with_help(
                self.filter_require_incident,
                "When on, only articles with clear incident language are kept."
            ),
            3, 0, 1, 2
        )
        global_layout.addWidget(
            self._create_checkbox_with_help(
                self.filter_dedup_url,
                "Removes repeated articles that share the same web link."
            ),
            4, 0, 1, 2
        )
        global_layout.addWidget(
            self._create_checkbox_with_help(
                self.filter_dedup_title,
                "Removes repeated articles that have the same or near-identical title."
            ),
            5, 0, 1, 2
        )
        adv_outer.addWidget(self.filter_global_group)

        self.filter_topic_words_group = QWidget()
        topic_words_layout = QVBoxLayout(self.filter_topic_words_group)
        topic_words_layout.setContentsMargins(0, 0, 0, 0)
        topic_words_layout.setSpacing(SPACING["sm"])
        tw_head = QLabel("Topic keywords")
        tw_head.setObjectName("subsectionTitle")
        topic_words_layout.addWidget(tw_head)
        topic_words_layout.addWidget(
            QLabel("Words required to overlap between the article and each search topic.")
        )
        topic_selector_row = QHBoxLayout()
        topic_selector_row.addWidget(QLabel("Topic:"))
        self.filter_topic_words_combo = QComboBox()
        self.filter_topic_words_combo.currentIndexChanged.connect(self._on_filter_topic_words_topic_changed)
        topic_selector_row.addWidget(self.filter_topic_words_combo)
        topic_words_layout.addLayout(topic_selector_row)

        self.filter_topic_words_list = QListWidget()
        self.filter_topic_words_list.setMinimumHeight(140)
        topic_words_layout.addWidget(self.filter_topic_words_list)

        topic_words_buttons = QHBoxLayout()
        add_word_btn = QPushButton("Add word")
        add_word_btn.clicked.connect(self._add_filter_topic_word)
        remove_word_btn = QPushButton("Remove selected")
        remove_word_btn.clicked.connect(self._remove_filter_topic_word)
        topic_words_buttons.addWidget(add_word_btn)
        topic_words_buttons.addWidget(remove_word_btn)
        topic_words_buttons.addStretch()
        topic_words_layout.addLayout(topic_words_buttons)
        adv_outer.addWidget(self.filter_topic_words_group)

        insights_panel = QWidget()
        insights_layout = QVBoxLayout(insights_panel)
        insights_layout.setContentsMargins(0, 0, 0, 0)
        insights_layout.setSpacing(SPACING["sm"])
        in_head = QLabel("Recent gate decisions (debug)")
        in_head.setObjectName("subsectionTitle")
        insights_layout.addWidget(in_head)
        self.filter_insights_output = QTextEdit()
        self.filter_insights_output.setReadOnly(True)
        self.filter_insights_output.setMinimumHeight(180)
        self.filter_insights_output.setPlaceholderText("Refresh after runs to inspect how the gate behaved.")
        insights_layout.addWidget(self.filter_insights_output)
        adv_outer.addWidget(insights_panel)

        button_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh from database")
        refresh_btn.clicked.connect(self._update_filtering_insights)
        save_btn = QPushButton("Save gate rules")
        save_btn.clicked.connect(self._save_filtering_settings)
        button_row.addWidget(refresh_btn)
        button_row.addStretch()
        button_row.addWidget(save_btn)
        adv_outer.addLayout(button_row)

        self._filter_topic_word_overrides = self._topic_word_overrides_from_config()
        self._refresh_filter_topic_words_topics()
        self._update_filtering_insights()

        layout.addWidget(adv)
        adv.setVisible(False)
        self._sync_advanced_filter_toggle_label()

        self._apply_prellm_filtering_controls_enabled(
            bool(self.config_manager.get("PRELLM_ENABLE_FILTERING", False))
        )

    def _toggle_advanced_filter_panel(self) -> None:
        panel = getattr(self, "advanced_filter_panel", None)
        if panel is None:
            return
        panel.setVisible(not panel.isVisible())
        self._sync_advanced_filter_toggle_label()

    def _sync_advanced_filter_toggle_label(self) -> None:
        if not hasattr(self, "_advanced_filter_toggle"):
            return
        panel = getattr(self, "advanced_filter_panel", None)
        if panel is None:
            return
        visible = panel.isVisible()
        self._advanced_filter_toggle.setText(
            "Hide pre-AI filtering options" if visible else "Show pre-AI filtering options…"
        )

    def _apply_prellm_filtering_controls_enabled(self, enabled: bool):
        """Disable preset, global, and per-topic controls when pre-LLM filtering is off."""
        if not hasattr(self, "filter_preset_group"):
            return
        self.filter_preset_group.setEnabled(enabled)
        self.filter_global_group.setEnabled(enabled)
        self.filter_topic_words_group.setEnabled(enabled)

    def _on_processing_prellm_filtering_toggled(self, checked: bool):
        """Keep in-memory config, Filtering tab state, and config.json aligned with the Processing tab switch."""
        enabled = bool(checked)
        self.config_manager.config["PRELLM_ENABLE_FILTERING"] = enabled
        self._apply_prellm_filtering_controls_enabled(enabled)
        try:
            self.config_manager.save_config(self.config_manager.config)
        except Exception as exc:
            logger.warning("Could not persist PRELLM_ENABLE_FILTERING: %s", exc)

    def _create_help_label(self, text: str, tooltip: str) -> QWidget:
        """Create a label with a compact hover-help icon."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        label = QLabel(text)
        label.setToolTip(tooltip)
        row.addWidget(label)

        row.addWidget(self._create_info_tool_button(tooltip))
        row.addStretch()
        return container

    def _create_checkbox_with_help(self, checkbox: QCheckBox, tooltip: str) -> QWidget:
        """Attach a hover-help icon to a checkbox option."""
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        checkbox.setToolTip(tooltip)
        row.addWidget(checkbox)

        row.addWidget(self._create_info_tool_button(tooltip))
        row.addStretch()
        return container

    def _create_info_tool_button(self, tooltip: str) -> QToolButton:
        """Small (i) in circle using the platform information icon."""
        btn = QToolButton()
        btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation))
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        btn.setAutoRaise(True)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setToolTip(tooltip)
        btn.setFixedSize(20, 20)
        btn.setIconSize(QSize(16, 16))
        return btn

    def _on_filter_preset_changed(self, _index=None):
        preset_key = self.filter_preset_combo.currentData()
        preset_values = FILTER_PRESET_MAP.get(preset_key, FILTER_PRESET_MAP["more_permissive"])
        self.filter_min_chars_spin.setValue(int(preset_values["min_content_chars"]))
        self.filter_max_chars_spin.setValue(int(preset_values["max_content_chars"]))
        self.filter_min_overlap_spin.setValue(int(preset_values["min_query_token_overlap"]))
        self.filter_require_incident.setChecked(bool(preset_values["require_incident_signal"]))
        self.filter_dedup_url.setChecked(bool(preset_values["dedup_by_url"]))
        self.filter_dedup_title.setChecked(bool(preset_values["dedup_by_title"]))

    def _topic_word_overrides_from_config(self) -> dict:
        raw_overrides = self.config_manager.get("PRELLM_TOPIC_OVERRIDES", {}) or {}
        if not isinstance(raw_overrides, dict):
            return {}
        cleaned: dict = {}
        for topic, override in raw_overrides.items():
            if not isinstance(topic, str) or not topic.strip():
                continue
            if not isinstance(override, dict):
                continue
            words = override.get("keywords", [])
            if not isinstance(words, list):
                continue
            normalized_words = []
            seen = set()
            for word in words:
                term = str(word).strip().lower()
                if not term or term in seen:
                    continue
                seen.add(term)
                normalized_words.append(term)
            cleaned[topic.strip()] = normalized_words
        return cleaned

    def _refresh_filter_topic_words_topics(self):
        if not hasattr(self, "filter_topic_words_combo"):
            return
        topics = []
        for topic in self._filter_topic_word_overrides.keys():
            normalized = str(topic).strip()
            if normalized:
                topics.append(normalized)
        self.filter_topic_words_combo.blockSignals(True)
        self.filter_topic_words_combo.clear()
        self.filter_topic_words_combo.addItems(topics)
        self.filter_topic_words_combo.blockSignals(False)
        self._on_filter_topic_words_topic_changed()

    def _on_filter_topic_words_topic_changed(self, _index=None):
        if not hasattr(self, "filter_topic_words_list"):
            return
        self.filter_topic_words_list.clear()
        topic = self.filter_topic_words_combo.currentText().strip() if hasattr(self, "filter_topic_words_combo") else ""
        if not topic:
            return
        words = self._filter_topic_word_overrides.get(topic, [])
        for word in words:
            self.filter_topic_words_list.addItem(word)

    def _add_filter_topic_word(self):
        topic = self.filter_topic_words_combo.currentText().strip() if hasattr(self, "filter_topic_words_combo") else ""
        if not topic:
            QMessageBox.warning(self, "No Topic", "Add at least one search term first.")
            return
        word, ok = QInputDialog.getText(self, "Add Filter Word", f"Add word or phrase for '{topic}':")
        if not ok:
            return
        normalized = str(word).strip().lower()
        if not normalized:
            return
        current = self._filter_topic_word_overrides.setdefault(topic, [])
        if normalized in current:
            QMessageBox.information(self, "Already Exists", "That word already exists for this topic.")
            return
        current.append(normalized)
        self._on_filter_topic_words_topic_changed()
        self._update_workspace_state_banner()

    def _remove_filter_topic_word(self):
        topic = self.filter_topic_words_combo.currentText().strip() if hasattr(self, "filter_topic_words_combo") else ""
        if not topic:
            return
        selected = self.filter_topic_words_list.currentItem() if hasattr(self, "filter_topic_words_list") else None
        if selected is None:
            return
        word = selected.text().strip().lower()
        words = self._filter_topic_word_overrides.get(topic, [])
        self._filter_topic_word_overrides[topic] = [item for item in words if item != word]
        self._on_filter_topic_words_topic_changed()
        self._update_workspace_state_banner()

    def _build_generated_topic_word_overrides(self, context_text: str) -> dict:
        payload = self._generate_topic_words_with_openai(context_text)
        topics = payload.get("topics", [])
        if not isinstance(topics, list):
            return {}
        min_overlap_value = int(self.config_manager.get("PRELLM_MIN_QUERY_TOKEN_OVERLAP", 1))
        require_incident_value = bool(self.config_manager.get("PRELLM_REQUIRE_INCIDENT_SIGNAL", False))
        overrides = {}
        for item in topics:
            if not isinstance(item, dict):
                continue
            topic_name = str(item.get("topic", "")).strip()
            if not topic_name:
                continue
            keywords = item.get("keywords", [])
            if not isinstance(keywords, list):
                keywords = []
            normalized_keywords = []
            seen = set()
            for word in keywords:
                normalized = str(word).strip().lower()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                normalized_keywords.append(normalized)
            overrides[topic_name] = {
                "enabled": True,
                "min_query_token_overlap": min_overlap_value,
                "require_incident_signal": require_incident_value,
                "keywords": normalized_keywords[:20],
            }
        return overrides

    def _generate_topic_words_with_openai(self, context_text: str) -> dict:
        cleaned_context = str(context_text or "").strip()
        if not cleaned_context:
            return {"topics": []}

        prompt = (
            "You are creating pre-filter topic controls for a news incident scraper.\n"
            "From the instruction text below, infer the best topic buckets and strong filtering keywords.\n"
            "Return strict JSON only in this shape:\n"
            "{\"topics\":[{\"topic\":\"<short topic name>\",\"keywords\":[\"keyword1\",\"keyword2\"]}]}\n"
            "Rules:\n"
            "- 3 to 12 topics.\n"
            "- Topic names must be short and clear.\n"
            "- Each topic must have 5 to 20 keywords/phrases.\n"
            "- Keywords should be practical for lexical matching in news text.\n"
            "- Avoid generic stopwords.\n"
            "- No markdown, no explanation.\n\n"
            f"INSTRUCTIONS:\n{cleaned_context}"
        )
        client = get_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        content = (response.choices[0].message.content or "").strip()
        if not content:
            raise ValueError("OpenAI returned empty content for topic generation.")

        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content).strip()

        parsed = json.loads(content)
        if isinstance(parsed, list):
            parsed = {"topics": parsed}
        if not isinstance(parsed, dict):
            raise ValueError("OpenAI topic generation did not return a JSON object.")
        return parsed

    def _save_filtering_settings(self):
        min_chars = int(self.filter_min_chars_spin.value())
        max_chars = int(self.filter_max_chars_spin.value())
        if min_chars > max_chars:
            QMessageBox.warning(self, "Invalid Filtering Range", "Minimum content length cannot exceed maximum.")
            return
        updates = {
            "PRELLM_ENABLE_FILTERING": (
                bool(self.processing_enable_prellm.isChecked())
                if hasattr(self, "processing_enable_prellm")
                else bool(self.config_manager.get("PRELLM_ENABLE_FILTERING", False))
            ),
            "PRELLM_FILTER_PRESET": self.filter_preset_combo.currentData(),
            "PRELLM_MIN_CONTENT_CHARS": min_chars,
            "PRELLM_MAX_CONTENT_CHARS": max_chars,
            "PRELLM_MIN_QUERY_TOKEN_OVERLAP": int(self.filter_min_overlap_spin.value()),
            "PRELLM_REQUIRE_INCIDENT_SIGNAL": bool(self.filter_require_incident.isChecked()),
            "PRELLM_DEDUP_BY_URL": bool(self.filter_dedup_url.isChecked()),
            "PRELLM_DEDUP_BY_TITLE": bool(self.filter_dedup_title.isChecked()),
            "PRELLM_TOPIC_OVERRIDES": self._overrides_with_keywords(),
        }
        merged = dict(self.config_manager.config)
        merged.update(updates)
        try:
            self.config_manager.save_config(merged)
            self._filter_topic_word_overrides = self._topic_word_overrides_from_config()
            self._refresh_filter_topic_words_topics()
            self._snapshot_saved_workspace()
            self._update_workspace_state_banner()
            QMessageBox.information(self, "Saved", "Gate rules saved to your configuration file.")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to save filtering controls: {exc}")

    def _overrides_with_keywords(self) -> dict:
        overrides = {}
        min_overlap_value = int(self.filter_min_overlap_spin.value()) if hasattr(self, "filter_min_overlap_spin") else 1
        require_incident_value = bool(self.filter_require_incident.isChecked()) if hasattr(self, "filter_require_incident") else False
        for topic, words in (self._filter_topic_word_overrides or {}).items():
            topic_name = str(topic).strip()
            if not topic_name:
                continue
            normalized_words = []
            seen = set()
            for word in words:
                normalized = str(word).strip().lower()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                normalized_words.append(normalized)
            overrides[topic_name] = {
                "enabled": True,
                "min_query_token_overlap": min_overlap_value,
                "require_incident_signal": require_incident_value,
                "keywords": normalized_words,
            }
        return overrides

    def _update_filtering_insights(self):
        try:
            rows = self.db_manager.execute_query(
                """
                SELECT reason, COUNT(*) AS count
                FROM pre_llm_filter_results
                WHERE decision='drop'
                GROUP BY reason
                ORDER BY count DESC, reason ASC
                LIMIT 15
                """
            ) or []
        except Exception as exc:
            self.filter_insights_output.setPlainText(f"Could not load insights: {exc}")
            return

        if not rows:
            self.filter_insights_output.setPlainText(
                "No drop decisions recorded yet.\nRun processing to see what was filtered and why."
            )
            return
        lines = ["Most common drop reasons:"]
        for row in rows:
            lines.append(f"- {row.get('reason', 'unknown')}: {row.get('count', 0)}")
        self.filter_insights_output.setPlainText("\n".join(lines))

    def _save_config(self):
        """Save and validate configuration including API keys."""
        try:
            # Get values
            news_key = self.news_api_key.text().strip()
            openai_key = self.openai_api_key.text().strip()

            # Validate date range before saving
            valid_dates, date_error = self.date_range_widget.validate_selection()
            if not valid_dates:
                QMessageBox.warning(self, "Invalid Date Range", date_error)
                return
            
            # Show validation progress
            self.progress_dialog = QMessageBox(self)
            self.progress_dialog.setWindowTitle("Validating Configuration")
            self.progress_dialog.setText("Validating API keys...")
            self.progress_dialog.setStandardButtons(QMessageBox.StandardButton.Cancel)
            
            # Create and start validation worker
            self.validation_worker = ApiValidationWorker(news_key, openai_key)
            self.validation_worker.finished.connect(self._handle_validation_result)
            self.validation_worker.start()
            
            # Show dialog but don't block
            self.progress_dialog.show()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to start validation: {e}")
            logger.error(f"Validation start error: {e}")

    def _handle_validation_result(self, result):
        """Handle API validation results"""
        news_valid, openai_valid, error = result
        
        # Close progress dialog
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.close()
        
        if error:
            QMessageBox.critical(self, "Error", f"Validation error: {error}")
            return
            
        if not news_valid:
            QMessageBox.critical(self, "Error", "Invalid TheNewsAPI token")
            return
        if not openai_valid:
            QMessageBox.critical(self, "Error", "Invalid OpenAI API key")
            return

        # Update config with validated values
        try:
            # Save all config values including API keys
            high_recall_on = bool(self.high_recall_enabled.isChecked())
            config_updates = {
                "NEWS_API_KEY": self.news_api_key.text().strip(),
                "OPENAI_API_KEY": self.openai_api_key.text().strip(),
                "RELEVANCE_THRESHOLD": self.threshold_slider.value() / 100,
                "HIGH_RECALL_MODE": high_recall_on,
                "QUERY_EXPANSION_ENABLED": high_recall_on,
                "QUERY_EXPANSION_USE_AI": True,
                "QUERY_EXPANSION_LANGUAGES": self._selected_languages_csv(),
                "CHATGPT_CONTEXT_MESSAGE": {
                    "role": "system",
                    "content": self.context_message.toPlainText()
                },
            }
            config_updates.update(self.date_range_widget.get_config_values())
            try:
                generated_overrides = self._build_generated_topic_word_overrides(
                    self.context_message.toPlainText()
                )
            except Exception as exc:
                logger.warning("Could not auto-generate pre-filter topics from OpenAI: %s", exc)
                current_overrides = self.config_manager.get("PRELLM_TOPIC_OVERRIDES", {})
                generated_overrides = current_overrides if isinstance(current_overrides, dict) else {}
                QMessageBox.warning(
                    self,
                    "Topic Generation Warning",
                    "Configuration was saved, but topic-word generation failed. "
                    "Existing topic words were kept.",
                )
            config_updates["PRELLM_TOPIC_OVERRIDES"] = generated_overrides

            # Save all at once to trigger encrypted storage
            merged = dict(self.config_manager.config)
            merged.update(config_updates)
            self.config_manager.save_config(merged)
            self._filter_topic_word_overrides = self._topic_word_overrides_from_config()
            self._refresh_filter_topic_words_topics()

            if self.config_manager.validate():
                self.processor = None  # Clear old processor
                self._snapshot_saved_workspace()
                self._update_workspace_state_banner()
                QMessageBox.information(self, "Success", "Workspace saved and validated successfully.")
                self.statusBar().showMessage("Workspace saved successfully")
            else:
                QMessageBox.warning(self, "Warning", "Configuration saved but validation failed. Check settings.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save configuration: {e}")
            logger.error(f"Config save error: {e}")

    def _create_search_terms_tab(self, ws_layout: QVBoxLayout):
        layout = ws_layout
        list_group = QGroupBox("Search topics and terms")
        list_group.setToolTip("Topics used for API search; import or add one term per line.")
        list_layout = QVBoxLayout(list_group)

        self.terms_list = QListWidget()
        list_layout.addWidget(self.terms_list)
        self._refresh_search_terms()

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Add term")
        add_btn.clicked.connect(self._add_search_term)
        remove_btn = QPushButton("Remove selected")
        remove_btn.clicked.connect(self._remove_search_term)
        import_btn = QPushButton("Import…")
        import_btn.clicked.connect(self._import_search_terms)
        export_btn = QPushButton("Export…")
        export_btn.clicked.connect(self._export_search_terms)

        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addWidget(import_btn)
        btn_layout.addWidget(export_btn)
        list_layout.addLayout(btn_layout)

        layout.addWidget(list_group)

    def _update_previews(self):
        # Update raw articles preview
        self.raw_preview.clear()
        raw_articles = self.db_manager.execute_query("SELECT id, title, url FROM raw_articles ORDER BY id DESC LIMIT 100")
        raw_count = len(self.db_manager.execute_query("SELECT id FROM raw_articles"))
        self.raw_count_label.setText(str(raw_count))
        
        for article in raw_articles:
            item = QTreeWidgetItem([str(article['id']), article['title'], article['url']])
            self.raw_preview.addTopLevelItem(item)

        # Update relevant articles preview
        self.cleaned_preview.clear()
        relevant_articles = self.db_manager.execute_query(
            "SELECT id, title, relevance_score FROM relevant_articles ORDER BY id DESC LIMIT 100"
        )
        relevant_count = len(self.db_manager.execute_query("SELECT id FROM relevant_articles"))
        self.cleaned_count_label.setText(str(relevant_count))
        
        for article in relevant_articles:
            score = f"{article.get('relevance_score', 0):.2f}"  # Fixed double colon typo
            item = QTreeWidgetItem([str(article['id']), article['title'], score])
            self.cleaned_preview.addTopLevelItem(item)

    def _clear_raw_articles(self):
        reply = QMessageBox.question(
            self, 
            'Confirm Clear',
            'Are you sure you want to clear all raw articles?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.db_manager.execute_query("DELETE FROM raw_articles")
            self._update_previews()
            QMessageBox.information(self, "Success", "Raw articles cleared successfully")

    def _clear_cleaned_articles(self):
        reply = QMessageBox.question(
            self, 
            'Confirm Clear',
            'Are you sure you want to clear all relevant articles?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.db_manager.execute_query("DELETE FROM relevant_articles")
            self._update_previews()
            QMessageBox.information(self, "Success", "Relevant articles cleared successfully")

    def _create_results_tab(self):
        self.results_host = QWidget()
        layout = QVBoxLayout(self.results_host)
        layout.setSpacing(SPACING["lg"])

        rt = QLabel("Results")
        tf = rt.font()
        tf.setPointSize(18)
        tf.setBold(True)
        rt.setFont(tf)
        layout.addWidget(rt)

        hint = QLabel(
            "The table lists articles at or above your workspace relevance cutoff (loaded from the database). "
            "Filters below only change which rows are visible; export includes those same visible rows. "
            "The detail pane shows the selected row’s explanation, incident line, and other stored fields."
        )
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)

        filter_group = QGroupBox("Filter the table")
        filter_group.setToolTip(
            "Visible rows = rows passing text search and minimum score. Export writes the same visible rows."
        )
        filter_layout = QHBoxLayout(filter_group)

        filter_layout.addWidget(QLabel("Text search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Match title, URL, keywords, description…")
        self.search_box.textChanged.connect(self._filter_results)
        self.search_box.setToolTip("Filter by text in title, URL, keywords, description, snippet, source, record ID, language")
        filter_layout.addWidget(self.search_box)

        filter_layout.addWidget(QLabel("Minimum score:"))
        self.relevance_filter = QComboBox()
        self.relevance_filter.addItems(["All scores", "Above 0.3", "Above 0.5", "Above 0.7", "Above 0.9"])
        self.relevance_filter.currentIndexChanged.connect(self._filter_results)
        filter_layout.addWidget(self.relevance_filter)

        filter_layout.addWidget(QLabel("Column preset:"))
        self.column_set_combo = QComboBox()
        self.column_set_combo.addItems(["Analyst (compact)", "All export fields"])
        self.column_set_combo.currentIndexChanged.connect(self._on_results_column_preset_changed)
        filter_layout.addWidget(self.column_set_combo)

        layout.addWidget(filter_group)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.results_table = QTableWidget(0, len(RESULTS_TABLE_COLUMNS))
        self._active_results_columns = list(RESULTS_TABLE_COLUMNS)
        self._apply_results_table_columns()
        hdr = self.results_table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(False)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setWordWrap(False)
        self.results_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_table.customContextMenuRequested.connect(self._show_results_context_menu)
        self.results_table.itemSelectionChanged.connect(self._on_results_selection_changed)
        split.addWidget(self.results_table)

        self.result_detail = QTextEdit()
        self.result_detail.setReadOnly(True)
        self.result_detail.setPlaceholderText("Select a row to inspect fields, explanation, and scoring output.")
        split.addWidget(self.result_detail)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        layout.addWidget(split, 1)

        self.all_results = []

        export_btn = QPushButton("Export visible rows…")
        export_btn.setToolTip("Exports rows currently shown in the table after text and score filters.")
        export_btn.clicked.connect(self._export_results)
        layout.addWidget(export_btn)

        self._load_results_from_database()

    def _on_results_column_preset_changed(self, _index: int = 0) -> None:
        if self.column_set_combo.currentIndex() == 0:
            self._active_results_columns = list(RESULTS_TABLE_COLUMNS_ANALYST)
        else:
            self._active_results_columns = list(RESULTS_TABLE_COLUMNS)
        self._apply_results_table_columns()
        self._filter_results()

    def _apply_results_table_columns(self) -> None:
        cols = self._active_results_columns
        self.results_table.setColumnCount(len(cols))
        self.results_table.setHorizontalHeaderLabels([h for _, h, _ in cols])
        hdr = self.results_table.horizontalHeader()
        for col, (_, _, w) in enumerate(cols):
            self.results_table.setColumnWidth(col, w)

    def _on_results_selection_changed(self) -> None:
        rows = self.results_table.selectionModel().selectedRows()
        if not rows:
            self.result_detail.clear()
            return
        row = rows[0].row()
        payload = self._result_payload_for_row(row)
        if not payload:
            self.result_detail.clear()
            return
        lines = [
            f"<b>Title</b><br>{html.escape(str(payload.get('title') or ''))}<br><br>",
            f"<b>Relevance</b> {html.escape(str(payload.get('relevance_score', '')))}<br><br>",
            f"<b>URL</b><br>{html.escape(str(payload.get('url') or ''))}<br><br>",
            f"<b>Source</b> {html.escape(str(payload.get('source') or ''))} &nbsp; "
            f"<b>Published</b> {html.escape(str(payload.get('published_at') or ''))}<br><br>",
            f"<b>Why this row appears</b><br>Stored as relevant at or above your cutoff when it was scored. "
            f"The database does not retain per-article drop reasons for kept items.<br><br>",
            f"<b>Explanation</b><br>{html.escape(str(payload.get('explanation') or ''))}<br><br>",
            f"<b>Incident (one line)</b><br>{html.escape(str(payload.get('incident_sentence') or ''))}<br><br>",
            f"<b>Keywords</b><br>{html.escape(str(payload.get('keywords') or ''))}<br><br>",
            f"<b>Description</b><br>{html.escape(str(payload.get('description') or ''))}<br>",
        ]
        self.result_detail.setHtml("".join(lines))

    def _snapshot_saved_workspace(self) -> None:
        self._saved_workspace_snapshot = self._gather_workspace_draft_for_compare()

    def _gather_workspace_draft_for_compare(self) -> dict[str, Any]:
        """Serializable subset of widget state for dirty detection (excludes secrets in compare)."""
        return {
            "threshold": self.threshold_slider.value(),
            "high_recall": bool(self.high_recall_enabled.isChecked()),
            "languages": self._selected_languages_csv(),
            "context": self.context_message.toPlainText(),
            "date": self.date_range_widget.get_config_values(),
            "prellm_on": bool(self.processing_enable_prellm.isChecked()),
            "max_run": int(self.max_articles_run_spin.value()),
            "max_q": int(self.max_articles_per_query_spin.value()),
            "filter_preset": self.filter_preset_combo.currentData(),
            "min_chars": int(self.filter_min_chars_spin.value()),
            "max_chars": int(self.filter_max_chars_spin.value()),
            "overlap": int(self.filter_min_overlap_spin.value()),
            "incident": bool(self.filter_require_incident.isChecked()),
            "dedup_url": bool(self.filter_dedup_url.isChecked()),
            "dedup_title": bool(self.filter_dedup_title.isChecked()),
            "topic_overrides": json.dumps(self._filter_topic_word_overrides, sort_keys=True),
            "has_news_key": bool(self.news_api_key.text().strip()),
            "has_openai_key": bool(self.openai_api_key.text().strip()),
            "search_terms": json.dumps(
                sorted(
                    str(t.get("term", "")).strip()
                    for t in self.search_manager.get_search_terms()
                    if str(t.get("term", "")).strip()
                ),
            ),
        }

    def _workspace_is_dirty(self) -> bool:
        if not self._saved_workspace_snapshot:
            return False
        return self._gather_workspace_draft_for_compare() != self._saved_workspace_snapshot

    def _update_workspace_state_banner(self) -> None:
        if not hasattr(self, "_workspace_state_banner"):
            return
        dirty = self._workspace_is_dirty()
        self._workspace_state_banner.setText(
            "Draft: the workspace form, gate rules, or search topics differ from the last snapshot the app took "
            "after a successful configuration write. Use Save workspace… or Save gate rules only to persist."
            if dirty
            else "Saved snapshot: the form matches the last successful write to your configuration file "
            "(Save workspace…, Save gate rules only, Reload from disk, or the save attempted when you start a run). "
            "Starting a run always copies the current form into memory for the worker; if disk save succeeds, "
            "that snapshot updates here too."
        )

    def _connect_workspace_dirty_signals(self) -> None:
        def _touch():
            self._update_workspace_state_banner()

        for w in (
            self.threshold_slider,
            self.high_recall_enabled,
            self.context_message,
            self.news_api_key,
            self.openai_api_key,
            self.filter_preset_combo,
            self.filter_min_chars_spin,
            self.filter_max_chars_spin,
            self.filter_min_overlap_spin,
            self.filter_require_incident,
            self.filter_dedup_url,
            self.filter_dedup_title,
        ):
            if hasattr(w, "textChanged"):
                w.textChanged.connect(_touch)
            elif hasattr(w, "valueChanged"):
                w.valueChanged.connect(_touch)
            elif hasattr(w, "currentIndexChanged"):
                w.currentIndexChanged.connect(_touch)
            elif hasattr(w, "toggled"):
                w.toggled.connect(_touch)
        for chip in getattr(self, "language_checkboxes", {}).values():
            chip.toggled.connect(_touch)
        self.date_range_widget.preset_radio.toggled.connect(_touch)
        self.date_range_widget.custom_radio.toggled.connect(_touch)
        self.date_range_widget.specific_radio.toggled.connect(_touch)
        self.date_range_widget.preset_combo.currentIndexChanged.connect(_touch)
        self.date_range_widget.after_date.dateChanged.connect(_touch)
        self.date_range_widget.before_date.dateChanged.connect(_touch)
        self.date_range_widget.specific_date.dateChanged.connect(_touch)

    def _reset_workspace_draft(self) -> None:
        if self._workspace_is_dirty():
            r = QMessageBox.question(
                self,
                "Reset draft",
                "Discard unsaved form changes and reload from the in-memory configuration "
                "(normally the last successful load or save)?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                return
        self.news_api_key.setText(self.config_manager.get("NEWS_API_KEY", ""))
        self.openai_api_key.setText(self.config_manager.get("OPENAI_API_KEY", ""))
        self.threshold_slider.setValue(int(self.config_manager.get("RELEVANCE_THRESHOLD", 0.7) * 100))
        self._update_threshold_label()
        self.high_recall_enabled.setChecked(bool(self.config_manager.get("HIGH_RECALL_MODE", True)))
        self.context_message.setText(self.config_manager.get_context_message().get("content", ""))
        self.date_range_widget.load_from_config(self.config_manager.config)
        selected_languages = {
            part.strip().lower()
            for part in str(self.config_manager.get("QUERY_EXPANSION_LANGUAGES", "en")).split(",")
            if part.strip()
        }
        for code, chip in self.language_checkboxes.items():
            chip.setChecked(code in selected_languages or (not selected_languages and code == "en"))
        saved_preset = str(self.config_manager.get("PRELLM_FILTER_PRESET", "more_permissive")).strip().lower()
        idx = max(0, self.filter_preset_combo.findData(saved_preset))
        self.filter_preset_combo.setCurrentIndex(idx)
        self.filter_min_chars_spin.setValue(int(self.config_manager.get("PRELLM_MIN_CONTENT_CHARS", 120)))
        self.filter_max_chars_spin.setValue(int(self.config_manager.get("PRELLM_MAX_CONTENT_CHARS", 20000)))
        self.filter_min_overlap_spin.setValue(int(self.config_manager.get("PRELLM_MIN_QUERY_TOKEN_OVERLAP", 1)))
        self.filter_require_incident.setChecked(bool(self.config_manager.get("PRELLM_REQUIRE_INCIDENT_SIGNAL", False)))
        self.filter_dedup_url.setChecked(bool(self.config_manager.get("PRELLM_DEDUP_BY_URL", True)))
        self.filter_dedup_title.setChecked(bool(self.config_manager.get("PRELLM_DEDUP_BY_TITLE", True)))
        self._filter_topic_word_overrides = self._topic_word_overrides_from_config()
        self._refresh_filter_topic_words_topics()
        self.processing_enable_prellm.blockSignals(True)
        self.processing_enable_prellm.setChecked(bool(self.config_manager.get("PRELLM_ENABLE_FILTERING", False)))
        self.processing_enable_prellm.blockSignals(False)
        self.max_articles_run_spin.setValue(int(self.config_manager.get("FETCH_MAX_ARTICLES_PER_RUN", 2000)))
        self.max_articles_per_query_spin.setValue(int(self.config_manager.get("FETCH_MAX_ARTICLES_PER_QUERY", 500)))
        self._apply_prellm_filtering_controls_enabled(self.processing_enable_prellm.isChecked())
        self._snapshot_saved_workspace()
        self._update_workspace_state_banner()

    def _reload_workspace_from_disk(self) -> None:
        if self._workspace_is_dirty():
            r = QMessageBox.question(
                self,
                "Reload from disk",
                "Discard unsaved changes and reload config.json from disk?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if r != QMessageBox.StandardButton.Yes:
                return
        try:
            self.config_manager.reload_from_disk()
        except Exception as exc:
            QMessageBox.critical(self, "Reload failed", str(exc))
            return
        self._reset_workspace_draft()

    def _apply_draft_to_live_config(self) -> None:
        """Push current widget values into config_manager.config (used before pipeline run)."""
        self.config_manager.config["NEWS_API_KEY"] = self.news_api_key.text().strip()
        self.config_manager.config["OPENAI_API_KEY"] = self.openai_api_key.text().strip()
        self.config_manager.config["RELEVANCE_THRESHOLD"] = self.threshold_slider.value() / 100
        high = bool(self.high_recall_enabled.isChecked())
        self.config_manager.config["HIGH_RECALL_MODE"] = high
        self.config_manager.config["QUERY_EXPANSION_ENABLED"] = high
        self.config_manager.config["QUERY_EXPANSION_USE_AI"] = True
        self.config_manager.config["QUERY_EXPANSION_LANGUAGES"] = self._selected_languages_csv()
        self.config_manager.config["CHATGPT_CONTEXT_MESSAGE"] = {
            "role": "system",
            "content": self.context_message.toPlainText(),
        }
        self.config_manager.config.update(self.date_range_widget.get_config_values())
        self.config_manager.config["PRELLM_ENABLE_FILTERING"] = bool(self.processing_enable_prellm.isChecked())
        self.config_manager.config["PRELLM_FILTER_PRESET"] = self.filter_preset_combo.currentData()
        self.config_manager.config["PRELLM_MIN_CONTENT_CHARS"] = int(self.filter_min_chars_spin.value())
        self.config_manager.config["PRELLM_MAX_CONTENT_CHARS"] = int(self.filter_max_chars_spin.value())
        self.config_manager.config["PRELLM_MIN_QUERY_TOKEN_OVERLAP"] = int(self.filter_min_overlap_spin.value())
        self.config_manager.config["PRELLM_REQUIRE_INCIDENT_SIGNAL"] = bool(self.filter_require_incident.isChecked())
        self.config_manager.config["PRELLM_DEDUP_BY_URL"] = bool(self.filter_dedup_url.isChecked())
        self.config_manager.config["PRELLM_DEDUP_BY_TITLE"] = bool(self.filter_dedup_title.isChecked())
        self.config_manager.config["PRELLM_TOPIC_OVERRIDES"] = self._overrides_with_keywords()
        self.config_manager.config["FETCH_MAX_ARTICLES_PER_RUN"] = int(self.max_articles_run_spin.value())
        self.config_manager.config["FETCH_MAX_ARTICLES_PER_QUERY"] = int(self.max_articles_per_query_spin.value())

    def _toggle_password_visibility(self, line_edit):
        if line_edit.echoMode() == QLineEdit.EchoMode.Password:
            line_edit.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            line_edit.setEchoMode(QLineEdit.EchoMode.Password)

    def _update_threshold_label(self):
        self.threshold_label.setText(f"{self.threshold_slider.value() / 100:.2f}")

    def _selected_languages_csv(self) -> str:
        selected = [code for code, checkbox in self.language_checkboxes.items() if checkbox.isChecked()]
        if not selected:
            selected = ["en"]
            if "en" in self.language_checkboxes:
                self.language_checkboxes["en"].setChecked(True)
        return ",".join(selected)

    def _refresh_search_terms(self):
        self.terms_list.clear()
        terms = self.search_manager.get_search_terms()
        for term in terms:
            self.terms_list.addItem(term['term'])
        if hasattr(self, "filter_topic_words_combo"):
            self._refresh_filter_topic_words_topics()
        self._update_workspace_state_banner()

    def _add_search_term(self):
        term, ok = QInputDialog.getText(self, "Add Search Term", "Enter new search term:")
        if ok and term:
            self.search_manager.insert_search_term(term)
            self._refresh_search_terms()

    def _remove_search_term(self):
        current_row = self.terms_list.currentRow()
        current = self.terms_list.currentItem()
        if current:
            self.search_manager.delete_search_term(current.text())
            self._refresh_search_terms()

            # Auto-select the next item (same index now points to the one below)
            if self.terms_list.count() > 0:
                next_row = min(current_row, self.terms_list.count() - 1)
                self.terms_list.setCurrentRow(next_row)

    def _import_search_terms(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Search Terms File", "", "Text Files (*.txt);;All Files (*)")
        if file_path:
            try:
                count = self.search_manager.insert_search_terms_from_txt(file_path)
                self._refresh_search_terms()
                QMessageBox.information(self, "Success", f"Imported {count} search terms successfully!")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to import search terms: {e}")

    def _export_search_terms(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Search Terms", "", "Text Files (*.txt);;All Files (*)")
        if file_path:
            try:
                terms = self.search_manager.get_search_terms()
                with open(file_path, 'w', encoding='utf-8') as f:
                    for term in terms:
                        f.write(f"{term['term']}\n")
                QMessageBox.information(self, "Success", "Search terms exported successfully!")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export search terms: {e}")

    def _start_processing(self):
        """Validate configuration and start the end-to-end pipeline.

        Ensures API keys are present, resets UI counters, wires callbacks, and
        launches a ProcessingWorker to run fetch/clean/analyze steps.
        """
        try:
            self._apply_draft_to_live_config()
            missing_keys = self._missing_required_keys()
            if missing_keys:
                missing_labels = ", ".join(key.replace("_", " ").title() for key in missing_keys)
                QMessageBox.warning(
                    self,
                    "Configuration Error",
                    f"Missing required settings: {missing_labels}. Add keys under Workspace → API connections.",
                )
                self._navigate_to(2)
                return
            if not self.config_manager.validate():
                QMessageBox.warning(
                    self,
                    "Configuration Error",
                    "Configuration is invalid. Review Workspace settings.",
                )
                self._navigate_to(2)
                return

            valid_dates, date_error = self.date_range_widget.validate_selection()
            if not valid_dates:
                QMessageBox.warning(self, "Invalid Date Range", date_error)
                self._navigate_to(2)
                return
            date_params = self.date_range_widget.get_date_params()

            try:
                self.config_manager.save_config(self.config_manager.config)
            except OSError as exc:
                logger.warning("Could not persist configuration to disk before run: %s", exc)
            else:
                self._snapshot_saved_workspace()
                self._update_workspace_state_banner()

            # Reset fetched counter when starting new run
            self._reset_fetch_count_ui()
            search_terms = self.search_manager.get_search_terms()
            if not search_terms:
                QMessageBox.warning(self, "Warning", "No search terms defined. Please add search terms first.")
                return
            if not self._prepare_storage_for_new_run():
                return

            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self._processing = True
            self._allow_llm_progress_bar = False

            # Reset UI elements
            self._reset_phase_statuses()
            self.progress_bar.setValue(0)
            self.progress_counter.setText("0 / 0 articles scored for relevance")
            self.status_icon.setText("…")
            self.status_label.setText("Starting pipeline…")
            self._clear_run_logs()
            self.diagnostics_view.clear_issues()
            self._attach_run_log_handler()

            # Ensure pipeline has current config
            self.pipeline = PipelineManager(self.db_manager, self.config_manager)

            # Initialize worker with pipeline
            self.worker = ProcessingWorker(
                pipeline=self.pipeline,
                search_terms=search_terms,
                date_params=date_params
            )
            self.worker.progress_updated.connect(self._update_progress)
            self.worker.status_updated.connect(self._update_status)
            self.worker.completed.connect(self._handle_processing_complete)

            logger.info("Starting full processing workflow")
            self.worker.start()
            
        except Exception as e:
            self._detach_run_log_handler()
            QMessageBox.critical(self, "Error", f"Failed to start processing: {e}")
            logger.exception("Failed to start processing")
            logger.error(f"Processing start error: {e}")
            return

    def _handle_processing_complete(self, results):
        """Finalize UI state after the worker completes.

        Args:
            results: PipelineRunResult from the pipeline, or legacy list of articles.
        """
        self._allow_llm_progress_bar = False
        if isinstance(results, PipelineRunResult):
            articles = results.relevant_articles
            if results.analysis_errors:
                logger.warning(
                    "Processing completed with %s analysis errors (%s articles scored)",
                    results.analysis_errors,
                    results.articles_analyzed,
                )
        elif isinstance(results, list):
            articles = results
        else:
            articles = []
        result_count = len(articles) if articles else 0
        logger.info(f"Processing completed with {result_count} relevant results")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._processing = False
        
        if articles:
            # Mark all phases as complete
            self._update_phase_status('fetch', "Complete", 100, is_complete=True)
            self._update_phase_status('clean', "Complete", 100, is_complete=True)
            self._update_phase_status('gate', "Complete", 100, is_complete=True)
            self._update_phase_status('analyze', "Complete", 100, is_complete=True)
            
            # Update results tab and UI
            self._update_results(articles)
            self._update_previews()
            
            # Results already contain only relevant articles
            relevant_count = len(articles)

            if isinstance(results, PipelineRunResult) and results.analysis_errors:
                QMessageBox.warning(
                    self,
                    "Completed with warnings",
                    f"Processed {relevant_count} relevant article(s). "
                    f"{results.analysis_errors} article(s) failed during relevance analysis.",
                )
            else:
                QMessageBox.information(
                    self,
                    "Success",
                    f"Processed {relevant_count} relevant articles successfully.",
                )
            logger.info(
                f"Successfully processed {relevant_count} relevant articles."
            )
            self.results_exported_this_session = False
        else:
            self._reset_phase_statuses()
            if isinstance(results, PipelineRunResult) and results.analysis_errors:
                QMessageBox.warning(
                    self,
                    "Warning",
                    f"No relevant articles were saved. {results.analysis_errors} article(s) "
                    "failed during relevance analysis.",
                )
                logger.warning(
                    "No relevant articles; analysis errors=%s", results.analysis_errors
                )
            else:
                QMessageBox.warning(self, "Warning", "No articles were processed")
                logger.warning("No articles were processed")
            self._update_previews()
        if hasattr(self, "filter_insights_output"):
            self._update_filtering_insights()
        if isinstance(results, PipelineRunResult):
            self._last_pipeline_result = results
            self.diagnostics_view.set_structured_markdown(format_run_metrics_markdown(results))
            self.run_page.set_inspection_html(self._format_inspection_html(results))
        if hasattr(self, "overview_dashboard"):
            self.overview_dashboard.refresh()
        self._detach_run_log_handler()

    def _format_inspection_html(self, result: PipelineRunResult) -> str:
        m = result.run_metrics if isinstance(result.run_metrics, dict) else {}
        parts = [
            "<h3>Run inspection</h3>",
            "<p>Same last-run telemetry as Diagnostics, formatted for quick scanning on the Run page.</p><ul>",
        ]
        fetch = m.get("fetch")
        if isinstance(fetch, dict):
            parts.append(f"<li><b>Fetch</b>: {html.escape(json.dumps(fetch, indent=0)[:800])}</li>")
        clean = m.get("clean")
        if isinstance(clean, dict):
            parts.append(f"<li><b>Normalize</b>: {html.escape(str(clean))}</li>")
        pre = m.get("pre_llm")
        if isinstance(pre, dict):
            parts.append(f"<li><b>Gate</b>: {html.escape(str({k: pre[k] for k in pre if k != 'dropped_by_reason'}))}</li>")
            dr = pre.get("dropped_by_reason")
            if isinstance(dr, dict) and dr:
                parts.append("<li><b>Drop reasons (aggregate)</b><ul>")
                for reason, cnt in sorted(dr.items(), key=lambda x: (-x[1], x[0]))[:12]:
                    parts.append(f"<li>{html.escape(str(reason))}: <b>{cnt}</b></li>")
                parts.append("</ul></li>")
        eff = m.get("effective_settings")
        if isinstance(eff, dict):
            parts.append(f"<li><b>Settings snapshot</b>: {html.escape(str(eff)[:1200])}</li>")
        parts.append("</ul>")
        parts.append(
            "<p><i>Limitation: per-query expansion plans and per-article pre-filter decisions are not persisted "
            "for drill-down; only aggregate telemetry is available today.</i></p>"
        )
        return "".join(parts)

    def _prepare_storage_for_new_run(self) -> bool:
        """Clear raw rows and resolve pre-existing relevant rows safely."""
        # Raw rows should clear immediately, independent of relevant export choice.
        self.db_manager.execute_query("DELETE FROM raw_articles")
        relevant_count = self.db_manager.get_table_row_count("relevant_articles")
        if relevant_count > 0 and not self.results_exported_this_session:
            choice_box = QMessageBox(self)
            choice_box.setIcon(QMessageBox.Icon.Warning)
            choice_box.setWindowTitle("Unexported Results Detected")
            choice_box.setText(
                "Relevant articles already exist and have not been exported this session.\n"
                "Choose how to proceed before starting a new run."
            )
            clear_btn = choice_box.addButton("Clear results", QMessageBox.ButtonRole.AcceptRole)
            export_clear_btn = choice_box.addButton(
                "Export and clear results", QMessageBox.ButtonRole.ActionRole
            )
            choice_box.exec()
            selected = choice_box.clickedButton()
            if selected is None:
                return False

            if selected == export_clear_btn:
                if not self._export_results():
                    return False
            elif selected != clear_btn:
                return False

        if relevant_count > 0:
            self.db_manager.execute_query("DELETE FROM relevant_articles")
        self._update_previews()
        return True

    def _stop_processing(self):
        if self.worker:
            self.worker.stop()
        if self.pipeline:
            try:
                self.pipeline.cancel()
            except Exception as e:
                logger.error(f"Error cancelling pipeline from GUI: {e}")
        self._processing = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_icon.setText("[]")
        self.status_label.setText("Processing stopped by user")
        self._reset_phase_statuses()
        self._allow_llm_progress_bar = False
        self._detach_run_log_handler()

    def _update_progress(self, current, total):
        if not self._allow_llm_progress_bar:
            return
        if total > 0:
            percentage = round((current / total) * 100)  # Round to nearest integer
            self.progress_bar.setValue(int(percentage))  # Explicitly convert to int
            self.progress_counter.setText(f"{current} / {total} articles scored for relevance")

    def _update_status(self, message, is_error, is_warning, is_success):
        """Update status labels and phase progress based on worker callbacks.

        Args:
            message: Human-readable status text from the pipeline.
            is_error: True when the pipeline reported an error.
            is_warning: True when the pipeline reported a non-fatal warning.
            is_success: True when a step completed successfully.
        """
        status = self.status_parser.parse(
            message,
            is_error=is_error,
            is_warning=is_warning,
            is_success=is_success,
        )
        if status.analysis_started or status.analysis_progress:
            self._allow_llm_progress_bar = True
        self.state.update_from_status(status)
        self._render_status(status)

    def _render_status(self, status: StatusUpdate):
        """Render parsed status into the UI (icons, labels, progress)."""
        logger.info(f"Status update: {status.message}")
        self.status_label.setText(status.message)
        self.statusBar().showMessage(status.message)

        if status.fetch_complete and status.counts.fetched_run_unique is not None:
            self.fetch_count_caption.setText("Unique URLs kept this run:")
            self._update_fetched_count(status.counts.fetched_run_unique)
        elif status.counts.fetched is not None:
            if not status.fetch_complete:
                self.fetch_count_caption.setText("Rows returned so far (before run dedup):")
            self._update_fetched_count(status.counts.fetched)

        if status.analysis_started:
            self._update_phase_status('analyze', "In Progress", 0)
        if status.analysis_progress:
            current = status.analysis_progress.current
            total = status.analysis_progress.total
            progress = (current / total * 100) if total > 0 else 0
            self._update_phase_status('analyze', f"Analyzing: {current}/{total}", progress)

        if status.cleaning_started:
            if status.cleaning_progress:
                current = status.cleaning_progress.current
                total = status.cleaning_progress.total
                progress = (current / total * 100) if total > 0 else 0
                self._update_phase_status('clean', f"Cleaning: {current}/{total}", progress)
            else:
                self._update_phase_status('clean', "Cleaning", 0)

        if status.term_progress:
            current = status.term_progress.current
            total = status.term_progress.total
            progress = (current / total * 100) if total > 0 else 0
            self._update_phase_status('fetch', f"Fetching: {current}/{total}", progress)

        if status.fetch_complete and not status.rate_limited:
            self._update_phase_status('fetch', "Complete", 100, is_complete=True)
        elif status.rate_limited:
            self._update_phase_status('fetch', "Rate Limited", 100, is_complete=True)

        if status.cleaning_complete:
            self._update_phase_status('clean', "Complete", 100, is_complete=True)

        if status.analysis_complete:
            self._update_phase_status('analyze', "Complete", 100, is_complete=True)

        msg_l = status.message.lower()
        if "candidate filtering complete" in msg_l:
            self._update_phase_status("gate", status.message[:120], 100, is_complete=True)
        elif "filtering candidates before llm" in msg_l:
            self._update_phase_status("gate", "Running heuristics…", 55)

        if status.is_error:
            logger.error(f"Process error: {status.message}")
            self.status_icon.setText("X")
        elif status.is_warning:
            logger.warning(f"Process warning: {status.message}")
            self.status_icon.setText("!")
        elif status.is_success:
            logger.info(f"Process success: {status.message}")
            self.status_icon.setText("V")
        else:
            self.status_icon.setText("...")

    def _update_phase_status(self, phase, status, progress=0, is_error=False, is_complete=False):
        """Update pipeline stage row on Run & pipeline view."""
        _, lab, bar = self.run_page.stage_widgets(phase)
        if lab is None or bar is None:
            return
        icon, _, _ = self.run_page.stage_widgets(phase)
        if icon is None:
            return
        if is_error:
            icon.setText("✕")
        elif is_complete:
            icon.setText("✓")
        else:
            icon.setText("…")

        labels = {
            "fetch": "Fetch from API",
            "clean": "Validate content",
            "gate": "Pre-AI gate",
            "analyze": "Relevance scoring",
        }
        prefix = labels.get(phase, phase.title())

        if phase == "fetch" and not is_complete and not is_error and "/" in status:
            lab.setText(f"{prefix}: {status}")
        else:
            lab.setText(f"{prefix}: {status}")
        if progress >= 0:
            bar.setValue(int(progress))

    def _reset_phase_statuses(self):
        for phase in ("fetch", "clean", "gate", "analyze"):
            self._update_phase_status(phase, "waiting", 0)
            icon, _, _ = self.run_page.stage_widgets(phase)
            if icon:
                icon.setText("○")

    def _update_raw_count(self):
        """Update the raw articles count from database"""
        raw_count = len(self.db_manager.execute_query("SELECT id FROM raw_articles"))
        self.raw_count_label.setText(str(raw_count))

    def _update_fetched_count(self, count: int):
        """Update the fetched count value (caption describes pre vs post dedup)."""
        self.fetched_count_label.setText(str(count))

    def _reset_fetch_count_ui(self):
        """Reset fetch counters and caption at the start of a pipeline run."""
        self.fetch_count_caption.setText("Rows returned so far (before run dedup):")
        self._update_fetched_count(0)

    def _attach_run_log_handler(self):
        """Attach a GUI logging handler to active project loggers."""
        if self._gui_log_handler is not None:
            return

        handler = GuiLogHandler(self._gui_log_bridge)
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

        targets = []
        for logger_obj in logging.Logger.manager.loggerDict.values():
            if isinstance(logger_obj, logging.Logger) and logger_obj.handlers:
                logger_obj.addHandler(handler)
                targets.append(logger_obj)

        if not targets:
            root_logger = logging.getLogger()
            root_logger.addHandler(handler)
            targets.append(root_logger)

        self._gui_log_handler = handler
        self._gui_log_targets = targets

    def _detach_run_log_handler(self):
        """Detach GUI logging handler to avoid duplicate log fanout."""
        if self._gui_log_handler is None:
            return
        for logger_obj in self._gui_log_targets:
            try:
                logger_obj.removeHandler(self._gui_log_handler)
            except Exception:
                pass
        self._gui_log_targets = []
        self._gui_log_handler = None

    def _clear_run_logs(self):
        if hasattr(self, "diagnostics_view") and self.diagnostics_view is not None:
            self.diagnostics_view.clear_raw()
            self.diagnostics_view.clear_issues()

    def _append_run_log_line(self, message: str):
        """Forward log lines to Diagnostics raw pane and capture issues."""
        if not message or not hasattr(self, "diagnostics_view") or self.diagnostics_view is None:
            return
        self.diagnostics_view.append_raw_line(message)
        low = message.lower()
        if " - error - " in low:
            self.diagnostics_view.append_issue("error", message[:500])
        elif " - warning - " in low:
            self.diagnostics_view.append_issue("warning", message[:500])

    def _results_url_column_index(self) -> int:
        for i, (key, _, _) in enumerate(self._active_results_columns):
            if key == "url":
                return i
        return 0

    def _enrich_result_row(self, row: dict) -> dict:
        """Normalize DB / pipeline dicts for display and export."""
        if not isinstance(row, dict):
            return {}
        out = dict(row)
        out.setdefault("api_uuid", str(out.get("api_uuid") or out.get("uuid") or "").strip())
        out.setdefault("description", str(out.get("description") or "").strip())
        out.setdefault("keywords", str(out.get("keywords") or "").strip())
        out.setdefault("snippet", str(out.get("snippet") or "").strip())
        out.setdefault("language", str(out.get("language") or "").strip())
        img = out.get("url_to_image") or out.get("image_url") or ""
        out["url_to_image"] = str(img or "").strip()
        out.setdefault("published_at", str(out.get("published_at") or "").strip())
        src = out.get("source", "") or ""
        if isinstance(src, dict):
            src = extract_source_name(src, default="")
        out["source"] = str(src or "").strip()
        out.setdefault("title", str(out.get("title") or "").strip())
        out.setdefault("url", str(out.get("url") or "").strip())
        out.setdefault("content", str(out.get("content") or "").strip())
        if not str(out.get("api_categories") or "").strip():
            cat = out.get("categories")
            if isinstance(cat, list):
                out["api_categories"] = json.dumps(cat, ensure_ascii=False)
            elif isinstance(cat, str) and cat.strip():
                out["api_categories"] = cat.strip()
            else:
                out["api_categories"] = "[]"
        return out

    def _format_categories_cell(self, row: dict) -> str:
        raw = row.get("api_categories") or row.get("categories") or "[]"
        if isinstance(raw, list):
            parts = [str(x).strip() for x in raw if str(x).strip()]
            return ", ".join(parts)
        s = str(raw).strip()
        if not s:
            return ""
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return ", ".join(str(x).strip() for x in parsed if str(x).strip())
        except json.JSONDecodeError:
            pass
        return s

    def _result_cell_text(self, row: dict, column_key: str) -> str:
        if column_key == "categories_display":
            return self._format_categories_cell(row)
        if column_key == "relevance_score":
            rs = row.get("relevance_score")
            try:
                return f"{float(rs):.6f}".rstrip("0").rstrip(".")
            except (TypeError, ValueError):
                return str(rs) if rs is not None else ""
        val = row.get(column_key, "")
        return str(val) if val is not None else ""

    def _result_row_search_blob(self, row: dict) -> str:
        parts = [
            row.get("title", ""),
            row.get("description", ""),
            row.get("keywords", ""),
            row.get("snippet", ""),
            row.get("url", ""),
            row.get("source", ""),
            row.get("api_uuid", ""),
            row.get("language", ""),
            self._format_categories_cell(row),
        ]
        return " ".join(str(p) for p in parts).lower()

    def _result_to_api_export_dict(self, row: dict) -> dict:
        """Shape one row like TheNewsAPI article objects (+ our relevance_score)."""
        r = self._enrich_result_row(row)
        raw_cat = r.get("api_categories") or r.get("categories") or "[]"
        categories: list = []
        if isinstance(raw_cat, list):
            categories = [str(x) for x in raw_cat]
        else:
            try:
                parsed = json.loads(str(raw_cat).strip() or "[]")
                if isinstance(parsed, list):
                    categories = [str(x) for x in parsed]
                else:
                    categories = [str(parsed)]
            except json.JSONDecodeError:
                s = str(raw_cat).strip()
                categories = [s] if s else []
        rel = r.get("relevance_score")
        try:
            relevance_score = float(rel) if rel is not None and rel != "" else None
        except (TypeError, ValueError):
            relevance_score = rel
        return {
            "uuid": r.get("api_uuid", "") or "",
            "title": r.get("title", "") or "",
            "description": r.get("description", "") or "",
            "keywords": r.get("keywords", "") or "",
            "snippet": r.get("snippet", "") or "",
            "url": r.get("url", "") or "",
            "image_url": r.get("url_to_image", "") or "",
            "language": r.get("language", "") or "",
            "published_at": r.get("published_at", "") or "",
            "source": r.get("source", "") or "",
            "categories": categories,
            "relevance_score": relevance_score,
        }

    def _show_results_context_menu(self, position):
        idx = self.results_table.indexAt(position)
        if not idx.isValid():
            return
        row_i = idx.row()
        item0 = self.results_table.item(row_i, 0)
        if not item0:
            return
        menu = QMenu()
        copy_action = QAction("Copy URL", self)
        copy_action.triggered.connect(lambda: self._copy_result_url_for_row(row_i))
        menu.addAction(copy_action)
        open_action = QAction("Open in Browser", self)
        open_action.triggered.connect(lambda: self._open_result_url_for_row(row_i))
        menu.addAction(open_action)
        menu.exec(self.results_table.viewport().mapToGlobal(position))

    def _result_payload_for_row(self, row_index: int) -> dict:
        item0 = self.results_table.item(row_index, 0)
        if not item0:
            return {}
        data = item0.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else {}

    def _copy_result_url_for_row(self, row_index: int):
        col = self._results_url_column_index()
        item = self.results_table.item(row_index, col)
        url = item.text() if item else ""
        if not url:
            url = self._result_payload_for_row(row_index).get("url", "")
        QApplication.clipboard().setText(url)
        self.statusBar().showMessage("URL copied to clipboard", 3000)

    def _open_result_url_for_row(self, row_index: int):
        import webbrowser
        col = self._results_url_column_index()
        item = self.results_table.item(row_index, col)
        url = item.text() if item else ""
        if not url:
            url = self._result_payload_for_row(row_index).get("url", "")
        if url:
            webbrowser.open(url)

    def _add_result_row(self, result: dict):
        """Append one enriched row to the results table."""
        try:
            full = self._enrich_result_row(result)
            row_i = self.results_table.rowCount()
            self.results_table.insertRow(row_i)
            for col, (key, _, _) in enumerate(self._active_results_columns):
                text = self._result_cell_text(full, key)
                cell = QTableWidgetItem(text)
                cell.setToolTip(text if len(text) < 2000 else text[:1997] + "…")
                if col == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, full)
                self.results_table.setItem(row_i, col, cell)
        except Exception as e:
            logger.error("Error adding result row: %s", e)
            
    def _filter_results(self):
        search_text = self.search_box.text().lower()
        relevance_idx = self.relevance_filter.currentIndex()
        min_relevance = {
            0: 0.0,
            1: 0.3,
            2: 0.5,
            3: 0.7,
            4: 0.9,
        }.get(relevance_idx, 0.0)

        self.results_table.setRowCount(0)
        for result in self.all_results:
            relevance = result.get("relevance_score", 0)
            try:
                rel_f = float(relevance)
            except (TypeError, ValueError):
                rel_f = 0.0
            blob = self._result_row_search_blob(self._enrich_result_row(result))
            if search_text in blob and rel_f >= min_relevance:
                self._add_result_row(result)

    def _export_results(self) -> bool:
        """Export the current results to a file."""
        if not self.all_results:
            QMessageBox.warning(self, "Warning", "No results to export")
            return False

        # Get the current relevance filter setting
        relevance_idx = self.relevance_filter.currentIndex()
        min_relevance = {
            0: 0.0,
            1: 0.3,
            2: 0.5,
            3: 0.7,
            4: 0.9,
        }.get(relevance_idx, 0.0)

        # Get the current search filter
        search_text = self.search_box.text().lower()
        
        # Filter results based on current criteria
        def _rel_ge(row: dict, minimum: float) -> bool:
            try:
                return float(row.get("relevance_score", 0)) >= minimum
            except (TypeError, ValueError):
                return False

        filtered_results = [
            result
            for result in self.all_results
            if _rel_ge(result, min_relevance)
            and search_text in self._result_row_search_blob(self._enrich_result_row(result))
        ]
        
        if not filtered_results:
            QMessageBox.warning(self, "Warning", "No results match your current filter criteria")
            return False

        file_path, file_type = QFileDialog.getSaveFileName(
            self,
            "Export Results",
            str(Path.home() / "Desktop"),
            "CSV Files (*.csv);;JSON Files (*.json);;Text Files (*.txt);;All Files (*)"
        )
        
        if not file_path:
            return False

        try:
            # Write results based on file type
            if file_path.endswith('.csv'):
                self._export_to_csv(file_path, filtered_results)
            elif file_path.endswith('.json'):
                self._export_to_json(file_path, filtered_results)
            else:
                self._export_to_txt(file_path, filtered_results)

            self.results_exported_this_session = True
            QMessageBox.information(self, "Success", f"Results exported to {file_path}")
            return True
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export results: {str(e)}")
            return False

    def _export_to_csv(self, file_path, results):
        """Export results to CSV (API fields plus a short summary column)."""
        import csv

        base_fields = [
            "uuid",
            "title",
            "description",
            "keywords",
            "snippet",
            "url",
            "image_url",
            "language",
            "published_at",
            "source",
            "categories",
            "relevance_score",
        ]
        fieldnames = base_fields + ["event | location | actor"]
        # Use UTF-8 BOM so spreadsheet apps (e.g. Excel) detect Unicode reliably.
        with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for result in results:
                api = self._result_to_api_export_dict(result)
                row = {
                    "uuid": api["uuid"],
                    "title": api["title"],
                    "description": api["description"],
                    "keywords": api["keywords"],
                    "snippet": api["snippet"],
                    "url": api["url"],
                    "image_url": api["image_url"],
                    "language": api["language"],
                    "published_at": api["published_at"],
                    "source": api["source"],
                    "categories": ", ".join(api["categories"]) if api["categories"] else "",
                    "relevance_score": api["relevance_score"],
                    "event | location | actor": self._build_export_summary(result),
                }
                writer.writerow(row)

    def _build_export_summary(self, result):
        """Build a compact 4-7 word keyphrase summary for export."""
        generic_phrases = (
            "this article",
            "passed the relevance filter",
            "high-priority for review",
            "merits attention",
            "related to pharmaceutical security monitoring",
            "this incident highlights",
            "this case highlights",
            "highlights ongoing",
            "addresses the serious issue",
            "this operation",
            "this enforcement action",
            "underscores the",
        )
        stopwords = {
            "the", "a", "an", "this", "that", "is", "are", "was", "were", "to", "of",
            "and", "for", "in", "on", "with", "by", "it", "its", "their", "has", "have",
            "be", "been", "being", "as", "at", "from",
        }

        def _clean_text(value):
            text = re.sub(r"\s+", " ", str(value or "")).strip()
            text = re.sub(r"https?://\S+", "", text).strip()
            return text

        def _normalize_phrase(value):
            text = _clean_text(value)
            if not text:
                return ""
            text = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()
            text = re.sub(
                (
                    r"^(this\s+(incident|case|operation|enforcement action)\s+"
                    r"(highlights|underscores|shows|demonstrates)\s+)"
                ),
                "",
                text,
                flags=re.IGNORECASE,
            )
            text = re.sub(r"^(highlights|addresses|underscores)\s+", "", text, flags=re.IGNORECASE)
            text = re.sub(
                r"\b(the ongoing issue of|the serious issue of|the need for|efforts to)\b",
                "",
                text,
                flags=re.IGNORECASE,
            )
            return re.sub(r"\s+", " ", text).strip(" ,;:-.")

        def _is_generic(value):
            text = _clean_text(value).lower()
            return any(phrase in text for phrase in generic_phrases)

        def _few_words(value, max_words=7):
            text = _normalize_phrase(value)
            if not text:
                return ""
            tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9'/-]*", text)
            filtered = [t for t in tokens if t.lower() not in stopwords]
            words = filtered or tokens
            return " ".join(words[:max_words]).strip()

        # Prefer structured fields first for concise signal.
        event = _few_words(result.get("event", ""), max_words=4)
        where_location = _few_words(result.get("where_location", ""), max_words=2)
        who_entities = _few_words(result.get("who_entities", ""), max_words=3)
        structured_parts = [p for p in (event, where_location, who_entities) if p]
        if structured_parts:
            return " | ".join(structured_parts[:3])[:80].strip(" |")

        # Fall back through narrative fields, but force short keyphrase output.
        for field in ("incident_sentence", "why_it_matters", "explanation", "title", "content", "snippet"):
            raw = result.get(field, "")
            if raw and not _is_generic(raw):
                short = _few_words(raw, max_words=7)
                if short:
                    return short

        # Last fallback: still keep it short.
        return "pharma incident"

    def _export_to_json(self, file_path, results):
        """Export as a JSON array of API-shaped article objects."""
        import json

        payload = [self._result_to_api_export_dict(r) for r in results]
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

    def _export_to_txt(self, file_path, results):
        """Export human-readable text with all API-style fields per article."""
        with open(file_path, "w", encoding="utf-8") as f:
            for result in results:
                api = self._result_to_api_export_dict(result)
                f.write(f"uuid: {api['uuid']}\n")
                f.write(f"title: {api['title']}\n")
                f.write(f"description: {api['description']}\n")
                f.write(f"keywords: {api['keywords']}\n")
                f.write(f"snippet: {api['snippet']}\n")
                f.write(f"url: {api['url']}\n")
                f.write(f"image_url: {api['image_url']}\n")
                f.write(f"language: {api['language']}\n")
                f.write(f"published_at: {api['published_at']}\n")
                f.write(f"source: {api['source']}\n")
                f.write(f"categories: {', '.join(api['categories'])}\n")
                f.write(f"relevance_score: {api['relevance_score']}\n")
                f.write(f"summary: {self._build_export_summary(result)}\n")
                f.write("-" * 80 + "\n")

    def _update_results(self, results):
        """Update results tab with processed articles"""
        # Filter out None or invalid results
        valid_results = [r for r in results if r is not None and isinstance(r, dict)]
        self.all_results = valid_results
        
        if not valid_results:
            logger.warning("No valid results to display")
            self.statusBar().showMessage("No valid results found")
            return

        self.results_table.setRowCount(0)
        for result in valid_results:
            self._add_result_row(result)

        self.statusBar().showMessage(f"Loaded {len(valid_results)} results")

    def _load_results_from_database(self):
        """Load persisted relevant articles into the Results tab on app startup."""
        try:
            rows = self.db_manager.execute_query(
                """
                SELECT
                    r.title AS title,
                    r.relevance_score AS relevance_score,
                    r.url AS url,
                    r.content AS content,
                    r.url_to_image AS url_to_image,
                    r.published_at AS published_at,
                    r.source AS source,
                    r.explanation AS explanation,
                    r.event AS event,
                    r.who_entities AS who_entities,
                    r.where_location AS where_location,
                    r.impact AS impact,
                    r.urgency AS urgency,
                    r.why_it_matters AS why_it_matters,
                    r.incident_sentence AS incident_sentence,
                    COALESCE(NULLIF(TRIM(r.api_uuid), ''), NULLIF(TRIM(rw.api_uuid), ''), '') AS api_uuid,
                    COALESCE(NULLIF(TRIM(r.description), ''), NULLIF(TRIM(rw.description), ''), '') AS description,
                    COALESCE(NULLIF(TRIM(r.snippet), ''), NULLIF(TRIM(rw.snippet), ''), '') AS snippet,
                    COALESCE(NULLIF(TRIM(r.keywords), ''), NULLIF(TRIM(rw.keywords), ''), '') AS keywords,
                    COALESCE(NULLIF(TRIM(r.language), ''), NULLIF(TRIM(rw.language), ''), '') AS language,
                    COALESCE(
                        NULLIF(TRIM(r.api_categories), ''),
                        NULLIF(TRIM(rw.categories), ''),
                        '[]'
                    ) AS api_categories
                FROM relevant_articles r
                LEFT JOIN raw_articles rw ON r.raw_article_id = rw.id
                ORDER BY r.id DESC
                """
            ) or []
            self._update_results(rows)
        except Exception as e:
            logger.error(f"Failed to load persisted results: {e}")
            self.all_results = []

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
        self._detach_run_log_handler()
        event.accept()
