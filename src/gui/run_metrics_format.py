"""Human-readable formatting for PipelineRunResult.run_metrics."""

from __future__ import annotations

from typing import Any, Dict

from src.pipeline_result import PipelineRunResult


def format_run_metrics_markdown(result: PipelineRunResult | None) -> str:
    """Structured summary for Diagnostics / Overview (no backend beyond run_metrics)."""
    if result is None:
        return "No pipeline run has finished in this session yet."

    lines: list[str] = []
    lines.append("## Last completed run")
    lines.append("")
    lines.append(result.completion_detail or "(no completion detail)")
    lines.append("")
    if result.completed_successfully:
        lines.append("**Outcome:** completed without analysis failures")
    else:
        lines.append("**Outcome:** completed with issues or failures")
    lines.append("")
    m: Dict[str, Any] = result.run_metrics if isinstance(result.run_metrics, dict) else {}

    eff = m.get("effective_settings")
    if isinstance(eff, dict) and eff:
        lines.append("### Settings used for this run")
        for k in sorted(eff.keys()):
            lines.append(f"- **{k}:** `{eff[k]}`")
        lines.append("")

    fetch = m.get("fetch")
    if isinstance(fetch, dict) and fetch:
        lines.append("### Fetch")
        for k, v in fetch.items():
            lines.append(f"- {k}: **{v}**")
        lines.append("")

    clean = m.get("clean")
    if isinstance(clean, dict) and clean:
        lines.append("### Normalize and validate")
        for k, v in clean.items():
            lines.append(f"- {k}: **{v}**")
        lines.append("")

    pre = m.get("pre_llm")
    if isinstance(pre, dict) and pre:
        lines.append("### Pre-AI gate")
        _pre_labels = {
            "retrieved_count": "Articles retrieved",
            "after_heuristics_count": "After rule-based checks",
            "after_semantic_count": "After semantic checks",
            "sent_to_llm_count": "Sent to relevance scoring",
        }
        for k in ("retrieved_count", "after_heuristics_count", "after_semantic_count", "sent_to_llm_count"):
            if k in pre:
                label = _pre_labels.get(k, k)
                lines.append(f"- {label}: **{pre[k]}**")
        drops = pre.get("dropped_by_reason")
        if isinstance(drops, dict) and drops:
            lines.append("- Drop reasons:")
            for reason, cnt in sorted(drops.items(), key=lambda x: (-x[1], x[0])):
                lines.append(f"  - `{reason}`: {cnt}")
        lines.append("")

    an = m.get("analyze")
    if isinstance(an, dict) and an:
        lines.append("### Relevance scoring phase")
        for k, v in an.items():
            lines.append(f"- {k}: **{v}**")
        lines.append("")

    funnel = m.get("funnel_rates")
    if isinstance(funnel, dict) and funnel:
        lines.append("### Funnel conversion rates")
        for k, v in funnel.items():
            lines.append(f"- {k}: **{v}**")
        lines.append("")

    top_fetch = m.get("fetch", {}).get("top_roots_by_fetch_count") if isinstance(m.get("fetch"), dict) else None
    if isinstance(top_fetch, list) and top_fetch:
        lines.append("### Top root terms by fetched volume")
        for row in top_fetch:
            if not isinstance(row, dict):
                continue
            lines.append(f"- {row.get('term', '')}: **{row.get('count', 0)}**")
        lines.append("")

    top_relevant = m.get("top_roots_by_relevant_count")
    if isinstance(top_relevant, list) and top_relevant:
        lines.append("### Top root terms by relevant results")
        for row in top_relevant:
            if not isinstance(row, dict):
                continue
            lines.append(f"- {row.get('term', '')}: **{row.get('count', 0)}**")
        lines.append("")

    expansion_diag = m.get("fetch", {}).get("expansion_diagnostics") if isinstance(m.get("fetch"), dict) else None
    if isinstance(expansion_diag, dict) and expansion_diag:
        lines.append("### Query expansion diagnostics")
        for key in ("ai_attempts", "ai_fallbacks", "expanded_queries_count", "max_total_queries"):
            if key in expansion_diag:
                lines.append(f"- {key}: **{expansion_diag[key]}**")
        fallback_by_language = expansion_diag.get("ai_fallbacks_by_language")
        if isinstance(fallback_by_language, dict) and fallback_by_language:
            lines.append("- AI fallback count by language:")
            for language, count in sorted(fallback_by_language.items(), key=lambda item: (-item[1], item[0])):
                lines.append(f"  - `{language}`: {count}")
        lines.append("")

    lines.append("### Output")
    lines.append(f"- Articles kept (relevant): **{len(result.relevant_articles)}**")
    lines.append(f"- Articles scored: **{result.articles_analyzed}**")
    lines.append(f"- Scoring errors: **{result.analysis_errors}**")
    lines.append("")

    return "\n".join(lines)


def format_run_metrics_plain(result: PipelineRunResult | None) -> str:
    """Plain text variant for widgets without reliable Markdown rendering."""
    raw = format_run_metrics_markdown(result).replace("**", "").replace("`", "").replace("#", "")
    lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("<!--")]
    return "\n".join(lines)
