"""Placement policy derived from measured behaviour, not hand-written rules.

`scripts/learn_placement_behavior.py` reads published posts and records which
headings actually receive an image and how those images are grouped. This
module turns that record into the two decisions the engine has to make:

  * which headings are worth filling, and in what order
  * whether the images under one heading render as a gallery or single blocks

The numbers live in ``data/placement_profile.json``. When it is missing the
measured values are used as defaults, so behaviour never depends on a file
being present — re-running the scan simply refreshes them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from src.utils.config import PROJECT_ROOT


_PROFILE_PATH = PROJECT_ROOT / "data" / "placement_profile.json"
_NUMBERED_RE = re.compile(r"^\s*\d{1,3}\s*[.\-):]")

# Measured on 300 published posts (172 guides, 139 with images, only 4 of them
# Pictova-managed — so this is overwhelmingly hand-made placement).
_MEASURED_FILL_RATE: Dict[str, float] = {
    "h2-numbered": 0.50,
    "h3-numbered": 0.71,
    "h4-numbered": 0.0,
    "h2": 0.18,
    "h3": 0.13,
    "h4": 0.09,
}
# A heading type below this rate is not a placement target: in the published
# record such headings are left without an image far more often than not.
_FILL_RATE_FLOOR = 0.25

_cached_profile: Dict[str, Any] | None = None


def _load_profile() -> Dict[str, Any]:
    global _cached_profile
    if _cached_profile is not None:
        return _cached_profile
    try:
        _cached_profile = json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _cached_profile = {}
    return _cached_profile


def heading_kind(heading: Dict[str, Any]) -> str:
    """Classify a heading the same way the measurement script did."""
    level = int(heading.get("level") or 0)
    text = str(heading.get("text") or "")
    suffix = "-numbered" if _NUMBERED_RE.match(text) else ""
    return f"h{level}{suffix}"


def fill_rate(kind: str) -> float:
    """How often a heading of this kind carries an image in published posts."""
    measured = _load_profile().get("heading_fill_rate") or {}
    entry = measured.get(kind)
    if isinstance(entry, dict) and isinstance(entry.get("rate"), (int, float)):
        return float(entry["rate"])
    return _MEASURED_FILL_RATE.get(kind, 0.0)


def rank_headings(headings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Order headings by how likely they are to deserve an image.

    A numbered list item is the concrete subject of its section and carries an
    image in most published posts; a lead-in question heading ("Nerede
    kalınır?") usually does not. Ordering by the measured rate keeps document
    order inside one kind while putting the real targets first.

    When no heading type clears the floor the original order is returned: a
    caller that explicitly asked for images should still get a usable list.
    """
    if not headings:
        return []
    ranked = sorted(
        enumerate(headings),
        key=lambda pair: (-fill_rate(heading_kind(pair[1])), pair[0]),
    )
    preferred = [
        heading for _, heading in ranked
        if fill_rate(heading_kind(heading)) >= _FILL_RATE_FLOOR
    ]
    return preferred or [heading for _, heading in ranked]


def is_placement_target(heading: Dict[str, Any]) -> bool:
    """Whether published behaviour puts images under this kind of heading."""
    return fill_rate(heading_kind(heading)) >= _FILL_RATE_FLOOR


def gallery_size_range() -> tuple[int, int]:
    """Smallest and largest image count that is rendered as a gallery.

    Measured block shapes: a single image is a plain block (66%), a pair is a
    gallery (28%), three is a rare but real gallery (2%). Four or more is
    noise in the record and is not produced.
    """
    shapes = _load_profile().get("block_shapes") or {}
    sizes = sorted(
        int(name.split("-")[1])
        for name in shapes
        if name.startswith("gallery-") and name.split("-")[1].isdigit()
        and shapes[name] >= max(3, 0.01 * sum(shapes.values()))
        and int(name.split("-")[1]) >= 2
    )
    if not sizes:
        return 2, 3
    return sizes[0], sizes[-1]


def should_render_as_gallery(image_count: int) -> bool:
    """A heading holding two or three images renders as one gallery block."""
    low, high = gallery_size_range()
    return low <= image_count <= high


__all__ = [
    "fill_rate",
    "gallery_size_range",
    "heading_kind",
    "is_placement_target",
    "rank_headings",
    "should_render_as_gallery",
]
