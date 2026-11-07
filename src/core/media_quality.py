"""Legacy import compatibility for the native image-validation module.

The implementation lives in src.pictova.engine.media_validation. Old import
paths remain available for callers of src.main and older integrations.
"""

from src.pictova.engine.media_validation import (
    ALLOWED_SIZES,
    ANCHOR_EQUIVALENTS,
    BAD_METADATA_TOKENS,
    GENERIC_ANCHORS,
    _anchor_tokens_from_text,
    _collect_semantic_anchors,
    _contains_bad_token,
    _expand_anchor_tokens,
    _has_anchor_support,
    _phrase_supported,
    _tokenize_phrase,
    normalize_text,
    validate_metadata,
    validate_processed_asset,
)

__all__ = [
    "ALLOWED_SIZES",
    "ANCHOR_EQUIVALENTS",
    "BAD_METADATA_TOKENS",
    "GENERIC_ANCHORS",
    "normalize_text",
    "validate_metadata",
    "validate_processed_asset",
]
