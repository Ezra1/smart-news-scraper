"""Structured return value from PipelineManager.execute_pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AnalysisPhaseResult:
    """Output of the LLM relevance phase."""

    relevant_articles: List[Dict[str, Any]] = field(default_factory=list)
    analyzed_count: int = 0
    error_count: int = 0


@dataclass
class PipelineRunResult:
    """Outcome of fetch → clean → filter → analyze."""

    relevant_articles: List[Dict[str, Any]] = field(default_factory=list)
    articles_analyzed: int = 0
    analysis_errors: int = 0
    """True when the run should be reported as successful in the UI (no analysis failures)."""
    completed_successfully: bool = True
    completion_detail: str = ""
    """Structured counts and settings for GUI observability (optional; filled by PipelineManager)."""
    run_metrics: Dict[str, Any] = field(default_factory=dict)
