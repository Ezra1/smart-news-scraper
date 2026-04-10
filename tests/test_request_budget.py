from src.request_budget import QueryPlanItem, apply_budget_to_queries, resolve_request_budget


def test_resolve_request_budget_prefers_configured_value():
    assert resolve_request_budget("light", 77) == 77


def test_resolve_request_budget_mode_defaults():
    assert resolve_request_budget("light", 0) == 50
    assert resolve_request_budget("medium", 0) == 200
    assert resolve_request_budget("aggressive", 0) == 500


def test_apply_budget_to_queries_limits_and_prioritizes():
    queries = [
        QueryPlanItem(term="q1", root_term="a", language="en", priority=3),
        QueryPlanItem(term="q2", root_term="a", language="es", priority=1),
        QueryPlanItem(term="q3", root_term="a", language="fr", priority=2),
    ]
    limited = apply_budget_to_queries(queries, 2)
    assert [item.term for item in limited] == ["q2", "q3"]

