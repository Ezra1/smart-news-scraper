"""PyQt6 desktop interface for the Smart News Scraper.

The GUI lets users configure API keys, manage search terms, launch the end-to-end
scraping pipeline, and review/export relevance-scored articles. Launch from the
repository root with:

    python -m src.qt_gui

Key elements:
- Configuration tab for API keys, relevance thresholds, and ChatGPT context
- Search Terms tab for CRUD and file import/export
- Processing tab to run the pipeline with live progress
- Results tab to filter, inspect, and export processed articles
"""

from PyQt6.QtWidgets import (
    QMainWindow, QApplication, QWidget, QPushButton, QLabel, QVBoxLayout,
    QHBoxLayout, QTabWidget, QLineEdit, QFrame, QListWidget, QProgressBar,
    QScrollArea, QTreeWidget, QTreeWidgetItem, QMessageBox, QFileDialog,
    QComboBox, QSlider, QInputDialog, QGroupBox, QMenu, QGridLayout, QTextEdit,
    QRadioButton, QDateEdit, QButtonGroup, QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QDate, QObject
from PyQt6.QtGui import QFont, QIcon, QAction
from pathlib import Path
from datetime import datetime, timedelta
import asyncio
import logging
import re
import sys
from queue import Queue

from src.logger_config import setup_logging
from src.config import ConfigManager
from src.database_manager import DatabaseManager, ArticleManager, SearchTermManager
from src.pipeline_manager import PipelineManager
from src.pipeline_factory import create_pipeline
from src.api_validator import validate_news_api_key, validate_openai_api_key
from src.gui.status_parser import StatusParser, StatusUpdate
from src.gui.processing_state import ProcessingState

logger = setup_logging(__name__)

SUPPORTED_LANGUAGES = [
    ("en", "English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("pt", "Portuguese"),
    ("ar", "Arabic"),
    ("ru", "Russian"),
    ("zh", "Chinese"),
    ("hi", "Hindi"),
]

SUPPORTED_REGIONS = [
    ("us", "United States"),
    ("gb", "United Kingdom"),
    ("ca", "Canada"),
    ("au", "Australia"),
    ("es", "Spain"),
    ("mx", "Mexico"),
    ("fr", "France"),
    ("pt", "Portugal"),
    ("br", "Brazil"),
    ("ae", "UAE"),
    ("sa", "Saudi Arabia"),
    ("eg", "Egypt"),
    ("ru", "Russia"),
    ("kz", "Kazakhstan"),
    ("cn", "China"),
    ("hk", "Hong Kong"),
    ("sg", "Singapore"),
    ("tw", "Taiwan"),
    ("in", "India"),
]

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
    completed = pyqtSignal(list)

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

class DateRangeWidget(QGroupBox):
    """Date range selector with presets and custom options."""

    def __init__(self, config_manager: ConfigManager, parent=None):
        super().__init__("Date Range", parent)
        self.config_manager = config_manager
        self._init_ui()
        self._load_from_config(config_manager.config)

    def _init_ui(self):
        layout = QVBoxLayout()

        # Radio buttons for mode selection
        self.mode_group = QButtonGroup(self)

        # Preset mode
        preset_layout = QHBoxLayout()
        self.preset_radio = QRadioButton("Preset:")
        self.preset_combo = QComboBox()
        self.preset_combo.addItems([
            "Last 24 hours",
            "Last 7 days",
            "Last 30 days",
            "Last 3 months",
            "Last 6 months",
            "Last year",
            "Last 2 years",
            "All time (no filter)"
        ])
        self.preset_combo.setCurrentText("Last 7 days")
        preset_layout.addWidget(self.preset_radio)
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addStretch()

        # Custom range mode
        custom_layout = QHBoxLayout()
        self.custom_radio = QRadioButton("Custom Range:")
        self.after_label = QLabel("After:")
        self.after_date = QDateEdit()
        self.after_date.setCalendarPopup(True)
        self.after_date.setDate(QDate.currentDate().addMonths(-1))
        self.before_label = QLabel("Before:")
        self.before_date = QDateEdit()
        self.before_date.setCalendarPopup(True)
        self.before_date.setDate(QDate.currentDate())
        custom_layout.addWidget(self.custom_radio)
        custom_layout.addWidget(self.after_label)
        custom_layout.addWidget(self.after_date)
        custom_layout.addWidget(self.before_label)
        custom_layout.addWidget(self.before_date)
        custom_layout.addStretch()

        # Specific date mode
        specific_layout = QHBoxLayout()
        self.specific_radio = QRadioButton("Specific Date:")
        self.specific_date = QDateEdit()
        self.specific_date.setCalendarPopup(True)
        self.specific_date.setDate(QDate.currentDate())
        specific_layout.addWidget(self.specific_radio)
        specific_layout.addWidget(self.specific_date)
        specific_layout.addStretch()

        # Add to button group
        self.mode_group.addButton(self.preset_radio, 0)
        self.mode_group.addButton(self.custom_radio, 1)
        self.mode_group.addButton(self.specific_radio, 2)
        self.preset_radio.setChecked(True)

        # Connect signals to enable/disable widgets
        self.preset_radio.toggled.connect(self._update_enabled_state)
        self.custom_radio.toggled.connect(self._update_enabled_state)
        self.specific_radio.toggled.connect(self._update_enabled_state)

        layout.addLayout(preset_layout)
        layout.addLayout(custom_layout)
        layout.addLayout(specific_layout)
        self.setLayout(layout)

        self._update_enabled_state()

    def _load_from_config(self, config: dict):
        """Restore saved preferences into the widget."""
        mode = config.get("DATE_RANGE_MODE", "preset")
        preset = config.get("DATE_RANGE_PRESET", "Last 7 days")
        after = config.get("DATE_RANGE_AFTER", "")
        before = config.get("DATE_RANGE_BEFORE", "")
        specific = config.get("DATE_RANGE_ON", "")

        mode_map = {
            "preset": self.preset_radio,
            "custom": self.custom_radio,
            "specific": self.specific_radio
        }
        if mode in mode_map:
            mode_map[mode].setChecked(True)
        else:
            self.preset_radio.setChecked(True)

        if preset:
            self.preset_combo.setCurrentText(preset)

        if after:
            self.after_date.setDate(self._parse_date(after, fallback=QDate.currentDate().addMonths(-1)))
        if before:
            self.before_date.setDate(self._parse_date(before, fallback=QDate.currentDate()))
        if specific:
            self.specific_date.setDate(self._parse_date(specific, fallback=QDate.currentDate()))

        self._update_enabled_state()

    def _parse_date(self, date_str: str, fallback: QDate) -> QDate:
        parsed = QDate.fromString(date_str, "yyyy-MM-dd")
        return parsed if parsed.isValid() else fallback

    def _update_enabled_state(self):
        """Enable/disable date pickers based on selected mode."""
        self.preset_combo.setEnabled(self.preset_radio.isChecked())
        self.after_date.setEnabled(self.custom_radio.isChecked())
        self.before_date.setEnabled(self.custom_radio.isChecked())
        self.specific_date.setEnabled(self.specific_radio.isChecked())

    def get_date_params(self) -> dict:
        """Return dict with published_after, published_before, or published_on."""
        params: dict = {}
        today = datetime.now()

        if self.preset_radio.isChecked():
            preset = self.preset_combo.currentText()
            if preset == "Last 24 hours":
                after = today - timedelta(days=1)
            elif preset == "Last 7 days":
                after = today - timedelta(days=7)
            elif preset == "Last 30 days":
                after = today - timedelta(days=30)
            elif preset == "Last 3 months":
                after = today - timedelta(days=90)
            elif preset == "Last 6 months":
                after = today - timedelta(days=180)
            elif preset == "Last year":
                after = today - timedelta(days=365)
            elif preset == "Last 2 years":
                after = today - timedelta(days=730)
            elif preset == "All time (no filter)":
                return {}
            else:
                after = today - timedelta(days=7)
            params["published_after"] = after.strftime("%Y-%m-%d")

        elif self.custom_radio.isChecked():
            after_qdate = self.after_date.date()
            before_qdate = self.before_date.date()
            params["published_after"] = after_qdate.toString("yyyy-MM-dd")
            params["published_before"] = before_qdate.toString("yyyy-MM-dd")

        elif self.specific_radio.isChecked():
            specific_qdate = self.specific_date.date()
            params["published_on"] = specific_qdate.toString("yyyy-MM-dd")

        return params

    def validate_selection(self) -> tuple[bool, str]:
        """Validate user input for date selections."""
        today = QDate.currentDate()

        if self.custom_radio.isChecked():
            if self.after_date.date() > self.before_date.date():
                return False, "The 'After' date must be on or before the 'Before' date."
            if self.before_date.date() > today:
                return False, "The 'Before' date cannot be in the future."

        if self.specific_radio.isChecked():
            if self.specific_date.date() > today:
                return False, "The specific date cannot be in the future."

        return True, ""

    def get_config_values(self) -> dict:
        """Return config-friendly representation of the widget state."""
        mode = "preset" if self.preset_radio.isChecked() else "custom" if self.custom_radio.isChecked() else "specific"
        return {
            "DATE_RANGE_MODE": mode,
            "DATE_RANGE_PRESET": self.preset_combo.currentText(),
            "DATE_RANGE_AFTER": self.after_date.date().toString("yyyy-MM-dd"),
            "DATE_RANGE_BEFORE": self.before_date.date().toString("yyyy-MM-dd"),
            "DATE_RANGE_ON": self.specific_date.date().toString("yyyy-MM-dd"),
        }

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
        self.run_log_max_lines = 2000
        self._gui_log_bridge = GuiLogBridge()
        self._gui_log_bridge.log_message.connect(self._append_run_log_line)
        self._gui_log_handler = None
        self._gui_log_targets = []
        
        # Defer processor initialization until needed
        self.processor = None

        # Setup UI
        self._setup_ui()
        self._setup_styles()
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
            f"Configuration needed: add {missing_labels} in the Configuration tab before starting processing."
        )

    def _setup_ui(self):
        """Build the tabbed interface and base widgets."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Create tab widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Add tabs
        self._create_config_tab()
        self._create_search_terms_tab()
        self._create_processing_tab()
        self._create_results_tab()

        # Status bar
        self.statusBar().showMessage("Ready")

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
                height: 12px;
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
        """)

    def _create_config_tab(self):
        config_widget = QWidget()
        layout = QVBoxLayout(config_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # API Configuration Group
        api_group = QGroupBox("API Configuration")
        api_layout = QVBoxLayout(api_group)

        # TheNewsAPI token
        news_api_layout = QHBoxLayout()
        news_api_layout.addWidget(QLabel("TheNewsAPI Token:"))
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
        openai_api_layout.addWidget(QLabel("OpenAI API Key:"))
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
        threshold_group = QGroupBox("Relevance Threshold")
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
        multilingual_group = QGroupBox("High-Recall Multilingual Search")
        multilingual_layout = QVBoxLayout(multilingual_group)
        self.high_recall_enabled = QCheckBox("Enable high-recall mode (balanced quality, higher volume)")
        self.high_recall_enabled.setChecked(bool(self.config_manager.get("HIGH_RECALL_MODE", False)))
        multilingual_layout.addWidget(self.high_recall_enabled)

        multilingual_layout.addWidget(QLabel("Languages (primary control):"))
        self.language_checkboxes = {}
        language_row = QHBoxLayout()
        language_row.setSpacing(8)
        selected_languages = {
            part.strip().lower()
            for part in str(self.config_manager.get("QUERY_EXPANSION_LANGUAGES", "en")).split(",")
            if part.strip()
        }
        for code, label in SUPPORTED_LANGUAGES:
            checkbox = QCheckBox(label)
            checkbox.setChecked(code in selected_languages or (not selected_languages and code == "en"))
            self.language_checkboxes[code] = checkbox
            language_row.addWidget(checkbox)
        language_row.addStretch()
        multilingual_layout.addLayout(language_row)

        self.auto_region_mapping = QCheckBox("Auto-map regions from selected languages")
        self.auto_region_mapping.setChecked(bool(self.config_manager.get("AUTO_REGION_MAPPING_ENABLED", True)))
        multilingual_layout.addWidget(self.auto_region_mapping)

        self.region_override_enabled = QCheckBox("Advanced: manually override regions")
        self.region_override_enabled.setChecked(bool(self.config_manager.get("REGION_OVERRIDE_ENABLED", False)))
        multilingual_layout.addWidget(self.region_override_enabled)

        self.region_checkboxes = {}
        region_row = QHBoxLayout()
        region_row.setSpacing(8)
        selected_regions = {
            part.strip().lower()
            for part in str(self.config_manager.get("QUERY_EXPANSION_REGIONS", "")).split(",")
            if part.strip()
        }
        for code, label in SUPPORTED_REGIONS:
            checkbox = QCheckBox(label)
            checkbox.setChecked(code in selected_regions)
            self.region_checkboxes[code] = checkbox
            region_row.addWidget(checkbox)
        region_row.addStretch()
        multilingual_layout.addLayout(region_row)
        self.region_override_enabled.toggled.connect(self._toggle_region_override_controls)
        self._toggle_region_override_controls(self.region_override_enabled.isChecked())
        layout.addWidget(multilingual_group)

        # Add ChatGPT Context Message group
        context_group = QGroupBox("ChatGPT Context Message")
        context_layout = QVBoxLayout(context_group)
        
        context_label = QLabel("Define the context and instructions for ChatGPT's article analysis:")
        context_layout.addWidget(context_label)
        
        self.context_message = QTextEdit()
        self.context_message.setPlaceholderText("Enter the system message for ChatGPT...")
        default_message = self.config_manager.get_context_message().get("content", "")
        self.context_message.setText(default_message)
        context_layout.addWidget(self.context_message)
        
        layout.addWidget(context_group)

        # Save Button
        save_btn = QPushButton("Save Configuration")
        save_btn.clicked.connect(self._save_config)
        layout.addWidget(save_btn)

        layout.addStretch()
        self.tabs.addTab(config_widget, "Configuration")

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
            config_updates = {
                "NEWS_API_KEY": self.news_api_key.text().strip(),
                "OPENAI_API_KEY": self.openai_api_key.text().strip(),
                "RELEVANCE_THRESHOLD": self.threshold_slider.value() / 100,
                "HIGH_RECALL_MODE": self.high_recall_enabled.isChecked(),
                "QUERY_EXPANSION_ENABLED": True,
                "QUERY_EXPANSION_USE_AI": True,
                "QUERY_EXPANSION_LANGUAGES": self._selected_languages_csv(),
                "REGION_OVERRIDE_ENABLED": self.region_override_enabled.isChecked(),
                "QUERY_EXPANSION_REGIONS": self._selected_regions_csv(),
                "AUTO_REGION_MAPPING_ENABLED": self.auto_region_mapping.isChecked(),
                "CHATGPT_CONTEXT_MESSAGE": {
                    "role": "system",
                    "content": self.context_message.toPlainText()
                },
            }
            config_updates.update(self.date_range_widget.get_config_values())

            # Save all at once to trigger encrypted storage
            self.config_manager.save_config(config_updates)

            if self.config_manager.validate():
                self.processor = None  # Clear old processor
                QMessageBox.information(self, "Success", "Configuration saved and validated successfully!")
                self.statusBar().showMessage("Configuration saved successfully")
            else:
                QMessageBox.warning(self, "Warning", "Configuration saved but validation failed. Check settings.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save configuration: {e}")
            logger.error(f"Config save error: {e}")

    def _create_search_terms_tab(self):
        search_widget = QWidget()
        layout = QVBoxLayout(search_widget)

        # Instructions
        title = QLabel("Manage Search Terms")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        layout.addWidget(title)

        instructions = QLabel("Add, remove, or manage search terms that will be used to find relevant news articles.")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        # Search terms list
        list_group = QGroupBox("Search Terms List")
        list_layout = QVBoxLayout(list_group)
        
        self.terms_list = QListWidget()
        list_layout.addWidget(self.terms_list)
        self._refresh_search_terms()

        # Buttons
        btn_layout = QHBoxLayout()
        add_btn = QPushButton("Add Term")
        add_btn.clicked.connect(self._add_search_term)
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_search_term)
        import_btn = QPushButton("Import from File")
        import_btn.clicked.connect(self._import_search_terms)
        export_btn = QPushButton("Export to File")
        export_btn.clicked.connect(self._export_search_terms)

        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(remove_btn)
        btn_layout.addWidget(import_btn)
        btn_layout.addWidget(export_btn)
        list_layout.addLayout(btn_layout)

        layout.addWidget(list_group)
        self.tabs.addTab(search_widget, "Search Terms")

    def _create_processing_tab(self):
        process_widget = QWidget()
        layout = QVBoxLayout(process_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Left side: Status and Controls
        left_panel = QVBoxLayout()

        # Enhanced Status group
        status_group = QGroupBox("Processing Status")
        status_layout = QVBoxLayout(status_group)

        # Overall status
        status_box = QHBoxLayout()
        self.status_icon = QLabel("OK")
        self.status_label = QLabel("Ready to process articles")
        status_box.addWidget(self.status_icon)
        status_box.addWidget(self.status_label)
        status_layout.addLayout(status_box)

        # Phase indicators
        phase_group = QGroupBox("Current Phase")
        phase_layout = QGridLayout(phase_group)
        
        # Fetch phase
        self.fetch_icon = QLabel("o")
        self.fetch_status = QLabel("Fetching: Waiting")
        self.fetch_progress = QProgressBar()
        self.fetch_progress.setMaximum(100)
        phase_layout.addWidget(self.fetch_icon, 0, 0)
        phase_layout.addWidget(self.fetch_status, 0, 1)
        phase_layout.addWidget(self.fetch_progress, 0, 2)
        
        # Clean phase
        self.clean_icon = QLabel("o")
        self.clean_status = QLabel("Cleaning: Waiting")
        self.clean_progress = QProgressBar()
        self.clean_progress.setMaximum(100)
        phase_layout.addWidget(self.clean_icon, 1, 0)
        phase_layout.addWidget(self.clean_status, 1, 1)
        phase_layout.addWidget(self.clean_progress, 1, 2)
        
        # Analyze phase
        self.analyze_icon = QLabel("o")
        self.analyze_status = QLabel("Analysis: Waiting")
        self.analyze_progress = QProgressBar()
        self.analyze_progress.setMaximum(100)
        phase_layout.addWidget(self.analyze_icon, 2, 0)
        phase_layout.addWidget(self.analyze_status, 2, 1)
        phase_layout.addWidget(self.analyze_progress, 2, 2)

        status_layout.addWidget(phase_group)

        # Overall progress
        self.progress_counter = QLabel("0/0 articles processed")
        status_layout.addWidget(self.progress_counter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        status_layout.addWidget(self.progress_bar)

        left_panel.addWidget(status_group)

        # Control buttons
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Processing")
        self.start_btn.clicked.connect(self._start_processing)
        
        self.stop_btn = QPushButton("Stop Processing")
        self.stop_btn.clicked.connect(self._stop_processing)
        self.stop_btn.setEnabled(False)
        self.clear_logs_btn = QPushButton("Clear Logs")
        self.clear_logs_btn.clicked.connect(self._clear_run_logs)

        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.addWidget(self.clear_logs_btn)
        left_panel.addLayout(btn_layout)

        # Live run logs
        logs_group = QGroupBox("Run Logs")
        logs_layout = QVBoxLayout(logs_group)
        self.run_logs_output = QTextEdit()
        self.run_logs_output.setReadOnly(True)
        self.run_logs_output.setPlaceholderText("Run logs will appear here while processing is active.")
        self.run_logs_output.setMinimumHeight(170)
        logs_layout.addWidget(self.run_logs_output)
        left_panel.addWidget(logs_group)

        # Right side: Database Preview
        right_panel = QVBoxLayout()

        # Raw Articles Preview
        raw_group = QGroupBox("Raw Articles Preview")
        raw_layout = QVBoxLayout(raw_group)
        
        # Create scroll area for raw preview
        raw_scroll = QScrollArea()
        raw_scroll.setWidgetResizable(True)
        raw_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        raw_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        raw_container = QWidget()
        raw_container_layout = QVBoxLayout(raw_container)
        
        self.raw_preview = QTreeWidget()
        self.raw_preview.setHeaderLabels(["ID", "Title", "URL"])
        self.raw_preview.setMinimumHeight(200)
        raw_container_layout.addWidget(self.raw_preview)
        
        raw_scroll.setWidget(raw_container)
        raw_layout.addWidget(raw_scroll)
        
        raw_controls = QHBoxLayout()
        # Add fetched this run counter
        raw_controls.addWidget(QLabel("Fetched this run: "))
        self.fetched_count_label = QLabel("0")
        raw_controls.addWidget(self.fetched_count_label)
        raw_controls.addSpacing(20)  # Add some spacing between counters
        raw_controls.addWidget(QLabel("Total Raw Articles: "))
        self.raw_count_label = QLabel("0")
        raw_controls.addWidget(self.raw_count_label)
        raw_controls.addStretch()
        clear_raw_btn = QPushButton("Clear Raw Articles")
        clear_raw_btn.clicked.connect(self._clear_raw_articles)
        raw_controls.addWidget(clear_raw_btn)
        raw_layout.addLayout(raw_controls)
        
        right_panel.addWidget(raw_group)

        # Relevant Articles Preview
        cleaned_group = QGroupBox("Relevant Articles Preview")
        cleaned_layout = QVBoxLayout(cleaned_group)
        
        # Create scroll area for cleaned preview
        cleaned_scroll = QScrollArea()
        cleaned_scroll.setWidgetResizable(True)
        cleaned_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        cleaned_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        cleaned_container = QWidget()
        cleaned_container_layout = QVBoxLayout(cleaned_container)
        
        self.cleaned_preview = QTreeWidget()
        self.cleaned_preview.setHeaderLabels(["ID", "Title", "Score"])
        self.cleaned_preview.setMinimumHeight(200)
        cleaned_container_layout.addWidget(self.cleaned_preview)
        
        cleaned_scroll.setWidget(cleaned_container)
        cleaned_layout.addWidget(cleaned_scroll)
        
        cleaned_controls = QHBoxLayout()
        cleaned_controls.addWidget(QLabel("Total Relevant Articles: "))
        self.cleaned_count_label = QLabel("0")
        cleaned_controls.addWidget(self.cleaned_count_label)
        cleaned_controls.addStretch()
        clear_cleaned_btn = QPushButton("Clear Relevant Articles")
        clear_cleaned_btn.clicked.connect(self._clear_cleaned_articles)
        cleaned_controls.addWidget(clear_cleaned_btn)
        cleaned_layout.addLayout(cleaned_controls)
        
        right_panel.addWidget(cleaned_group)

        # Combine panels in horizontal layout
        panels_layout = QHBoxLayout()
        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        
        panels_layout.addWidget(left_widget)
        panels_layout.addWidget(right_widget)
        layout.addLayout(panels_layout)

        self.tabs.addTab(process_widget, "Processing")
        
        # Initial preview update
        self._update_previews()

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
        results_widget = QWidget()
        layout = QVBoxLayout(results_widget)

        # Filter controls
        filter_group = QGroupBox("Filter Results")
        filter_layout = QHBoxLayout(filter_group)

        filter_layout.addWidget(QLabel("Search:"))
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search in titles...")
        self.search_box.textChanged.connect(self._filter_results)
        self.search_box.setToolTip("Enter text to filter article titles")
        filter_layout.addWidget(self.search_box)

        filter_layout.addWidget(QLabel("Min. Relevance:"))
        self.relevance_filter = QComboBox()
        self.relevance_filter.addItems(["All", "Low (>0.3)", "Medium (>0.5)", "High (>0.7)", "Very High (>0.9)"])
        self.relevance_filter.currentIndexChanged.connect(self._filter_results)
        self.relevance_filter.setToolTip("Filter articles by minimum relevance score")
        filter_layout.addWidget(self.relevance_filter)

        layout.addWidget(filter_group)

        # Results tree with context menu
        self.results_tree = QTreeWidget()
        self.results_tree.setHeaderLabels(["Title", "Relevance", "URL"])
        self.results_tree.setColumnWidth(0, 400)
        self.results_tree.setColumnWidth(1, 100)
        self.results_tree.setColumnWidth(2, 300)
        self.results_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_tree.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self.results_tree)

        # Store original results for filtering
        self.all_results = []

        # Export button
        export_btn = QPushButton("Export Results")
        export_btn.clicked.connect(self._export_results)
        layout.addWidget(export_btn)

        self.tabs.addTab(results_widget, "Results")
        self._load_results_from_database()

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

    def _selected_regions_csv(self) -> str:
        if not self.region_override_enabled.isChecked():
            return ""
        selected = [code for code, checkbox in self.region_checkboxes.items() if checkbox.isChecked()]
        return ",".join(selected)

    def _toggle_region_override_controls(self, enabled: bool):
        for checkbox in self.region_checkboxes.values():
            checkbox.setEnabled(enabled)

    def _refresh_search_terms(self):
        self.terms_list.clear()
        terms = self.search_manager.get_search_terms()
        for term in terms:
            self.terms_list.addItem(term['term'])

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
            # Validate configuration first
            missing_keys = self._missing_required_keys()
            if missing_keys:
                missing_labels = ", ".join(key.replace("_", " ").title() for key in missing_keys)
                QMessageBox.warning(
                    self,
                    "Configuration Error",
                    f"Missing required settings: {missing_labels}. Please update the Configuration tab first.",
                )
                self.tabs.setCurrentIndex(0)  # Switch to config tab
                return
            if not self.config_manager.validate():
                QMessageBox.warning(
                    self,
                    "Configuration Error",
                    "Configuration is invalid. Please review values in the Configuration tab.",
                )
                self.tabs.setCurrentIndex(0)
                return

            valid_dates, date_error = self.date_range_widget.validate_selection()
            if not valid_dates:
                QMessageBox.warning(self, "Invalid Date Range", date_error)
                self.tabs.setCurrentIndex(0)
                return
            date_params = self.date_range_widget.get_date_params()

            # Reset fetched counter when starting new run
            self._update_fetched_count(0)
            search_terms = self.search_manager.get_search_terms()
            if not search_terms:
                QMessageBox.warning(self, "Warning", "No search terms defined. Please add search terms first.")
                return

            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self._processing = True

            # Reset UI elements
            self._reset_phase_statuses()
            self.progress_bar.setValue(0)
            self.progress_counter.setText("0/0 articles processed")
            self.status_icon.setText("...")
            self.status_label.setText("Starting processing...")
            self._clear_run_logs()
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
            logger.error(f"Processing start error: {e}")
            return

    def _handle_processing_complete(self, results):
        """Finalize UI state after the worker completes.

        Args:
            results: List of processed article dicts returned by the pipeline.
        """
        result_count = len(results) if results else 0
        logger.info(f"Processing completed with {result_count} relevant results")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._processing = False
        
        if results:
            # Mark all phases as complete
            self._update_phase_status('fetch', "Complete", 100, is_complete=True)
            self._update_phase_status('clean', "Complete", 100, is_complete=True)
            self._update_phase_status('analyze', "Complete", 100, is_complete=True)
            
            # Update results tab and UI
            self._update_results(results)
            self._update_previews()
            
            # Results already contain only relevant articles
            relevant_count = len(results)

            QMessageBox.information(
                self,
                "Success",
                f"Processed {relevant_count} relevant articles successfully."
            )
            logger.info(
                f"Successfully processed {relevant_count} relevant articles."
            )
        else:
            self._reset_phase_statuses()
            QMessageBox.warning(self, "Warning", "No articles were processed")
            logger.warning("No articles were processed")
            self._update_previews()
        self._detach_run_log_handler()

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
        self._detach_run_log_handler()

    def _update_progress(self, current, total):
        if total > 0:
            percentage = round((current / total) * 100)  # Round to nearest integer
            self.progress_bar.setValue(int(percentage))  # Explicitly convert to int
            self.progress_counter.setText(f"{current}/{total} articles processed")

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
        self.state.update_from_status(status)
        self._render_status(status)

    def _render_status(self, status: StatusUpdate):
        """Render parsed status into the UI (icons, labels, progress)."""
        logger.info(f"Status update: {status.message}")
        self.status_label.setText(status.message)
        self.statusBar().showMessage(status.message)

        if status.counts.fetched is not None:
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
        """Update icons, labels, and progress bars for a processing phase.

        Args:
            phase: Phase identifier ('fetch', 'clean', or 'analyze').
            status: Human-readable status to display.
            progress: Integer percentage to set on the phase progress bar.
            is_error: Whether the phase ended with an error.
            is_complete: Whether the phase finished successfully.
        """
        icon_map = {
            'fetch': self.fetch_icon,
            'clean': self.clean_icon,
            'analyze': self.analyze_icon
        }
        status_map = {
            'fetch': self.fetch_status,
            'clean': self.clean_status,
            'analyze': self.analyze_status
        }
        progress_map = {
            'fetch': self.fetch_progress,
            'clean': self.clean_progress,
            'analyze': self.analyze_progress
        }

        if phase in icon_map:
            # Update icon
            if is_error:
                icon_map[phase].setText("X")
            elif is_complete:
                icon_map[phase].setText("V")
            else:
                icon_map[phase].setText("...")

            # Update status text and progress
            if phase == 'fetch' and not is_complete and not is_error:
                # Only try to split if status contains the expected format
                if '/' in status:
                    try:
                        current, total = status.split('/')
                        status_map[phase].setText(f"Fetching: {current}/{total} terms processed")
                    except ValueError:
                        status_map[phase].setText(f"Fetching: {status}")
                else:
                    status_map[phase].setText(f"Fetching: {status}")
            else:
                status_map[phase].setText(f"{phase.title()}: {status}")

            # Update progress
            if progress >= 0:
                progress_map[phase].setValue(int(progress))

    def _reset_phase_statuses(self):
        """Reset all phase indicators to waiting state"""
        phases = ['fetch', 'clean', 'analyze']
        for phase in phases:
            self._update_phase_status(phase, "Waiting", 0)
            icon_map = {
                'fetch': self.fetch_icon,
                'clean': self.clean_icon,
                'analyze': self.analyze_icon
            }
            icon_map[phase].setText("o")

    def _update_raw_count(self):
        """Update the raw articles count from database"""
        raw_count = len(self.db_manager.execute_query("SELECT id FROM raw_articles"))
        self.raw_count_label.setText(str(raw_count))

    def _update_fetched_count(self, count: int):
        """Update the fetched this run counter"""
        self.fetched_count_label.setText(str(count))

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
        if hasattr(self, "run_logs_output") and self.run_logs_output is not None:
            self.run_logs_output.clear()

    def _append_run_log_line(self, message: str):
        """Append one log line and cap retained lines for UI responsiveness."""
        if not message or not hasattr(self, "run_logs_output") or self.run_logs_output is None:
            return
        self.run_logs_output.append(message)
        doc = self.run_logs_output.document()
        overflow = doc.blockCount() - self.run_log_max_lines
        if overflow <= 0:
            return

        cursor = self.run_logs_output.textCursor()
        cursor.movePosition(cursor.MoveOperation.Start)
        for _ in range(overflow):
            cursor.select(cursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()

    def _show_context_menu(self, position):
        item = self.results_tree.itemAt(position)
        if (item):
            menu = QMenu()
            copy_action = QAction("Copy URL", self)
            copy_action.triggered.connect(lambda: self._copy_url(item))
            menu.addAction(copy_action)
            
            open_action = QAction("Open in Browser", self)
            open_action.triggered.connect(lambda: self._open_url(item))
            menu.addAction(open_action)
            
            menu.exec(self.results_tree.viewport().mapToGlobal(position))

    def _copy_url(self, item):
        url = item.text(2)  # URL is in the third column
        QApplication.clipboard().setText(url)
        self.statusBar().showMessage("URL copied to clipboard", 3000)

    def _open_url(self, item):
        import webbrowser
        url = item.text(2)
        webbrowser.open(url)

    def _add_result_item(self, result):
        """Add a single result item to the results tree"""
        try:
            item = QTreeWidgetItem([
                result.get('title', 'No title'),
                f"{result.get('relevance_score', 0):.2f}",
                result.get('url', 'No URL')
            ])
            self.results_tree.addTopLevelItem(item)
        except Exception as e:
            logger.error(f"Error adding result to tree: {e}")
            
    def _filter_results(self):
        search_text = self.search_box.text().lower()
        relevance_idx = self.relevance_filter.currentIndex()
        min_relevance = {
            0: 0.0,    # All
            1: 0.3,    # Low
            2: 0.5,    # Medium
            3: 0.7,    # High
            4: 0.9     # Very High
        }.get(relevance_idx, 0.0)

        self.results_tree.clear()
        for result in self.all_results:
            title = result.get('title', '').lower()
            relevance = result.get('relevance_score', 0)
            
            if (search_text in title and relevance >= min_relevance):
                self._add_result_item(result)

    def _export_results(self):
        """Export the current results to a file"""
        if not self.all_results:
            QMessageBox.warning(self, "Warning", "No results to export")
            return

        # Get the current relevance filter setting
        relevance_idx = self.relevance_filter.currentIndex()
        min_relevance = {
            0: 0.0,    # All
            1: 0.3,    # Low
            2: 0.5,    # Medium
            3: 0.7,    # High
            4: 0.9     # Very High
        }.get(relevance_idx, 0.0)
        
        # Get the current search filter
        search_text = self.search_box.text().lower()
        
        # Filter results based on current criteria
        filtered_results = [
            result for result in self.all_results
            if (search_text in result.get('title', '').lower() and 
                result.get('relevance_score', 0) >= min_relevance)
        ]
        
        if not filtered_results:
            QMessageBox.warning(self, "Warning", "No results match your current filter criteria")
            return

        file_path, file_type = QFileDialog.getSaveFileName(
            self,
            "Export Results",
            str(Path.home() / "Desktop"),
            "CSV Files (*.csv);;JSON Files (*.json);;Text Files (*.txt);;All Files (*)"
        )
        
        if not file_path:
            return

        try:
            # Write results based on file type
            if file_path.endswith('.csv'):
                self._export_to_csv(file_path, filtered_results)
            elif file_path.endswith('.json'):
                self._export_to_json(file_path, filtered_results)
            else:
                self._export_to_txt(file_path, filtered_results)
                
            QMessageBox.information(self, "Success", f"Results exported to {file_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export results: {str(e)}")

    def _export_to_csv(self, file_path, results):
        """Export results to CSV format"""
        import csv
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(
                f,
                fieldnames=['title', 'relevance_score', 'url', 'event | location | actor']
            )
            writer.writeheader()
            for result in results:
                writer.writerow({
                    'title': result.get('title', ''),
                    'relevance_score': f"{result.get('relevance_score', 0):.2f}",
                    'url': result.get('url', ''),
                    'event | location | actor': self._build_export_summary(result),
                })

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
        """Export results to JSON format"""
        import json
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

    def _export_to_txt(self, file_path, results):
        """Export results to plain text format"""
        with open(file_path, 'w', encoding='utf-8') as f:
            for result in results:
                f.write(f"Title: {result.get('title', '')}\n")
                f.write(f"Relevance: {result.get('relevance_score', 0):.2f}\n")
                f.write(f"URL: {result.get('url', '')}\n")
                f.write(f"Summary: {self._build_export_summary(result)}\n")
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

        self.results_tree.clear()
        for result in valid_results:
            self._add_result_item(result)

        self.statusBar().showMessage(f"Loaded {len(valid_results)} results")

    def _load_results_from_database(self):
        """Load persisted relevant articles into the Results tab on app startup."""
        try:
            rows = self.db_manager.execute_query(
                """
                SELECT
                    title,
                    relevance_score,
                    url,
                    content,
                    explanation,
                    event,
                    who_entities,
                    where_location,
                    impact,
                    urgency,
                    why_it_matters,
                    incident_sentence
                FROM relevant_articles
                ORDER BY id DESC
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
