"""Quality validation exports."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from src.core.media_quality import (
    BAD_METADATA_TOKENS,
    normalize_text,
    validate_metadata,
    validate_processed_asset,
)
from src.pictova.engine.selector import _matching_anchor_count


_EDITORIAL_NOISE_TOKENS = {
    "advert", "advertisement", "afis", "afiş", "banner", "brochure",
    "duyuru", "flyer", "kampanya", "marketing", "menu", "menü",
    "promo", "promotional", "reklam", "screenshot", "slide",
    "fiyat",
}
_EDITORIAL_CLICHE_TOKENS = {
    "harika", "buyuleyici", "benzersiz", "essiz", "muhtesem",
    "masalsi", "unutulmaz", "keyifli", "gizemli", "buyulu", "etkileyici",
}
_CONTEXT_STOPWORDS = {
    "bir", "ve", "ile", "icin", "için", "the", "and",
    "gezilecek", "yerler", "yerleri", "gezi", "rehberi", "rehber",
    "travel", "guide", "rota", "rotasi", "rotalar",
    "detayli", "guncel", "notlari", "notları",
    "yakin", "yakın", "ulasim", "ulaşım", "gecis", "geçiş",
    "tavsiyelerim", "tavsiyesi", "ipuclari", "ipuçları",
    "bilmeniz", "gerekenler", "gitmeden", "giris", "giriş", "ucreti", "ücreti",
    "kalinir", "kalınır", "nasil", "nasıl", "nerede", "yakininda", "yakınında",
}
_GENERIC_VISUAL_TOKENS = {
    "beach", "beautiful", "dag", "dağ", "forest", "guzel", "güzel", "image",
    "landscape", "manzara", "mountain", "mountains", "nature", "outdoor", "photo",
    "plaj", "selale", "selaleleri", "şelale", "şelaleleri", "view", "waterfall",
    "waterfalls",
}
_APPLICATION_CONTEXT_TOKENS = {
    "app", "apps", "application", "applications",
    "uygulama", "uygulamasi", "uygulamalari", "uygulamalar",
}
_TURKISH_ASCII = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u"})


def _tokenize(value: str) -> list[str]:
    value = normalize_text(value).translate(_TURKISH_ASCII)
    return [
        token
        for token in re.findall(r"[a-z0-9]+", value)
        if len(token) >= 3
    ]


def _meaningful_tokens(*values: object) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for token in _tokenize(str(value or "")):
            if token in BAD_METADATA_TOKENS:
                continue
            if token in _EDITORIAL_NOISE_TOKENS:
                continue
            if token in _CONTEXT_STOPWORDS:
                continue
            if token in _GENERIC_VISUAL_TOKENS:
                continue
            tokens.add(token)
    return tokens


def validate_native_metadata(metadata: Dict[str, Any], post_context: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    title = str(metadata.get("title", "")).strip()
    alt = str(metadata.get("alt", "")).strip()
    caption = str(metadata.get("caption", "")).strip()
    description = str(metadata.get("description", "")).strip()
    heading = str(metadata.get("heading", "")).strip()
    keywords = metadata.get("keywords", [])
    if isinstance(keywords, str):
        keyword_text = keywords
    elif isinstance(keywords, list):
        keyword_text = " ".join(str(item) for item in keywords if str(item).strip())
    else:
        keyword_text = ""
    post_title = normalize_text(post_context.get("title", ""))
    post_slug = normalize_text(post_context.get("slug", ""))
    context_tokens = _meaningful_tokens(post_context.get("title", ""), post_context.get("slug", ""), heading)
    heading_tokens = _meaningful_tokens(heading)
    image_tokens = _meaningful_tokens(
        title,
        alt,
        caption,
        description,
        keyword_text,
        metadata.get("scene", ""),
        metadata.get("activity", ""),
    )
    explicit_raw = metadata.get("required_heading_tokens", [])
    if not isinstance(explicit_raw, (list, tuple, set)):
        explicit_raw = [explicit_raw]
    explicit_tokens = _meaningful_tokens(*explicit_raw)
    visual_evidence = str(metadata.get("visual_evidence", "")).strip()
    visual_tokens = _meaningful_tokens(visual_evidence)
    article_tokens = set(_tokenize(
        f"{post_context.get('title', '')} {post_context.get('slug', '')}"
    ))

    if len(title) < 8:
        errors.append("title too short")
    if len(alt) < 12:
        errors.append("alt too short")
    if caption and len(caption) < 12:
        errors.append("caption too short")
    if description and len(description) < 12:
        errors.append("description too short")

    combined = normalize_text(
        " ".join([title, alt, caption, description, str(metadata.get("summary", "")), str(metadata.get("scene", "")), str(metadata.get("activity", "")), keyword_text])
    )
    if any(token in combined for token in BAD_METADATA_TOKENS):
        errors.append("metadata contains source junk tokens")
    noise_tokens = set(_tokenize(combined)) & _EDITORIAL_NOISE_TOKENS
    if "fiyat" in noise_tokens and "fiyat" in post_title:
        noise_tokens.remove("fiyat")
    if noise_tokens:
        errors.append("metadata looks promotional or editorially noisy")
    cliche_tokens = set(_tokenize(combined)) & _EDITORIAL_CLICHE_TOKENS
    if cliche_tokens:
        errors.append("metadata contains editorial cliches")

    if post_title and normalize_text(title) == post_title:
        errors.append("title mirrors post title without visual distinction")

    required_tokens = heading_tokens | context_tokens
    if required_tokens:
        if _matching_anchor_count(image_tokens, heading_tokens) == 0 and _matching_anchor_count(image_tokens, context_tokens) == 0:
            errors.append("metadata does not match heading or post context")
    elif post_slug and not context_tokens and not image_tokens:
        errors.append("metadata is missing contextual anchors")
    if explicit_tokens and not explicit_tokens <= image_tokens:
        errors.append("metadata is missing an exact assigned-heading entity")
    # Publishing fields are intentionally rewritten from the selected heading
    # for concise SEO. They cannot prove that the pixels show that entity.
    # For app/product lists the exact brand must be visible in an unprimed
    # vision result; a generic beach portrait may never pass as "Tinder".
    if (
        explicit_tokens
        and article_tokens & _APPLICATION_CONTEXT_TOKENS
        and not explicit_tokens <= visual_tokens
    ):
        errors.append("visual evidence does not confirm exact assigned-heading entity")

    return errors


def quality_gate_native_batch(
    *,
    processed_images: List[str],
    metadata_dict: Dict[str, Dict[str, Any]],
    processed_details: Dict[str, Dict[str, Any]],
    post_context: Dict[str, Any],
) -> Tuple[List[str], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    approved_files: List[str] = []
    approved_metadata: Dict[str, Dict[str, Any]] = {}
    approved_details: Dict[str, Dict[str, Any]] = {}
    blocked: List[Dict[str, Any]] = []

    for image_file in processed_images:
        metadata = metadata_dict.get(image_file, {})
        process_info = processed_details.get(image_file)
        errors = validate_native_metadata(metadata, post_context)
        errors.extend(validate_processed_asset(metadata, process_info))
        if errors:
            blocked.append({"file": image_file, "errors": errors})
            continue
        approved_files.append(image_file)
        approved_metadata[image_file] = metadata
        approved_details[image_file] = process_info or {}

    return approved_files, approved_metadata, approved_details, blocked


__all__ = [
    "normalize_text",
    "quality_gate_native_batch",
    "validate_metadata",
    "validate_native_metadata",
    "validate_processed_asset",
]
