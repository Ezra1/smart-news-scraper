from dataclasses import dataclass

from src.gui.status_parser import StatusUpdate


@dataclass
class ProcessingState:
    """Track derived counters from pipeline status updates."""

    total_processed: int = 0
    relevant_count: int = 0
    irrelevant_count: int = 0
    error_count: int = 0
    current_term: str = ""

    def update_from_status(self, status: StatusUpdate) -> None:
        """Update state using parsed status details."""
        if status.term_progress and status.term_progress.term:
            self.current_term = status.term_progress.term

        if status.analysis_progress:
            self.total_processed = status.analysis_progress.current

        if status.is_error:
            self.error_count += 1

    def reset(self) -> None:
        """Reset counters to initial values."""
        self.total_processed = 0
        self.relevant_count = 0
        self.irrelevant_count = 0
        self.error_count = 0
        self.current_term = ""

