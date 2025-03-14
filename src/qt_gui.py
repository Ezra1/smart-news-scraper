from PyQt6.QtWidgets import (
    QMainWindow, QApplication, QWidget, QPushButton, QLabel, QVBoxLayout,
    QHBoxLayout, QTabWidget, QLineEdit, QFrame, QListWidget, QProgressBar,
    QScrollArea, QTreeWidget, QTreeWidgetItem, QMessageBox, QFileDialog,
    QComboBox, QSlider, QInputDialog, QGroupBox, QMenu
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QAction
from pathlib import Path
import asyncio
import sys
from queue import Queue

from src.logger_config import setup_logging
from src.config import ConfigManager
from src.database_manager import DatabaseManager, ArticleManager, SearchTermManager
from src.news_scraper import NewsArticleScraper
from src.openai_relevance_processing import ArticleProcessor
from src.article_validator import ArticleValidator

logger = setup_logging(__name__)

class ProcessingWorker(QThread):
    progress_updated = pyqtSignal(int, int)
    status_updated = pyqtSignal(str, bool, bool, bool)
    completed = pyqtSignal(list)

    def __init__(self, scraper, processor, validator, search_terms, db_manager=None):
        super().__init__()
        self.scraper = scraper
        self.processor = processor
        self.validator = validator
        self.search_terms = search_terms
        self.db_manager = db_manager
        self._is_running = True

    def run(self):
        asyncio.run(self._process_articles())

    def stop(self):
        self._is_running = False

    async def _process_articles(self):
        try:
            articles = []
            if self.scraper:
                # Try to fetch new articles
                articles = await self.scraper.fetch_all_articles(self.search_terms)
                if self.scraper.rate_limited:
                    self.status_updated.emit("Rate limit reached. Using existing articles...", False, True, False)
                
                # Get existing articles from database if no new ones fetched
                if not articles:
                    articles = self.db_manager.execute_query("SELECT * FROM raw_articles")
                    if articles:
                        self.status_updated.emit(f"Processing {len(articles)} existing articles from database", False, False, True)
            elif self.validator:
                articles = self.search_terms  # In this case search_terms contains articles to clean
            else:
                articles = self.search_terms  # For analysis only

            # Get article counts
            raw_count = len(self.db_manager.execute_query("SELECT id FROM raw_articles"))
            clean_count = len(self.db_manager.execute_query("SELECT id FROM cleaned_articles"))
            counts_msg = f"Database contains: {raw_count} raw articles, {clean_count} cleaned articles"

            if not articles:
                self.status_updated.emit(f"No articles to process. {counts_msg}", False, True, False)
                return

            # Process articles
            total = len(articles)
            processed = 0
            cleaned_articles = []

            for article in articles:
                if not self._is_running:
                    break

                if self.validator:
                    clean_article = self.validator.clean_article(article)
                    if clean_article:
                        cleaned_articles.append(clean_article)
                        processed += 1
                        self.progress_updated.emit(processed, total)
                else:
                    cleaned_articles = articles
                    processed += 1
                    self.progress_updated.emit(processed, total)

            if cleaned_articles and self._is_running:
                if self.processor:
                    self.status_updated.emit("Starting OpenAI analysis...", False, False, False)
                    processed = 0
                    relevant_articles = []
                    
                    for article in cleaned_articles:
                        if not self._is_running:
                            break
                            
                        result = await self.processor.process_article(article, len(cleaned_articles) - processed)
                        processed += 1
                        self.progress_updated.emit(processed, len(cleaned_articles))
                        
                        if result:
                            relevant_articles.append(result)
                            
                    self.completed.emit(relevant_articles)
                    self.status_updated.emit(f"Analysis completed. Found {len(relevant_articles)} relevant articles. {counts_msg}", False, False, True)
                else:
                    self.completed.emit(cleaned_articles)
                    self.status_updated.emit(f"Processing completed. {counts_msg}", False, False, True)
            else:
                self.status_updated.emit(f"No valid articles to process. {counts_msg}", False, True, False)

        except Exception as e:
            logger.error(f"Processing error: {e}")
            self.status_updated.emit(f"Error: {str(e)}", True, False, False)

class NewsScraperGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart News Scraper")
        self.setMinimumSize(1200, 800)

        # Initialize components
        self.validator = ArticleValidator()
        self.config_manager = ConfigManager()
        self.db_manager = DatabaseManager(self.config_manager.get("DATABASE_PATH"))
        self.search_manager = SearchTermManager(self.db_manager)
        self.article_manager = ArticleManager(self.db_manager)
        self.processor = ArticleProcessor(self.db_manager)
        self.processing_queue = Queue()
        self._processing = False
        self.worker = None

        # Setup UI
        self._setup_ui()
        self._setup_styles()

    def _setup_ui(self):
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
        # Update spacing and layout
        config_widget = QWidget()
        layout = QVBoxLayout(config_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # API Configuration Group
        api_group = QGroupBox("API Configuration")
        api_layout = QVBoxLayout(api_group)

        # News API
        news_api_layout = QHBoxLayout()
        news_api_layout.addWidget(QLabel("News API Key:"))
        self.news_api_key = QLineEdit()
        self.news_api_key.setText(self.config_manager.get("NEWS_API_KEY", ""))
        self.news_api_key.setEchoMode(QLineEdit.EchoMode.Password)
        news_api_layout.addWidget(self.news_api_key)
        toggle_news = QPushButton("👁️")
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
        toggle_openai = QPushButton("👁️")
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

        # Save Button
        save_btn = QPushButton("Save Configuration")
        save_btn.clicked.connect(self._save_config)
        layout.addWidget(save_btn)

        layout.addStretch()
        self.tabs.addTab(config_widget, "Configuration")

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
        add_btn = QPushButton("➕ Add Term")
        add_btn.clicked.connect(self._add_search_term)
        remove_btn = QPushButton("➖ Remove Selected")
        remove_btn.clicked.connect(self._remove_search_term)
        import_btn = QPushButton("📥 Import from File")
        import_btn.clicked.connect(self._import_search_terms)
        export_btn = QPushButton("📤 Export to File")
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

        # Status group
        status_group = QGroupBox("Processing Status")
        status_layout = QVBoxLayout(status_group)

        status_box = QHBoxLayout()
        self.status_icon = QLabel("🟢")
        self.status_label = QLabel("Ready to process articles")
        status_box.addWidget(self.status_icon)
        status_box.addWidget(self.status_label)
        status_layout.addLayout(status_box)

        # Progress
        self.progress_counter = QLabel("0/0 articles processed")
        status_layout.addWidget(self.progress_counter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        status_layout.addWidget(self.progress_bar)

        layout.addWidget(status_group)

        # Control buttons
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶️ Start Processing")
        self.start_btn.clicked.connect(self._start_processing)
        
        self.stop_btn = QPushButton("⏹️ Stop Processing")
        self.stop_btn.clicked.connect(self._stop_processing)
        self.stop_btn.setEnabled(False)

        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)

        # Step controls
        steps_group = QGroupBox("Processing Steps")
        steps_layout = QHBoxLayout(steps_group)

        fetch_btn = QPushButton("1. Fetch Articles")
        fetch_btn.clicked.connect(self._start_fetch_only)
        clean_btn = QPushButton("2. Clean Articles")
        clean_btn.clicked.connect(self._start_cleaning_only)
        analyze_btn = QPushButton("3. Analyze Relevance")
        analyze_btn.clicked.connect(self._start_analysis_only)

        steps_layout.addWidget(fetch_btn)
        steps_layout.addWidget(clean_btn)
        steps_layout.addWidget(analyze_btn)

        layout.addWidget(steps_group)
        self.tabs.addTab(process_widget, "Processing")

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
        export_btn = QPushButton("📤 Export Results")
        export_btn.clicked.connect(self._export_results)
        layout.addWidget(export_btn)

        self.tabs.addTab(results_widget, "Results")

    def _toggle_password_visibility(self, line_edit):
        if line_edit.echoMode() == QLineEdit.EchoMode.Password:
            line_edit.setEchoMode(QLineEdit.EchoMode.Normal)
        else:
            line_edit.setEchoMode(QLineEdit.EchoMode.Password)

    def _update_threshold_label(self):
        self.threshold_label.setText(f"{self.threshold_slider.value() / 100:.2f}")

    def _save_config(self):
        try:
            self.config_manager.set("NEWS_API_KEY", self.news_api_key.text())
            self.config_manager.set("OPENAI_API_KEY", self.openai_api_key.text())
            self.config_manager.set("RELEVANCE_THRESHOLD", self.threshold_slider.value() / 100)

            if self.config_manager.validate():
                QMessageBox.information(self, "Success", "Configuration saved successfully!")
                self.statusBar().showMessage("Configuration saved successfully")
            else:
                QMessageBox.warning(self, "Warning", "Configuration saved but validation failed. Check API keys.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save configuration: {e}")

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
        current = self.terms_list.currentItem()
        if current:
            self.search_manager.delete_search_term(current.text())
            self._refresh_search_terms()

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
        if not self.search_manager.get_search_terms():
            QMessageBox.warning(self, "Warning", "No search terms defined. Please add search terms first.")
            return

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._processing = True

        scraper = NewsArticleScraper(self.config_manager)
        scraper.db_manager = self.db_manager
        self.worker = ProcessingWorker(
            scraper=scraper,
            processor=self.processor,
            validator=self.validator,
            search_terms=self.search_manager.get_search_terms(),
            db_manager=self.db_manager
        )
        
        self.worker.progress_updated.connect(self._update_progress)
        self.worker.status_updated.connect(self._update_status)
        self.worker.completed.connect(self._update_results)
        
        self.worker.start()

    def _stop_processing(self):
        if self.worker:
            self.worker.stop()
        self._processing = False
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_icon.setText("⏹️")
        self.status_label.setText("Processing stopped by user")

    def _update_progress(self, current, total):
        if total > 0:
            percentage = round((current / total) * 100)  # Round to nearest integer
            self.progress_bar.setValue(int(percentage))  # Explicitly convert to int
            self.progress_counter.setText(f"{current}/{total} articles processed")

    def _update_status(self, message, is_error, is_warning, is_success):
        self.status_label.setText(message)
        self.statusBar().showMessage(message)
        
        if is_error:
            self.status_icon.setText("❌")
        elif is_warning:
            self.status_icon.setText("⚠️")
        elif is_success:
            self.status_icon.setText("✅")
        else:
            self.status_icon.setText("🔄")

    def _update_results(self, results):
        self.all_results = results  # Store for filtering
        self.results_tree.clear()
        for result in results:
            self._add_result_item(result)

    def _add_result_item(self, result):
        item = QTreeWidgetItem([
            result.get('title', ''),
            f"{float(result.get('relevance_score', 0)):.2f}",
            result.get('url', '')
        ])
        
        relevance = result.get('relevance_score', 0)
        if relevance >= 0.7:
            item.setBackground(0, Qt.GlobalColor.green)
        elif relevance >= 0.4:
            item.setBackground(0, Qt.GlobalColor.yellow)
        else:
            item.setBackground(0, Qt.GlobalColor.red)
            
        self.results_tree.addTopLevelItem(item)

    def _export_results(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Results As",
            str(Path.home() / "Desktop"),
            "Text Files (*.txt);;CSV Files (*.csv);;All Files (*)"
        )
        
        if file_path:
            try:
                from src.extract_cleaned_articles import extract_cleaned_data
                extract_cleaned_data(self.db_manager.db_path, file_path)
                QMessageBox.information(self, "Success", f"Results exported to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export results: {e}")

    def _start_fetch_only(self):
        if not self.search_manager.get_search_terms():
            QMessageBox.warning(self, "Warning", "No search terms defined. Please add search terms first.")
            return

        self.start_btn.setEnabled(False)
        scraper = NewsArticleScraper(self.config_manager)
        self.worker = ProcessingWorker(scraper, None, None, self.search_manager.get_search_terms(), db_manager=self.db_manager)
        
        self.worker.progress_updated.connect(self._update_progress)
        self.worker.status_updated.connect(self._update_status)
        self.worker.completed.connect(lambda x: self._process_fetch_results(x))
        
        self.worker.start()

    def _start_cleaning_only(self):
        articles = self.article_manager.get_articles()
        if not articles:
            QMessageBox.warning(self, "Warning", "No articles found to clean")
            return

        self.start_btn.setEnabled(False)
        self.worker = ProcessingWorker(None, None, self.validator, articles, db_manager=self.db_manager)
        
        self.worker.progress_updated.connect(self._update_progress)
        self.worker.status_updated.connect(self._update_status)
        self.worker.completed.connect(lambda x: self._process_clean_results(x))
        
        self.worker.start()

    def _start_analysis_only(self):
        articles = self.article_manager.get_articles()
        if not articles:
            QMessageBox.warning(self, "Warning", "No articles found to analyze")
            return

        self.start_btn.setEnabled(False)
        self.worker = ProcessingWorker(None, self.processor, None, articles, db_manager=self.db_manager)
        
        self.worker.progress_updated.connect(self._update_progress)
        self.worker.status_updated.connect(self._update_status)
        self.worker.completed.connect(self._update_results)
        
        self.worker.start()

    def _process_fetch_results(self, articles):
        self.start_btn.setEnabled(True)
        raw_count = len(self.db_manager.execute_query("SELECT id FROM raw_articles"))
        clean_count = len(self.db_manager.execute_query("SELECT id FROM cleaned_articles"))
        counts_msg = f"Database contains: {raw_count} raw articles, {clean_count} cleaned articles"
        
        if articles:
            QMessageBox.information(self, "Success", f"Fetched {len(articles)} new articles\n{counts_msg}")
            for article in articles:
                self.article_manager.insert_article(article, article['search_term_id'])
        else:
            QMessageBox.warning(self, "Info", f"No new articles fetched\n{counts_msg}")

    def _process_clean_results(self, articles):
        self.start_btn.setEnabled(True)
        if articles:
            QMessageBox.information(self, "Success", f"Cleaned {len(articles)} articles successfully")
            for article in articles:
                self.article_manager.update_article(article)
        else:
            QMessageBox.warning(self, "Warning", "No articles were cleaned")

    def _show_context_menu(self, position):
        item = self.results_tree.itemAt(position)
        if item:
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

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
        event.accept()
