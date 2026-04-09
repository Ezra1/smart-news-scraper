from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class QueryPlanItem:
    term: str
    root_term: str
    language: str
    regions: List[str]
    priority: int


def resolve_request_budget(mode: str, configured_budget: int) -> int:
    normalized_mode = str(mode or "").strip().lower()
    if configured_budget > 0:
        return configured_budget
    if normalized_mode == "light":
        return 50
    if normalized_mode == "medium":
        return 200
    return 500


def apply_budget_to_queries(queries: List[QueryPlanItem], budget: int) -> List[QueryPlanItem]:
    if not queries or budget <= 0:
        return []
    # Keep highest-priority queries first while preserving deterministic order.
    ordered = sorted(
        list(enumerate(queries)),
        key=lambda item: (item[1].priority, item[0]),
    )
    limited = [query for _, query in ordered[:budget]]
    return limited

