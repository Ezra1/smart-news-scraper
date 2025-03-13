import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
import asyncio
import threading
from typing import Optional
from queue import Queue
import ttkthemes

from src.logger_config import setup_logging
from src.config import ConfigManager
from src.database_manager import DatabaseManager, ArticleManager, SearchTermManager
from src.news_scraper import NewsArticleScraper
from src.openai_relevance_processing import ArticleProcessor
from src.article_validator import ArticleValidator

logger = setup_logging(__name__)

class NewsScraperGUI:
    def __init__(self):
        # Use themed tk window
        self.root = ttkthemes.ThemedTk()
        self.root.set_theme("arc")  # Modern dark theme
        self.root.title("Smart News Scraper")
        self.root.geometry("1200x1000")  # Slightly larger for better white space
        
        # Define color scheme
        self.colors = {
            'primary': '#646F4B',      # Reseda Green
            'secondary': '#46351D',    # Cafe Noir
            'accent': '#e74c3c',       # Red
            'bg_dark': '#2c3e50',      # Dark blue/gray
            'bg_light': '#7BB2D9',     # Light blue
            'text_dark': '#2c3e50',    # Dark blue/gray
            'text_light': '#BFD2BF',   # Light gray
            'disabled_text': '#95a5a6',  # Light gray
        }
        
        # Configure styles with modern color scheme
        self.style = ttk.Style()
        
        # Title style
        self.style.configure("Title.TLabel", 
            font=("Segoe UI", 18, "bold"),
            foreground=self.colors['primary'],
            padding=15,
            background=self.colors['bg_dark']
        )
        
        # Status style
        self.style.configure("Status.TLabel",
            font=("Segoe UI", 10),
            padding=5
        )
        
        # Action button style
        self.style.configure("Action.TButton",
            font=("Segoe UI", 10, "bold"),
            padding=8
        )
        
        # Primary button style
        self.style.configure("Primary.TButton",
            background=self.colors['bg_dark'],
            foreground=self.colors['text_dark']
        )
        
        # Secondary button style
        self.style.configure("Secondary.TButton",
            background=self.colors['secondary']
        )
        
        # Danger button style
        self.style.configure("Danger.TButton",
            background=self.colors['accent']
        )
        
        # Frame styles
        self.style.configure("Card.TFrame", 
            padding=15,
            relief="flat",
            borderwidth=0
        )
        
        # Tab style
        self.style.configure("TNotebook.Tab", 
            padding=[15, 5],
            font=("Segoe UI", 10)
        )
        
        # Configure button styles properly
        self.style.configure("Primary.TButton",
            padding=(10, 5),
            font=("Segoe UI", 10, "bold")
        )
        """
                # Define color scheme
        self.colors = {
            'primary': '#646F4B',      # Reseda Green
            'secondary': '#46351D',    # Cafe Noir
            'accent': '#e74c3c',       # Red
            'bg_dark': '#2c3e50',      # Dark blue/gray
            'bg_light': '#7BB2D9',     # Light blue
            'text_dark': '#2c3e50',    # Dark blue/gray
            'text_light': '#BFD2BF',   # Light gray
            'disabled_text': '#95a5a6'  # Light gray
        }
        """
        self.style.map("Primary.TButton",
            foreground=[('active', self.colors['text_light']), ('!disabled', self.colors['text_light']), ('disabled', self.colors['disabled_text'])],
            background=[('active', self.colors['bg_dark']), ('!disabled', '#3498db'), ('disabled', '#bdc3c7')]
        )
        
        self.style.configure("Secondary.TButton",
            padding=(10, 5),
            font=("Segoe UI", 10)
        )
        self.style.map("Secondary.TButton",
            foreground=[('active', '#ffffff'), ('!disabled', '#ffffff'), ('disabled', '#95a5a6')],
            background=[('active', '#27ae60'), ('!disabled', '#2ecc71'), ('disabled', '#bdc3c7')]
        )
        
        self.style.configure("Danger.TButton",
            padding=(10, 5),
            font=("Segoe UI", 10)
        )
        self.style.map("Danger.TButton",
            foreground=[('active', '#ffffff'), ('!disabled', '#ffffff'), ('disabled', '#95a5a6')],
            background=[('active', '#c0392b'), ('!disabled', '#e74c3c'), ('disabled', '#bdc3c7')]
        )
        
        # Regular button style
        self.style.configure("TButton",
            padding=(10, 5),
            font=("Segoe UI", 10)
        )
        self.style.map("TButton",
            foreground=[('active', '#2c3e50'), ('!disabled', '#2c3e50'), ('disabled', '#95a5a6')],
            background=[('active', '#dfe6e9'), ('!disabled', '#f8f9fa'), ('disabled', '#ecf0f1')]
        )
        
        # Add better padding and organization
        main_frame = ttk.Frame(self.root, padding="20", style="Card.TFrame")
        main_frame.pack(fill='both', expand=True)

        # Create title with subtle animation effect
        title_frame = ttk.Frame(main_frame)
        title_frame.pack(fill='x', pady=(0, 20))
        
        self.title = ttk.Label(
            title_frame, 
            text="Smart News Scraper",
            style="Title.TLabel"
        )
        self.title.pack(pady=10)
        
        # Add a subtle separator below title for better visual hierarchy
        separator = ttk.Separator(main_frame, orient='horizontal')
        separator.pack(fill='x', pady=(0, 20))
        
        # Add article validator
        self.validator = ArticleValidator()
        
        # Initialize managers using config
        self.config_manager = ConfigManager()
        self.db_manager = DatabaseManager(self.config_manager.get("DATABASE_PATH"))
        self.search_manager = SearchTermManager(self.db_manager)
        self.article_manager = ArticleManager(self.db_manager)
        self.processor = ArticleProcessor(self.db_manager)
        
        # Create processing queue
        self.processing_queue = Queue()
        
        # Thread control flag
        self._processing = False
        
        self._create_notebook()
        self._create_config_tab()
        self._create_search_terms_tab()
        self._create_processing_tab()
        self._create_results_tab()
        
        # Add status bar at bottom for better feedback
        self.status_bar = ttk.Label(
            self.root, 
            text="Ready", 
            relief=tk.SUNKEN, 
            anchor=tk.W,
            padding=(10, 5)
        )
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    def _create_notebook(self):
        """Create main notebook with tabs"""
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill='both', padx=20, pady=10)
        
        # Add callback for tab changes to update status bar
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _on_tab_changed(self, event):
        """Update status bar when tab changes"""
        tab_id = self.notebook.select()
        tab_name = self.notebook.tab(tab_id, "text")
        self.status_bar.config(text=f"Current view: {tab_name}")

    def _create_config_tab(self):
        """Create configuration tab with better layout"""
        config_frame = ttk.Frame(self.notebook, padding="20", style="Card.TFrame")
        self.notebook.add(config_frame, text='Configuration')
        
        # Add heading for better visual hierarchy
        ttk.Label(
            config_frame, 
            text="API Configuration", 
            font=("Segoe UI", 14, "bold"),
            foreground=self.colors['primary']
        ).grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 15))

        # News API Key with view toggle - improved layout
        api_key_frame = ttk.LabelFrame(config_frame, text="News API Settings", padding=15)
        api_key_frame.grid(row=1, column=0, columnspan=2, padx=5, pady=10, sticky='ew')
        
        ttk.Label(api_key_frame, text="API Key:", font=("Segoe UI", 10)).grid(row=0, column=0, padx=5, pady=5, sticky='w')
        
        key_frame = ttk.Frame(api_key_frame)
        key_frame.grid(row=0, column=1, padx=5, pady=5, sticky='ew')
        
        self.news_api_key = ttk.Entry(key_frame, show="*", width=40)
        self.news_api_key.insert(0, self.config_manager.get("NEWS_API_KEY", ""))
        self.news_api_key.pack(side='left', fill='x', expand=True)
        
        view_btn = ttk.Button(key_frame, text="👁️", width=3, 
                   command=lambda: self._toggle_view(self.news_api_key))
        view_btn.pack(side='left', padx=(5, 0))
        
        # Create tooltip for the view button
        self._create_tooltip(view_btn, "Toggle visibility")

        # OpenAI API Key with view toggle - matching layout
        openai_key_frame = ttk.LabelFrame(config_frame, text="OpenAI API Settings", padding=15)
        openai_key_frame.grid(row=2, column=0, columnspan=2, padx=5, pady=10, sticky='ew')
        
        ttk.Label(openai_key_frame, text="API Key:", font=("Segoe UI", 10)).grid(row=0, column=0, padx=5, pady=5, sticky='w')
        
        openai_key_input = ttk.Frame(openai_key_frame)
        openai_key_input.grid(row=0, column=1, padx=5, pady=5, sticky='ew')
        
        self.openai_api_key = ttk.Entry(openai_key_input, show="*", width=40)
        self.openai_api_key.insert(0, self.config_manager.get("OPENAI_API_KEY", ""))
        self.openai_api_key.pack(side='left', fill='x', expand=True)
        
        view_openai_btn = ttk.Button(openai_key_input, text="👁️", width=3,
                   command=lambda: self._toggle_view(self.openai_api_key))
        view_openai_btn.pack(side='left', padx=(5, 0))
        self._create_tooltip(view_openai_btn, "Toggle visibility")

        # Relevance Threshold with better visual design
        threshold_frame = ttk.LabelFrame(config_frame, text="Processing Settings", padding=15)
        threshold_frame.grid(row=3, column=0, columnspan=2, padx=5, pady=10, sticky='ew')
        
        ttk.Label(
            threshold_frame, 
            text="Relevance Threshold:", 
            font=("Segoe UI", 10)
        ).grid(row=0, column=0, padx=5, pady=5, sticky='w')
        
        scale_frame = ttk.Frame(threshold_frame)
        scale_frame.grid(row=0, column=1, padx=5, pady=5, sticky='ew')
        
        self.relevance_threshold = ttk.Scale(
            scale_frame, 
            from_=0.0, 
            to=1.0, 
            orient='horizontal'
        )
        self.relevance_threshold.set(self.config_manager.get("RELEVANCE_THRESHOLD", 0.7))
        self.relevance_threshold.pack(side='left', fill='x', expand=True)
        
        # Add value label that updates
        self.threshold_value = tk.StringVar(value=f"{self.relevance_threshold.get():.2f}")
        threshold_label = ttk.Label(scale_frame, textvariable=self.threshold_value, width=5)
        threshold_label.pack(side='left', padx=(5, 0))
        
        # Update label when slider moves
        self.relevance_threshold.configure(command=self._update_threshold_label)

        # Save Button - bigger and more prominent
        save_frame = ttk.Frame(config_frame)
        save_frame.grid(row=4, column=0, columnspan=2, pady=25, sticky='e')
        
        ttk.Button(
            save_frame, 
            text="Save Configuration", 
            style="Primary.TButton",
            command=self._save_config,
            padding=(15, 10)
        ).pack(side='right')

    def _toggle_view(self, entry_widget):
        """Toggle between showing and hiding entry text with visual feedback"""
        current_show = entry_widget.cget('show')
        entry_widget.configure(show='' if current_show else '*')
        
        # Update status bar for feedback
        if current_show:
            self.status_bar.config(text="Key visible - remember to hide when finished")
        else:
            self.status_bar.config(text="Key hidden")

    def _update_threshold_label(self, value):
        """Update the threshold value label"""
        self.threshold_value.set(f"{float(value):.2f}")

    def _create_search_terms_tab(self):
        """Create search terms management tab with better layout"""
        search_frame = ttk.Frame(self.notebook, padding="20")
        self.notebook.add(search_frame, text='Search Terms')

        # Add heading for better hierarchy
        ttk.Label(
            search_frame, 
            text="Manage Search Terms", 
            font=("Segoe UI", 14, "bold"),
            foreground=self.colors['primary']
        ).pack(anchor='w', pady=(0, 15))
        
        # Instructions for better usability
        ttk.Label(
            search_frame,
            text="Add, remove, or manage search terms that will be used to find relevant news articles.",
            wraplength=600
        ).pack(anchor='w', pady=(0, 15))

        # Search terms frame with border
        terms_frame = ttk.LabelFrame(search_frame, text="Search Terms List", padding=15)
        terms_frame.pack(fill='both', expand=True, padx=5, pady=5)
        
        # Add a scrollbar to the list
        list_frame = ttk.Frame(terms_frame)
        list_frame.pack(fill='both', expand=True)
        
        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side='right', fill='y')
        
        # Improved list with custom font and more height
        self.terms_list = tk.Listbox(
            list_frame, 
            height=15,
            font=("Segoe UI", 11),
            activestyle='dotbox',
            yscrollcommand=scrollbar.set
        )
        self.terms_list.pack(fill='both', expand=True, side='left')
        scrollbar.config(command=self.terms_list.yview)

        # Buttons frame with more spacing
        btn_frame = ttk.Frame(search_frame)
        btn_frame.pack(fill='x', padx=5, pady=15)

        ttk.Button(
            btn_frame, 
            text="➕ Add Term", 
            style="Primary.TButton",
            command=self._add_search_term,
            padding=(10, 5)
        ).pack(side='left', padx=5)
        
        ttk.Button(
            btn_frame, 
            text="➖ Remove Selected",
            style="Danger.TButton", 
            command=self._remove_search_term,
            padding=(10, 5)
        ).pack(side='left', padx=5)
        
        ttk.Button(
            btn_frame, 
            text="📥 Import from File", 
            command=self._import_search_terms,
            padding=(10, 5)
        ).pack(side='left', padx=5)
        
        ttk.Button(
            btn_frame, 
            text="📤 Export to File", 
            command=self._export_search_terms,
            padding=(10, 5)
        ).pack(side='left', padx=5)

        self._refresh_search_terms()

    def _create_processing_tab(self):
        """Create processing control tab with enhanced visuals"""
        process_frame = ttk.Frame(self.notebook, padding="20")
        self.notebook.add(process_frame, text='Processing')
        
        # Add heading
        ttk.Label(
            process_frame, 
            text="Article Processing", 
            font=("Segoe UI", 14, "bold"),
            foreground=self.colors['primary']
        ).pack(anchor='w', pady=(0, 15))

        # Status and counter frame with better visual hierarchy
        status_frame = ttk.LabelFrame(process_frame, text="Processing Status", padding="15")
        status_frame.pack(fill='x', padx=5, pady=10)

        # Status with icon
        status_box = ttk.Frame(status_frame)
        status_box.pack(fill='x', pady=5)
        
        self.status_icon = ttk.Label(status_box, text="🟢")
        self.status_icon.pack(side='left', padx=(0, 10))
        
        self.status_var = tk.StringVar(value="Ready to process articles")
        ttk.Label(
            status_box, 
            textvariable=self.status_var,
            font=("Segoe UI", 11, "bold"),
            foreground=self.colors['primary']
        ).pack(side='left', pady=5)

        # Progress counter with better layout
        counter_frame = ttk.Frame(status_frame)
        counter_frame.pack(fill='x', pady=10)
        
        self.progress_counter = tk.StringVar(value="0/0 articles processed")
        ttk.Label(
            counter_frame, 
            text="Progress:",
            font=("Segoe UI", 10)
        ).pack(side='left', padx=(0, 10))
        
        ttk.Label(
            counter_frame, 
            textvariable=self.progress_counter,
            font=("Segoe UI", 10, "bold")
        ).pack(side='left')

        # Progress bar with improved visuals
        progress_frame = ttk.Frame(status_frame)
        progress_frame.pack(fill='x', padx=10, pady=10)
        
        self.progress_var = tk.DoubleVar()
        self.progress = ttk.Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=100,
            mode='determinate',
            length=400
        )
        self.progress.pack(side='left', fill='x', expand=True)
        
        self.progress_percent = tk.StringVar(value="0%")
        ttk.Label(
            progress_frame, 
            textvariable=self.progress_percent,
            font=("Segoe UI", 10, "bold"),
            width=6
        ).pack(side='left', padx=10)

        # Control buttons with more spacing and better styling
        btn_frame = ttk.Frame(process_frame)
        btn_frame.pack(pady=25)

        self.start_btn = ttk.Button(
            btn_frame, 
            text="▶️ Start Processing",
            command=self._start_processing,
            style="Primary.TButton",
            padding=(15, 10)
        )
        self.start_btn.pack(side='left', padx=10)

        self.stop_btn = ttk.Button(
            btn_frame, 
            text="⏹️ Stop Processing",
            command=self._stop_processing,
            state='disabled',
            style="Danger.TButton",
            padding=(15, 10)
        )
        self.stop_btn.pack(side='left', padx=10)
        
        # Add information box for users
        info_frame = ttk.LabelFrame(process_frame, text="Information", padding=15)
        info_frame.pack(fill='x', pady=15)
        
        ttk.Label(
            info_frame,
            text="The processing engine will fetch articles based on your search terms and analyze them for relevance. " 
                 "This process may take several minutes depending on the number of search terms and available articles.",
            wraplength=600,
            justify='left'
        ).pack(anchor='w')

        # Add step-by-step processing controls
        steps_frame = ttk.LabelFrame(process_frame, text="Processing Steps", padding=15)
        steps_frame.pack(fill='x', pady=15)

        # Step buttons frame
        step_btns_frame = ttk.Frame(steps_frame)
        step_btns_frame.pack(fill='x', pady=5)

        # Create step buttons
        self.fetch_btn = ttk.Button(
            step_btns_frame,
            text="1. Fetch Articles",
            command=self._start_fetch_only,
            style="Secondary.TButton",
            padding=(10, 5)
        )
        self.fetch_btn.pack(side='left', padx=5)

        self.clean_btn = ttk.Button(
            step_btns_frame,
            text="2. Clean Articles",
            command=self._start_cleaning_only,
            style="Secondary.TButton",
            padding=(10, 5)
        )
        self.clean_btn.pack(side='left', padx=5)

        self.analyze_btn = ttk.Button(
            step_btns_frame,
            text="3. Analyze Relevance",
            command=self._start_analysis_only,
            style="Secondary.TButton",
            padding=(10, 5)
        )
        self.analyze_btn.pack(side='left', padx=5)

        # Add separator between step controls and main controls
        ttk.Separator(process_frame, orient='horizontal').pack(fill='x', pady=15)

    def _create_results_tab(self):
        """Create enhanced results viewing tab with better visuals"""
        results_frame = ttk.Frame(self.notebook, padding="20")
        self.notebook.add(results_frame, text='Results')
        
        # Add heading
        ttk.Label(
            results_frame, 
            text="Search Results", 
            font=("Segoe UI", 14, "bold"),
            foreground=self.colors['primary']
        ).pack(anchor='w', pady=(0, 15))

        # Search and filter frame with better design
        filter_frame = ttk.LabelFrame(results_frame, text="Filter Results", padding="15")
        filter_frame.pack(fill='x', pady=10)
        
        ttk.Label(filter_frame, text="Search:", font=("Segoe UI", 10)).pack(side='left', padx=(0, 5))
        
        # Improved search box
        search_entry = ttk.Entry(filter_frame, width=40, font=("Segoe UI", 10))
        search_entry.pack(side='left', padx=5)
        
        ttk.Button(
            filter_frame, 
            text="🔍 Search",
            style="Primary.TButton",
            padding=(10, 5)
        ).pack(side='left', padx=5)
        
        # Add relevance filter
        ttk.Label(filter_frame, text="Min. Relevance:", font=("Segoe UI", 10)).pack(side='left', padx=(20, 5))
        
        relevance_combobox = ttk.Combobox(
            filter_frame,
            values=["All", "Low (>0.3)", "Medium (>0.5)", "High (>0.7)", "Very High (>0.9)"],
            width=15,
            state="readonly"
        )
        relevance_combobox.current(0)
        relevance_combobox.pack(side='left', padx=5)

        # Results container with better frame
        results_container = ttk.LabelFrame(results_frame, text="Articles", padding="15")
        results_container.pack(fill='both', expand=True, pady=10)
        
        # Create tree container with scrollbars
        tree_frame = ttk.Frame(results_container)
        tree_frame.pack(fill='both', expand=True)
        
        # Add scrollbars
        y_scrollbar = ttk.Scrollbar(tree_frame, orient='vertical')
        y_scrollbar.pack(side='right', fill='y')
        
        x_scrollbar = ttk.Scrollbar(tree_frame, orient='horizontal')
        x_scrollbar.pack(side='bottom', fill='x')

        # Results treeview with better styling
        self.results_tree = ttk.Treeview(
            tree_frame,
            columns=('title', 'relevance_score', 'url'),
            show='headings',
            selectmode='browse',
            yscrollcommand=y_scrollbar.set,
            xscrollcommand=x_scrollbar.set
        )
        
        # Configure scrollbars
        y_scrollbar.config(command=self.results_tree.yview)
        x_scrollbar.config(command=self.results_tree.xview)
        
        # Define column headings with better formatting
        self.results_tree.heading('title', text='Title')
        self.results_tree.heading('relevance_score', text='Relevance')
        self.results_tree.heading('url', text='URL')
        
        # Configure column widths
        self.results_tree.column('title', width=400, minwidth=200)
        self.results_tree.column('relevance_score', width=100, minwidth=80)
        self.results_tree.column('url', width=300, minwidth=150)
        
        self.results_tree.pack(fill='both', expand=True)
        
        # Add tag configuration for visual feedback based on relevance
        self.results_tree.tag_configure('high_relevance', background='#d5f5e3')  # Light green
        self.results_tree.tag_configure('medium_relevance', background='#fef9e7')  # Light yellow
        self.results_tree.tag_configure('low_relevance', background='#fadbd8')  # Light red

        # Action buttons frame
        action_frame = ttk.Frame(results_frame)
        action_frame.pack(fill='x', pady=15, anchor='e')
        
        ttk.Button(
            action_frame, 
            text="📋 Copy Selected URL",
            padding=(10, 5)
        ).pack(side='right', padx=5)
        
        ttk.Button(
            action_frame, 
            text="📤 Export Results", 
            command=self._export_results,
            padding=(10, 5),
            style="Primary.TButton"
        ).pack(side='right', padx=5)

    def _create_tooltip(self, widget, text):
        """Create a simple tooltip for a widget"""
        def enter(event):
            self.tooltip = tk.Toplevel(self.root)
            self.tooltip.wm_overrideredirect(True)
            self.tooltip.wm_geometry(f"+{event.x_root+10}+{event.y_root+10}")
            
            label = ttk.Label(
                self.tooltip, 
                text=text, 
                background=self.colors['bg_dark'],
                foreground=self.colors['text_light'],
                padding=5
            )
            label.pack()
            
        def leave(event):
            if hasattr(self, 'tooltip'):
                self.tooltip.destroy()
                
        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)

    def _save_config(self):
        """Save configuration changes with validation and feedback"""
        try:
            news_api_key = self.news_api_key.get()
            openai_api_key = self.openai_api_key.get()
            threshold = self.relevance_threshold.get()
            
            # Update config
            self.config_manager.set("NEWS_API_KEY", news_api_key)
            self.config_manager.set("OPENAI_API_KEY", openai_api_key) 
            self.config_manager.set("RELEVANCE_THRESHOLD", threshold)

            # Validate config
            if self.config_manager.validate():
                messagebox.showinfo("Success", "Configuration saved and validated successfully!")
                self.status_bar.config(text="Configuration saved and validated successfully")
            else:
                messagebox.showwarning("Warning", "Configuration saved but validation failed. Check API keys.")
                self.status_bar.config(text="Configuration saved but validation failed")
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            messagebox.showerror("Error", f"Failed to save configuration: {e}")
            self.status_bar.config(text=f"Error: Failed to save configuration")

    def _add_search_term(self):
        """Add new search term with feedback"""
        term = tk.simpledialog.askstring("Add Search Term", "Enter new search term:")
        if term:
            self.search_manager.insert_search_term(term)
            self._refresh_search_terms()
            self.status_bar.config(text=f"Added new search term: {term}")

    def _remove_search_term(self):
        """Remove selected search term with feedback"""
        selection = self.terms_list.curselection()
        if selection:
            term = self.terms_list.get(selection[0])
            self.search_manager.delete_search_term(term)
            self._refresh_search_terms()
            self.status_bar.config(text=f"Removed search term: {term}")
        else:
            self.status_bar.config(text="No search term selected for removal")

    def _import_search_terms(self):
        """Import search terms from a file with feedback"""
        file_path = filedialog.askopenfilename(
            title="Select Search Terms File",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if file_path:
            try:
                count = self.search_manager.insert_search_terms_from_txt(file_path)
                self._refresh_search_terms()
                messagebox.showinfo("Success", f"Imported {count} search terms successfully!")
                self.status_bar.config(text=f"Imported {count} search terms from {Path(file_path).name}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to import search terms: {e}")
                logger.error(f"Failed to import search terms: {e}")
                self.status_bar.config(text="Error importing search terms")

    def _export_search_terms(self):
        """Export search terms to a file with feedback"""
        file_path = filedialog.asksaveasfilename(
            title="Save Search Terms",
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
        )
        if file_path:
            try:
                terms = self.search_manager.get_search_terms()
                with open(file_path, 'w', encoding='utf-8') as f:
                    for term in terms:
                        f.write(f"{term['term']}\n")
                messagebox.showinfo("Success", "Search terms exported successfully!")
                self.status_bar.config(text=f"Exported {len(terms)} search terms to {Path(file_path).name}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export search terms: {e}")
                logger.error(f"Failed to export search terms: {e}")
                self.status_bar.config(text="Error exporting search terms")

    def _refresh_search_terms(self):
        """Refresh search terms list"""
        self.terms_list.delete(0, tk.END)
        terms = self.search_manager.get_search_terms()
        for term in terms:
            self.terms_list.insert(tk.END, term['term'])

    async def _process_articles(self):
        """Process articles using existing functionality with better feedback"""
        if self._processing:
            return
            
        self._processing = True
        try:
            # Update status indicators
            self.status_icon.configure(text="🔄")
            
            search_terms = self.search_manager.get_search_terms()
            if not search_terms:
                self._update_status("No search terms defined. Please add search terms first.", is_error=True)
                return

            scraper = NewsArticleScraper(self.config_manager)
            self._update_status("Fetching articles from news sources...")
            articles = await scraper.fetch_all_articles(search_terms)
            
            if articles:
                total_articles = len(articles)
                processed = 0
                
                self._update_status(f"Processing {total_articles} articles...")
                
                # Validate and clean articles before processing
                cleaned_articles = []
                for article in articles:
                    clean_article = self.validator.clean_article(article)
                    if clean_article:
                        cleaned_articles.append(clean_article)
                        self.article_manager.insert_article(clean_article, article['search_term_id'])
                        processed += 1
                        self._update_progress(processed, total_articles)
                
                # Use ArticleProcessor for relevance processing
                if cleaned_articles:
                    self._update_status("Analyzing article relevance...")
                    results = await self.processor.process_articles(cleaned_articles)
                    self._update_results_view(results)
                    
                    # Use processor's analysis features
                    self.processor.analyze_results()
                    
                    self._update_status("Processing completed successfully", is_success=True)
                    self.status_icon.configure(text="✅")
                else:
                    self._update_status("No valid articles to process", is_warning=True)
                    self.status_icon.configure(text="⚠️")
            else:
                self._update_status("No articles found for your search terms", is_warning=True)
                self.status_icon.configure(text="⚠️")
                
        except Exception as e:
            logger.error(f"Processing error: {e}")
            self._update_status(f"Error: {str(e)}", is_error=True)
            self.status_icon.configure(text="❌")
        finally:
            self._processing = False
            self.start_btn.config(state='normal')
            self.stop_btn.config(state='disabled')

    def _start_processing(self):
        """Start article processing with visual feedback"""
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        
        # Reset progress indicators
        self.progress_var.set(0)
        self.progress_percent.set("0%")
        self.progress_counter.set("0/0 articles processed")
        
        self._update_status("Starting processing engine...")
        
        # Run processing in background
        threading.Thread(target=lambda: asyncio.run(self._process_articles())).start()

    def _stop_processing(self):
        """Stop article processing with user confirmation"""
        if messagebox.askyesno("Confirm", "Are you sure you want to stop processing?"):
            self.start_btn.config(state='normal')
            self.stop_btn.config(state='disabled')
            self._update_status("Processing stopped by user", is_warning=True)
            self.status_icon.configure(text="⏹️")
            self._processing = False

    async def _fetch_articles_only(self):
        """Process only the article fetching step"""
        self._update_status("Fetching articles from news sources...")
        search_terms = self.search_manager.get_search_terms()
        if not search_terms:
            self._update_status("No search terms defined. Please add search terms first.", is_error=True)
            return None
            
        scraper = NewsArticleScraper(self.config_manager)
        articles = await scraper.fetch_all_articles(search_terms)
        
        if articles:
            self._update_status(f"Fetched {len(articles)} articles", is_success=True)
        else:
            self._update_status("No articles found", is_warning=True)
        return articles

    async def _clean_articles_only(self, articles=None):
        """Process only the article cleaning step"""
        if not articles:
            articles = self.article_manager.get_articles()
            
        if not articles:
            self._update_status("No articles to clean", is_warning=True)
            return None
            
        self._update_status(f"Cleaning {len(articles)} articles...")
        cleaned_articles = []
        for idx, article in enumerate(articles):
            clean_article = self.validator.clean_article(article)
            if clean_article:
                cleaned_articles.append(clean_article)
                self._update_progress(idx + 1, len(articles))
                
        if cleaned_articles:
            self._update_status(f"Cleaned {len(cleaned_articles)} articles", is_success=True)
        else:
            self._update_status("No articles passed cleaning", is_warning=True)
        return cleaned_articles

    async def _analyze_articles_only(self, articles=None):
        """Process only the article analysis step"""
        if not articles:
            # Get most recently cleaned articles from database
            articles = self.article_manager.get_articles()
            
        if not articles:
            self._update_status("No articles to analyze", is_warning=True)
            return None
            
        self._update_status(f"Analyzing relevance for {len(articles)} articles...")
        results = await self.processor.process_articles(articles)
        
        if results:
            self._update_status(f"Analyzed {len(results)} articles", is_success=True)
            self._update_results_view(results)
        else:
            self._update_status("No relevant articles found", is_warning=True)
        return results

    def _start_fetch_only(self):
        """Start only the fetch step"""
        self.fetch_btn.config(state='disabled')
        threading.Thread(target=lambda: asyncio.run(self._fetch_articles_only())).start()
        self.fetch_btn.config(state='normal')

    def _start_cleaning_only(self):
        """Start only the cleaning step"""
        self.clean_btn.config(state='disabled')
        threading.Thread(target=lambda: asyncio.run(self._clean_articles_only())).start()
        self.clean_btn.config(state='normal')

    def _start_analysis_only(self):
        """Start only the analysis step"""
        self.analyze_btn.config(state='disabled')
        threading.Thread(target=lambda: asyncio.run(self._analyze_articles_only())).start()
        self.analyze_btn.config(state='normal')

    def _update_results_view(self, results):
        """Update results treeview in main thread with visual indicators"""
        if not results:
            return
            
        # Use after() to safely update GUI from worker thread
        self.root.after(0, self._do_update_results, results)

    def _do_update_results(self, results):
        """Perform actual results update in main thread with visual tags"""
        self.results_tree.delete(*self.results_tree.get_children())
        for result in results:
            relevance = result.get('relevance_score', 0)
            
            # Determine the tag based on relevance score
            tag = None
            if relevance >= 0.7:
                tag = 'high_relevance'
            elif relevance >= 0.4:
                tag = 'medium_relevance'
            else:
                tag = 'low_relevance'
                
            self.results_tree.insert(
                '', 'end', 
                values=(
                    result.get('title', ''),
                    f"{float(relevance):.2f}" if relevance else '',
                    result.get('url', '')
                ),
                tags=(tag,)
            )

    def _export_results(self):
        """Export results to desktop with better feedback"""
        desktop_path = str(Path.home() / "Desktop")
        file_path = filedialog.asksaveasfilename(
            title="Save Results As",
            initialdir=desktop_path,
            defaultextension=".txt",
            filetypes=[("Text Files", "*.txt"), ("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        
        if not file_path:
            return
            
        try:
            from src.extract_cleaned_articles import extract_cleaned_data
            extract_cleaned_data(self.db_manager.db_path, file_path)
            messagebox.showinfo("Success", f"Results exported to {file_path}")
            self.status_bar.config(text=f"Results exported to {Path(file_path).name}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export results: {e}")
            self.status_bar.config(text="Error exporting results")

    def _update_progress(self, current: int, total: int):
        """Update progress bar and counter with animation"""
        if total > 0:
            percentage = (current / total) * 100
            self.progress_var.set(percentage)
            self.progress_percent.set(f"{percentage:.1f}%")
            self.progress_counter.set(f"{current}/{total} articles processed")
        
        # Force GUI update
        self.root.update_idletasks()

    def _update_status(self, message: str, is_error: bool = False, is_warning: bool = False, is_success: bool = False):
        """Update status with visual feedback based on message type"""
        self.status_var.set(message)
        
        # Update status bar too
        self.status_bar.config(text=message)
        
        # Apply color based on message type
        if is_error:
            self.status_var.set(f"{message}")
            self.status_bar.config(foreground=self.colors['accent'])
        elif is_warning:
            self.status_var.set(f"{message}")
            self.status_bar.config(foreground='orange')
        elif is_success:
            self.status_var.set(f"{message}")
            self.status_bar.config(foreground=self.colors['secondary'])
        else:
            self.status_var.set(message)
            self.status_bar.config(foreground='')
        
        # Force GUI update
        self.root.update_idletasks()

    def run(self):
        """Start the GUI application"""
        # Center window on screen
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
        
        self.root.mainloop()

if __name__ == "__main__":
    app = NewsScraperGUI()
    app.run()