"""The placement policy must follow the measurement, not a hardcoded level."""

from __future__ import annotations

import pytest

from src.pictova.engine.placement import (
    fill_rate,
    heading_kind,
    is_placement_target,
    rank_headings,
    should_render_as_gallery,
)


def test_numbered_heading_outranks_a_lead_in_question_heading():
    """Measured: numbered headings ~70%/50% filled, plain H2 18%, H3 13%."""
    headings = [
        {"text": "İzmir Köylerine Nasıl Gidilir?", "level": 2},
        {"text": "Nerede Kalınır?", "level": 2},
        {"text": "1. Şirince, Selçuk", "level": 2},
        {"text": "2. Birgi, Ödemiş", "level": 2},
    ]

    ranked = rank_headings(headings)

    assert [h["text"] for h in ranked] == ["1. Şirince, Selçuk", "2. Birgi, Ödemiş"]


def test_numbered_h2_is_a_target_even_though_it_is_not_h3():
    """The old rule required level>=3 and ignored numbered H2 list posts."""
    numbered_h2 = {"text": "1. Şirince, Selçuk", "level": 2}
    numbered_h3 = {"text": "1. Ohrid Gölü", "level": 3}
    plain_h2 = {"text": "Nerede Kalınır?", "level": 2}

    assert heading_kind(numbered_h2) == "h2-numbered"
    assert is_placement_target(numbered_h2)
    assert is_placement_target(numbered_h3)
    assert not is_placement_target(plain_h2)


def test_document_order_is_kept_inside_one_heading_kind():
    headings = [
        {"text": "3. Kozbeyli", "level": 3},
        {"text": "1. Şirince", "level": 3},
        {"text": "2. Birgi", "level": 3},
    ]

    assert [h["text"] for h in rank_headings(headings)] == [
        "3. Kozbeyli", "1. Şirince", "2. Birgi",
    ]


def test_ranking_falls_back_when_no_kind_clears_the_floor():
    """A post of only lead-in headings still gets a usable ordering."""
    headings = [{"text": "Nasıl Gidilir?", "level": 2}, {"text": "Notlar", "level": 4}]

    ranked = rank_headings(headings)

    assert len(ranked) == 2
    assert ranked[0]["text"] == "Nasıl Gidilir?"  # higher measured rate first


def test_rank_headings_handles_no_headings():
    assert rank_headings([]) == []


@pytest.mark.parametrize(("count", "expected"), [(1, False), (2, True), (3, True), (4, False)])
def test_gallery_sizes_match_published_blocks(count, expected):
    """Measured block shapes: single 66%, gallery-2 28%, gallery-3 2%, nothing above."""
    assert should_render_as_gallery(count) is expected


def test_fill_rate_is_read_from_the_measured_profile():
    # Numbered headings must rank above their unnumbered counterparts.
    assert fill_rate("h3-numbered") > fill_rate("h3")
    assert fill_rate("h2-numbered") > fill_rate("h2")
    # An unknown kind is simply not a target rather than an error.
    assert fill_rate("h9-unknown") == 0.0
