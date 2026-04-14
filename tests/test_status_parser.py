import pytest

from src.gui.status_parser import StatusParser, StatusUpdate
from src.gui.processing_state import ProcessingState


class TestStatusParser:
    def setup_method(self):
        self.parser = StatusParser()

    def test_status_parser_extracts_term(self):
        status = self.parser.parse("Processing term 3/10: pharma (5 articles found)")

        assert status.term_progress is not None
        assert status.term_progress.current == 3
        assert status.term_progress.total == 10
        assert status.term_progress.term == "pharma"
        assert status.term_progress.articles_found == 5
        assert status.counts.fetched == 5

    def test_analysis_progress_parsed(self):
        status = self.parser.parse("Analyzed 4/8 articles")

        assert status.analysis_started is True
        assert status.analysis_progress is not None
        assert status.analysis_progress.current == 4
        assert status.analysis_progress.total == 8
        assert status.analysis_complete is False

    def test_cleaning_progress_parsed(self):
        status = self.parser.parse("Cleaned 2/5 articles")

        assert status.cleaning_started is True
        assert status.cleaning_progress is not None
        assert status.cleaning_progress.current == 2
        assert status.cleaning_progress.total == 5
        assert status.cleaning_complete is False

    def test_completion_flags(self):
        status = self.parser.parse("Completed cleaning 5/5 articles")

        assert status.cleaning_complete is True
        assert status.analysis_complete is False
        assert status.fetch_complete is False

    def test_rate_limit_flag(self):
        status = self.parser.parse(
            "Rate limit reached after finding 12 articles. Moving to cleaning phase..."
        )

        assert status.rate_limited is True
        assert status.fetch_complete is False

    def test_completed_fetch_sets_run_unique_count(self):
        status = self.parser.parse(
            "Completed fetch: 42 articles from 5/10 terms", False, False, True
        )

        assert status.fetch_complete is True
        assert status.counts.fetched_run_unique == 42


class TestProcessingState:
    def test_update_from_status_sets_term_and_processed(self):
        state = ProcessingState()
        parser = StatusParser()
        status = StatusUpdate(
            message="Analyzed 3/6 articles",
            analysis_progress=parser.parse("Analyzed 3/6 articles").analysis_progress,
            term_progress=parser.parse("Processing term 2/4: biotech").term_progress,
        )

        state.update_from_status(status)

        assert state.current_term == "biotech"
        assert state.total_processed == 3
        assert state.error_count == 0

    def test_update_from_status_increments_error(self):
        state = ProcessingState()
        status = StatusUpdate(message="Error: failed", is_error=True)

        state.update_from_status(status)
        state.update_from_status(status)

        assert state.error_count == 2

    def test_reset_clears_counts(self):
        state = ProcessingState(total_processed=5, relevant_count=2, irrelevant_count=1, error_count=3, current_term="bio")

        state.reset()

        assert state.total_processed == 0
        assert state.relevant_count == 0
        assert state.irrelevant_count == 0
        assert state.error_count == 0
        assert state.current_term == ""

