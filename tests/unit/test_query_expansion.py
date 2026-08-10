"""Broadening a query must stay a suggestion, never a decision."""

from __future__ import annotations

from src.pictova.engine.query_expansion import expand_heading_query


def test_model_queries_are_cleaned_and_capped():
    def analyzer(prompt):
        assert "Kozbeyli" in prompt  # the heading reaches the model
        return '{"queries": ["stone house Aegean village", "  olive grove   hillside  ", "a", "d", "e", "f"]}'

    queries = expand_heading_query("3. Kozbeyli, Foça", {"title": "İzmir Köyleri"}, analyzer=analyzer)

    assert queries[:2] == ["stone house Aegean village", "olive grove hillside"]
    assert len(queries) <= 3


def test_long_query_is_trimmed_to_a_searchable_length():
    def analyzer(_prompt):
        return '{"queries": ["one two three four five six seven eight"]}'

    assert expand_heading_query("x", analyzer=analyzer) == ["one two three four five six"]


def test_duplicate_suggestions_collapse():
    def analyzer(_prompt):
        return '{"queries": ["aegean village", "Aegean  village", "harbour town"]}'

    assert expand_heading_query("x", analyzer=analyzer) == ["aegean village", "harbour town"]


def test_no_vision_source_yields_no_expansion():
    """An empty result is normal and keeps the selection fail-closed."""
    assert expand_heading_query("3. Kozbeyli, Foça", analyzer=lambda _p: "") == []


def test_unusable_model_reply_is_ignored():
    for reply in ("not json at all", '{"queries": "not a list"}', '{"other": []}'):
        assert expand_heading_query("x", analyzer=lambda _p, r=reply: r) == []


def test_analyzer_failure_does_not_propagate():
    def analyzer(_prompt):
        raise RuntimeError("model down")

    assert expand_heading_query("x", analyzer=analyzer) == []


def test_empty_heading_never_calls_the_model():
    calls = []

    def analyzer(prompt):
        calls.append(prompt)
        return '{"queries": ["x"]}'

    assert expand_heading_query("   ", analyzer=analyzer) == []
    assert calls == []
