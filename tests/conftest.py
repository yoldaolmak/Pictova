"""Shared test guards.

The suite must never reach an external service. Query expansion asks a local or
hosted model for broader search terms, so without this fixture a selector test
would sit waiting on LM Studio or the Gemini API — the run went from 6 seconds
to 98 the moment expansion was wired in.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def no_model_calls_in_tests(monkeypatch):
    """Expansion returns nothing unless a test asks for it explicitly."""
    from src.pictova.engine import query_expansion

    monkeypatch.setattr(query_expansion, "_default_analyzer", lambda prompt: "")
