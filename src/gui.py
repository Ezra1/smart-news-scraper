import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
import asyncio
import threading
from typing import Optional
from queue import Queue

from src.logger_config import setup_logging
from src.config import ConfigManager
from src.database_manager import DatabaseManager, ArticleManager, SearchTermManager
from src.news_scraper import NewsArticleScraper
from src.openai_relevance_processing import ArticleProcessor

logger = setup_logging(__name__)

class NewsScraperGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Smart News Scraper")
        self.root.geometry("800x600")
        
        # Initialize managers
        self.config_manager = ConfigManager()
        self.db_manager = DatabaseManager()
        self.search_manager = SearchTermManager(self.db_manager)
        self.article_manager = ArticleManager(self.db_manager)
        
        # Create processing queue
        self.processing_queue = Queue()
        
        self._create_notebook()
        self._create_config_tab()
        self._create_search_terms_tab()
        self._create_processing_tab()
        self._create_results_tab()

    def _create_notebook(self):
        """Create main notebook with tabs"""
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill='both', padx=5, pady=5)

    def _create_config_tab(self):
        """Create configuration tab"""
        config_frame = ttk.Frame(self.notebook)
        self.notebook.add(config_frame, text='Configuration')

        # API Keys
        ttk.Label(config_frame, text="News API Key:").grid(row=0, column=0, padx=5, pady=5)
        self.news_api_key = ttk.Entry(config_frame, show="*")
        self.news_api_key.insert(0, self.config_manager.get("NEWS_API_KEY", ""))
        self.news_api_key.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(config_frame, text="OpenAI API Key:").grid(row=1, column=0, padx=5, pady=5)
        self.openai_api_key = ttk.Entry(config_frame, show="*")
        self.openai_api_key.insert(0, self.config_manager.get("OPENAI_API_KEY", ""))
        self.openai_api_key.grid(row=1, column=1, padx=5, pady=5)

        # Relevance Threshold
        ttk.Label(config_frame, text="Relevance Threshold:").grid(row=2, column=0, padx=5, pady=5)
        self.relevance_threshold = ttk.Scale(config_frame, from_=0.0, to=1.0, orient='horizontal')
        self.relevance_threshold.set(self.config_manager.get("RELEVANCE_THRESHOLD", 0.7))
        self.relevance_threshold.grid(row=2, column=1, padx=5, pady=5)

        # Save Button
        ttk.Button(config_frame, text="Save Configuration", 
                  command=self._save_config).grid(row=3, column=0, columnspan=2, pady=20)

    def _create_search_terms_tab(self):
        """Create search terms management tab"""
        search_frame = ttk.Frame(self.notebook)
        self.notebook.add(search_frame, text='Search Terms')

        # Search terms list
        self.terms_list = tk.Listbox(search_frame, height=10)
        self.terms_list.pack(fill='both', expand=True, padx=5, pady=5)

        # Buttons frame
        btn_frame = ttk.Frame(search_frame)
        btn_frame.pack(fill='x', padx=5, pady=5)

        ttk.Button(btn_frame, text="Add Term", 
                  command=self._add_search_term).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Remove Selected", 
                  command=self._remove_search_term).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Import from File", 
                  command=self._import_search_terms).pack(side='left', padx=5)
        ttk.Button(btn_frame, text="Export to File", 
                  command=self._export_search_terms).pack(side='left', padx=5)

        self._refresh_search_terms()

    def _create_processing_tab(self):
        """Create processing control tab"""
        process_frame = ttk.Frame(self.notebook)
        self.notebook.add(process_frame, text='Processing')

        # Status display
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(process_frame, textvariable=self.status_var).pack(pady=10)

        # Progress bar
        self.progress_var = tk.DoubleVar()
        self.progress = ttk.Progressbar(process_frame, variable=self.progress_var, 
                                      maximum=100)
        self.progress.pack(fill='x', padx=20, pady=10)

        # Control buttons
        btn_frame = ttk.Frame(process_frame)
        btn_frame.pack(pady=20)

        self.start_btn = ttk.Button(btn_frame, text="Start Processing", 
                                  command=self._start_processing)
        self.start_btn.pack(side='left', padx=5)

        self.stop_btn = ttk.Button(btn_frame, text="Stop Processing", 
                                 command=self._stop_processing, state='disabled')
        self.stop_btn.pack(side='left', padx=5)

    def _create_results_tab(self):
        """Create results viewing tab"""
        results_frame = ttk.Frame(self.notebook)
        self.notebook.add(results_frame, text='Results')

        # Results treeview
        columns = ('title', 'relevance_score', 'url')
        self.results_tree = ttk.Treeview(results_frame, columns=columns, show='headings')
        
        # Define column headings
        self.results_tree.heading('title', text='Title')
        self.results_tree.heading('relevance_score', text='Relevance')
        self.results_tree.heading('url', text='URL')
        
        # Configure column widths
        self.results_tree.column('title', width=300)
        self.results_tree.column('relevance_score', width=100)
        self.results_tree.column('url', width=200)
        
        self.results_tree.pack(fill='both', expand=True, padx=5, pady=5)

        # Export button
        ttk.Button(results_frame, text="Export Results", 
                  command=self._export_results).pack(pady=10)

    def _save_config(self):
        """Save configuration changes"""
        self.config_manager.set("NEWS_API_KEY", self.news_api_key.get())
        self.config_manager.set("OPENAI_API_KEY", self.openai_api_key.get())
        self.config_manager.set("RELEVANCE_THRESHOLD", self.relevance_threshold.get())
        messagebox.showinfo("Success", "Configuration saved successfully!")

    def _add_search_term(self):
        """Add new search term"""
        term = tk.simpledialog.askstring("Add Search Term", "Enter new search term:")
        if term:
            self.search_manager.insert_search_term(term)
            self._refresh_search_terms()

    def _remove_search_term(self):
        """Remove selected search term"""
        selection = self.terms_list.curselection()
        if selection:
            term = self.terms_list.get(selection[0])
            # Implement deletion in database
            self._refresh_search_terms()

    def _refresh_search_terms(self):
        """Refresh search terms list"""
        self.terms_list.delete(0, tk.END)
        terms = self.search_manager.get_search_terms()
        for term in terms:
            self.terms_list.insert(tk.END, term['term'])

    async def _process_articles(self):
        """Process articles asynchronously"""
        try:
            processor = ArticleProcessor()
            scraper = NewsArticleScraper(self.config_manager)
            
            # Get search terms
            search_terms = self.search_manager.get_search_terms()
            
            # Fetch and process articles
            articles = await scraper.fetch_all_articles(search_terms)
            if articles:
                results = await processor.process_articles(articles)
                self._update_results_view(results)
            
        except Exception as e:
            logger.error(f"Processing error: {e}")
            self.status_var.set(f"Error: {str(e)}")

    def _start_processing(self):
        """Start article processing"""
        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.status_var.set("Processing...")
        
        # Run processing in background
        threading.Thread(target=lambda: asyncio.run(self._process_articles())).start()

    def _stop_processing(self):
        """Stop article processing"""
        self.start_btn.config(state='normal')
        self.stop_btn.config(state='disabled')
        self.status_var.set("Processing stopped")

    def _update_results_view(self, results):
        """Update results treeview"""
        self.results_tree.delete(*self.results_tree.get_children())
        for result in results:
            self.results_tree.insert('', 'end', values=(
                result.get('title', ''),
                result.get('relevance_score', ''),
                result.get('url', '')
            ))

    def _export_results(self):
        """Export results to desktop"""
        desktop_path = str(Path.home() / "Desktop")
        output_file = str(Path(desktop_path) / "cleaned_articles.txt")
        
        try:
            from src.extract_cleaned_articles import extract_cleaned_data
            extract_cleaned_data(self.db_manager.db_path, output_file)
            messagebox.showinfo("Success", f"Results exported to {output_file}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export results: {e}")

    def run(self):
        """Start the GUI application"""
        self.root.mainloop()

if __name__ == "__main__":
    app = NewsScraperGUI()
    app.run()