"""Selection helpers exposed from the canonical engine package."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from typing import Any, Dict, List

import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import time
from src.core.processor import get_vil_images
from src.core.media_quality import BAD_METADATA_TOKENS, GENERIC_ANCHORS, normalize_text
from src.pictova.engine.search import load_vil_images_from_index_for_post, search_semantic_assets
from src.pictova.config import get_visual_memory_db_path
from src.pictova.engine.placement import is_placement_target, rank_headings


# The exact free discovery result is reusable by the paid phase. Keep it in
# memory for one process and briefly on disk so a separate `plan` then `attach`
# does not consume the personal hotspot on the same provider search twice.
# The cached payload is the raw provider response, which depends only on the
# query and the fetch size. Keying it by the caller's token filters too made
# the same search run again for every distinct token set — the exact repeat
# this cache exists to prevent.
_DepositCacheKey = tuple[str, int]
_DEPOSIT_DISCOVERY_CACHE: dict[_DepositCacheKey, list[dict[str, Any]]] = {}
_DEPOSIT_DISCOVERY_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "deposit_cache" / "discovery"
_DEPOSIT_DISCOVERY_CACHE_TTL_SECONDS = 60 * 60


def _deposit_discovery_cache_path(cache_key: _DepositCacheKey) -> Path:
    payload = json.dumps(list(cache_key), ensure_ascii=False, separators=(",", ":"))
    return _DEPOSIT_DISCOVERY_CACHE_DIR / f"{sha256(payload.encode()).hexdigest()}.json"


def _load_deposit_discovery(cache_key: _DepositCacheKey) -> list[dict[str, Any]] | None:
    path = _deposit_discovery_cache_path(cache_key)
    try:
        if time.time() - path.stat().st_mtime > _DEPOSIT_DISCOVERY_CACHE_TTL_SECONDS:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        return None
    return data


def _save_deposit_discovery(cache_key: _DepositCacheKey, results: list[dict[str, Any]]) -> None:
    """Atomically retain a short-lived free search result for plan replay."""
    cache_dir = _DEPOSIT_DISCOVERY_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _deposit_discovery_cache_path(cache_key)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=cache_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(results, handle, ensure_ascii=False, separators=(",", ":"))
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass


def resolve_source_images(
    *,
    source: str,
    count: int | None,
    name: str | None,
    query: str | None,
    location_query: str | None,
    content_filter: str | None,
    post_context: Dict[str, Any],
    plan_only: bool = False,
) -> Dict[str, Any]:
    _count = count or 5

    if source == "auto":
        base_query = location_query or _primary_post_query(post_context) or _extract_location(post_context)
        selection_warnings: list[str] = []
        files, heading_assignments = _heading_specific_selection(
            post_context=post_context,
            content_filter=content_filter,
            limit=_count,
            allow_external=True,
            plan_only=plan_only,
            diagnostics=selection_warnings,
        )
        if len(files) >= _count:
            return {
                "source": "auto",
                "query": base_query,
                "content_filter": content_filter,
                "files": files[:_count],
                "heading_assignments": {file: heading_assignments[file] for file in files[:_count] if file in heading_assignments},
                "warnings": selection_warnings,
            }
        # Headings are the hard semantic contract.  A partial exact result is
        # safer than filling the remaining slots with a generic local image.
        if post_context.get("available_headings"):
            return {
                "source": "auto",
                "query": base_query,
                "content_filter": content_filter,
                "files": files,
                "heading_assignments": heading_assignments,
                "warnings": selection_warnings,
            }

        # 1. Local photos (semantic search)
        files = _semantic_heading_files(
            post_context=post_context,
            content_filter=content_filter,
            limit=_count,
        )
        if len(files) < _count:
            generic_files = search_semantic_assets(
                location_query=base_query,
                count=_count,
                content_filter=content_filter,
                post_context=post_context,
            )
            generic_files = _filter_relevant_candidates(
                generic_files,
                post_context=post_context,
                heading_text="",
                anchor_text=base_query,
            )
            files = list(dict.fromkeys(files + generic_files))[:_count]
        if len(files) >= _count:
            return {"source": "semantic", "query": location_query or "", "content_filter": content_filter, "files": files}

        # 2. iCloud candidate photos — first destination index, then FTS fallback
        need = _count - len(files)
        loc_q = base_query
        icloud_uuids = _destination_index_uuids(loc_q, need)
        if not icloud_uuids:
            icloud = search_semantic_assets(
                location_query=loc_q,
                count=need,
                content_filter=content_filter,
                post_context=post_context,
                include_icloud=True,
            )
            icloud_uuids = [f for f in icloud if f.startswith("icloud://")]
        if icloud_uuids:
            icloud_uuids = _filter_relevant_candidates(
                icloud_uuids,
                post_context=post_context,
                heading_text="",
                anchor_text=base_query,
            )
            files = files + icloud_uuids[:need]

        # 3. External sources — heading-aware when headings exist, batch otherwise
        if len(files) < _count:
            need = _count - len(files)
            base_q = base_query
            available_headings = post_context.get("available_headings") or []
            post_location = _turkify_to_english_query(_extract_location(post_context))

            if available_headings and not plan_only:
                # Per-heading selection: 1 photo per heading, specific query per slot
                # headings to fill = the ones that don't yet have a local/icloud photo
                already_filled = len(files)
                target_headings = available_headings[already_filled: already_filled + need]
                if not target_headings:
                    target_headings = available_headings[:need]

                external = []
                for h in target_headings:
                    heading_text = str(h.get("text", "") or "").strip()
                    h_q = _heading_to_search_query(heading_text, post_location=post_location)
                    anchor_tokens = _specific_tokens(_token_set_from_text(h_q))
                    dep = _safe_deposit_search(
                        diagnostics=selection_warnings,
                        context=heading_text or h_q,
                        query=h_q,
                        count=1,
                        plan_only=False,
                        strict_tokens=anchor_tokens,
                    )
                    if dep:
                        external.append(dep[0])

                files = files + external[:need]
            else:
                # No headings (or plan_only preview) — batch mode
                dep_q = _enrich_query_for_theme(base_q, post_context, content_filter, source="deposit")
                anchor_tokens = _primary_post_tokens(post_context)
                dep_files = _safe_deposit_search(
                    diagnostics=selection_warnings,
                    context=dep_q,
                    query=dep_q,
                    count=need,
                    plan_only=plan_only,
                    strict_tokens=anchor_tokens,
                )
                files = files + dep_files

        return {
            "source": "auto",
            "query": base_query,
            "content_filter": content_filter,
            "files": files,
            "warnings": selection_warnings,
        }

    if source == "semantic":
        files, heading_assignments = _heading_specific_selection(
            post_context=post_context,
            content_filter=content_filter,
            limit=_count,
            allow_external=False,
        )
        if files:
            return {
                "source": "semantic",
                "query": location_query or "",
                "content_filter": content_filter,
                "files": files[:_count],
                "heading_assignments": {file: heading_assignments[file] for file in files[:_count] if file in heading_assignments},
            }
        files = _semantic_heading_files(
            post_context=post_context,
            content_filter=content_filter,
            limit=_count,
        )
        if len(files) < _count:
            generic_files = search_semantic_assets(
                location_query=location_query or "",
                count=_count,
                content_filter=content_filter,
                post_context=post_context,
            )
            generic_files = _filter_relevant_candidates(
                generic_files,
                post_context=post_context,
                heading_text="",
                anchor_text=location_query or "",
            )
            files = list(dict.fromkeys(files + generic_files))[:_count]
        return {
            "source": "semantic",
            "query": location_query or "",
            "content_filter": content_filter,
            "files": files,
        }

    if source == "vil":
        files = load_vil_images_from_index_for_post(
            count=count,
            name=name,
            post_context=post_context,
        )
        if not files:
            files = get_vil_images(count=count, name=name)
        return {
            "source": "vil",
            "query": name or "",
            "content_filter": None,
            "files": files,
        }

    if source == "deposit":
        deposit_warnings: list[str] = []
        numbered_headings = [
            heading for heading in (post_context.get("available_headings") or [])
            if re.match(r"^\s*\d{1,3}\s*[.\-):]", str(heading.get("text") or ""))
        ]
        if numbered_headings and not query and not location_query:
            previews: list[str] = []
            used_queries: list[str] = []
            query_specs: list[tuple[str, set[str]]] = []
            for heading in numbered_headings:
                heading_query = _heading_to_search_query(str(heading.get("text") or ""))
                strict_tokens = _specific_tokens(_token_set_from_text(heading_query))
                if not strict_tokens:
                    continue
                matched = _safe_deposit_search(
                    diagnostics=deposit_warnings,
                    context=heading_query,
                    query=heading_query,
                    count=1,
                    plan_only=True,
                    strict_tokens=strict_tokens,
                )
                if matched and matched[0] not in previews:
                    previews.append(matched[0])
                    used_queries.append(heading_query)
                    query_specs.append((heading_query, strict_tokens))
                if len(previews) == _count:
                    break
            if len(previews) != _count:
                previews = []
                used_queries = []
                query_specs = []
            if plan_only or not query_specs:
                files = previews
            else:
                files = []
                for heading_query, strict_tokens in query_specs:
                    matched = _safe_deposit_search(
                        diagnostics=deposit_warnings,
                        context=heading_query,
                        query=heading_query,
                        count=1,
                        plan_only=False,
                        strict_tokens=strict_tokens,
                    )
                    if matched and matched[0] not in files:
                        files.append(matched[0])
                if len(files) != _count:
                    files = []
                    used_queries = []
            return {
                "source": "deposit",
                "query": " | ".join(used_queries),
                "content_filter": None,
                "files": files,
                "warnings": deposit_warnings,
            }

        preferred_q = location_query or query or _primary_post_query(post_context)
        # A supplied query may lead a general thematic article, but never
        # override a named destination/product already present in the post.
        primary_tokens = _primary_post_tokens(post_context)
        strict_tokens = (
            primary_tokens
            if _has_hard_post_anchor(primary_tokens)
            else _specific_tokens(_token_set_from_text(preferred_q))
        )
        if not strict_tokens or not preferred_q:
            return {"source": "deposit", "query": "", "content_filter": None, "files": [], "warnings": deposit_warnings}
        enriched_q = _enrich_query_for_theme(preferred_q, post_context, content_filter)
        files = _safe_deposit_search(
            diagnostics=deposit_warnings,
            context=enriched_q,
            query=enriched_q,
            count=_count,
            plan_only=plan_only,
            strict_tokens=strict_tokens,
        )
        return {
            "source": "deposit",
            "query": enriched_q if len(files) == _count else "",
            "content_filter": None,
            "files": files if len(files) == _count else [],
            "warnings": deposit_warnings,
        }

    if source == "wikimedia":
        from src.pictova.providers import wikimedia as wikimedia_provider

        wikimedia_warnings: list[str] = []
        preferred_q = location_query or query or _primary_post_query(post_context)
        anchor_tokens = _specific_tokens(_token_set_from_text(preferred_q))
        if not preferred_q or not anchor_tokens:
            return {"source": "wikimedia", "query": "", "content_filter": None, "files": [], "warnings": wikimedia_warnings}
        # A provider outage degrades this selection the same way it degrades
        # DepositPhotos: an empty exact result, never an aborted command.
        try:
            results = wikimedia_provider.search(preferred_q, count=max(_count * 4, 20))
            exact_results = [
                result for result in results
                if _matching_anchor_count(
                    _token_set_from_text(result.get("title", "")), anchor_tokens,
                ) >= min(2, len(anchor_tokens))
            ]
            if len(exact_results) < _count:
                return {"source": "wikimedia", "query": "", "content_filter": None, "files": [], "warnings": wikimedia_warnings}
            if plan_only:
                files = [result["url"] for result in exact_results[:_count]]
            else:
                files = [wikimedia_provider.download(result) for result in exact_results[:_count]]
        except Exception as exc:
            return {
                "source": "wikimedia",
                "query": "",
                "content_filter": None,
                "files": [],
                "warnings": [
                    f"Wikimedia exact retrieval failed for {preferred_q!r} "
                    f"({type(exc).__name__}); no generic fallback was used"
                ],
            }
        return {
            "source": "wikimedia",
            "query": preferred_q,
            "content_filter": None,
            "files": files,
            "warnings": wikimedia_warnings,
        }

    if source == "local":
        # Direct file paths list — split query by "," or "\n" delimiter
        raw = query or ""
        paths = [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]
        # Also pick up "files" from post_context if present
        extra = post_context.get("files") or []
        if isinstance(extra, list):
            paths = paths + [str(f) for f in extra]
        paths = paths[:_count]
        return {"source": "local", "query": raw, "content_filter": None, "files": paths}

    if source == "unsplash":
        loc_q = location_query or query or _extract_location(post_context)
        enriched_q = _enrich_query_for_theme(loc_q, post_context, content_filter, source="unsplash")
        files = _unsplash_search_download(query=enriched_q, count=_count)
        return {"source": "unsplash", "query": enriched_q, "content_filter": None, "files": files}

    raise ValueError(f"Unsupported source: {source}")


_THEME_NIGHT_KEYWORDS = {
    "gece hayatı", "nightlife", "gece kulübü", "bar ", "barlar", "eğlence",
    "party", "club ", "disco", "meyhane", "taverna", "pub ",
}
_THEME_NATURE_KEYWORDS = {
    "doğa", "yayla", "orman", "dağ", "kanyonu", "şelale", "vadisi",
    "nature", "forest", "mountain", "canyon", "waterfall",
}
_THEME_BEACH_KEYWORDS = {
    "plaj", "koy", "deniz", "sahil", "beach", "bay", "coast",
}

_NOISY_METADATA_TOKENS = {
    "advert", "advertisement", "banner", "brochure", "document", "flyer",
    "logo", "menu", "poster", "promo", "promotional", "reklam", "screenshot",
    "sign", "street sign", "food", "dish", "restaurant", "interior",
    "presentation", "tabela", "tableware", "dish", "chair", "room",
}
_GENERIC_SEMANTIC_ANCHORS = {
    "waterfall", "selale", "şelale", "beach", "plaj", "bay", "koy",
    "island", "ada", "castle", "kale", "coast", "sahil", "harbor",
    "liman", "museum", "muze", "nature", "landscape", "manzara",
}

_NON_SPECIFIC_MATCH_TOKENS = GENERIC_ANCHORS | _GENERIC_SEMANTIC_ANCHORS | {
    "beautiful", "guide", "how", "landscapes", "mountain", "mountains",
    "national", "park", "parks", "panorama", "panoramic", "place", "places",
    "rehber", "rehberi", "selaleleri", "waterfalls", "scenic", "sunset",
    "where", "visit",
    "bilmeniz", "gerekenler", "gitmeden", "giris", "ucreti", "nasil", "nerede",
    "adasi", "golu", "kalesi", "koyu", "magarasi", "milli", "ormani", "parki",
    "plaji", "sahili", "vadisi", "yaylasi", "gezilecek", "yerler", "ok",
}
_THEMATIC_POST_TOKENS = {
    "yalniz", "seyahat", "gezi", "rehber", "rehberi", "tatil", "rota",
    "rotasi", "ipuclari", "deneyim", "deneyimler", "uygulama", "uygulamasi",
    "app", "apps",
}
_TITLE_VERB_TOKENS = {
    "etmek", "olmak", "yapmak", "hissetmek", "bilmek", "vermek", "almak",
    "gercek", "gercekten", "kendi", "daha", "gibi", "bir",
}

_TURKISH_ASCII = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u"})

def _canonical_token(value: object) -> str:
    # Lowercasing U+0130 can leave a combining dot that normalize_text drops
    # together with the leading letter ("İstanbul" -> "stanbul").
    text = str(value or "").replace("İ", "I")
    return normalize_text(text).translate(_TURKISH_ASCII)


def _token_set_from_text(*values: object) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        text = _canonical_token(value)
        for token in re.findall(r"[a-z0-9çğıöşü]+", text):
            if len(token) < 3:
                continue
            if token in BAD_METADATA_TOKENS:
                continue
            tokens.add(token)
    return tokens


def _specific_tokens(tokens: set[str]) -> set[str]:
    return {token for token in tokens if token not in _NON_SPECIFIC_MATCH_TOKENS}


def _primary_post_tokens(post_context: Dict[str, Any]) -> set[str]:
    """Return only the post title/slug entity anchors; body links cannot widen them."""
    return _specific_tokens(_token_set_from_text(
        post_context.get("title", ""),
        post_context.get("slug", ""),
    ))


def _has_hard_post_anchor(tokens: set[str]) -> bool:
    """A named destination or product must not be overridden by a loose query."""
    return any(token not in _THEMATIC_POST_TOKENS | _TITLE_VERB_TOKENS for token in tokens)


def _primary_post_query(post_context: Dict[str, Any]) -> str:
    primary_tokens = _primary_post_tokens(post_context)
    if not _has_hard_post_anchor(primary_tokens):
        thematic_tokens = _token_set_from_text(
            post_context.get("title", ""),
            post_context.get("slug", ""),
        ) & _THEMATIC_POST_TOKENS
        for value in (post_context.get("slug", ""), post_context.get("title", "")):
            ordered = [
                token for token in re.findall(r"[a-z0-9]+", _canonical_token(value))
                if token in thematic_tokens
            ]
            if ordered:
                return " ".join(dict.fromkeys(ordered))
    for value in (post_context.get("slug", ""), post_context.get("title", "")):
        ordered = [
            token for token in re.findall(r"[a-z0-9]+", _canonical_token(value))
            if token in primary_tokens
        ]
        if ordered:
            return " ".join(dict.fromkeys(ordered))
    return ""


def _context_anchor_tokens(
    post_context: Dict[str, Any],
    *,
    heading_text: str = "",
    anchor_text: str = "",
) -> set[str]:
    return _specific_tokens(_token_set_from_text(
        heading_text,
        anchor_text,
        post_context.get("title", ""),
        post_context.get("slug", ""),
        _extract_location(post_context),
    ))


def _specific_anchor_text(value: str) -> str:
    token = normalize_text(value)
    if not token or token in _GENERIC_SEMANTIC_ANCHORS:
        return ""
    return value


def _candidate_tokens_from_row(row: Dict[str, Any]) -> set[str]:
    blob = " ".join(
        str(row.get(field) or "")
        for field in (
            "title",
            "location",
            "city",
            "state_province",
            "country",
            "scene",
            "activity",
            "summary",
            "description",
            "ai_keywords_json",
            "apple_labels_json",
        )
    ).lower()
    blob = re.sub(r"\s+", " ", blob)
    if any(token in blob for token in _NOISY_METADATA_TOKENS):
        return set()
    return _token_set_from_text(blob)


def _deposit_result_tokens(result: Dict[str, Any]) -> set[str]:
    """Return title tokens only; provider tags may rank but cannot approve an asset."""
    return _specific_tokens(_token_set_from_text(result.get("title", "")))


def _matching_anchor_count(candidate_tokens: set[str], anchor_tokens: set[str]) -> int:
    """Count anchors the candidate matches literally or by shared word stem.

    A hand-written TR/EN equivalence table used to sit here. It only ever knew
    the vocabulary of the articles someone had already published, so it is gone;
    cross-language matching belongs to the semantic layer.
    """
    candidate_tokens = _specific_tokens(candidate_tokens)
    anchor_tokens = _specific_tokens(anchor_tokens)
    if not candidate_tokens or not anchor_tokens:
        return 0
    return _literal_matching_anchor_count(candidate_tokens, anchor_tokens)


def _literal_matching_anchor_count(candidate_tokens: set[str], anchor_tokens: set[str]) -> int:
    candidate_tokens = _specific_tokens(candidate_tokens)
    anchor_tokens = _specific_tokens(anchor_tokens)
    matched_anchors = set()
    for candidate in candidate_tokens:
        for anchor in anchor_tokens:
            if candidate == anchor:
                matched_anchors.add(anchor)
                continue
            shorter, longer = sorted((candidate, anchor), key=len)
            if len(shorter) >= 6 and len(longer) - len(shorter) <= 3 and longer.startswith(shorter):
                matched_anchors.add(anchor)
    return len(matched_anchors)


def _matches_anchor_tokens(candidate_tokens: set[str], anchor_tokens: set[str]) -> bool:
    return _matching_anchor_count(candidate_tokens, anchor_tokens) >= 1


def _filter_relevant_candidates(
    candidates: list[str],
    *,
    post_context: Dict[str, Any],
    heading_text: str = "",
    anchor_text: str = "",
) -> list[str]:
    anchor_tokens = _context_anchor_tokens(post_context, heading_text=heading_text, anchor_text=anchor_text)
    if not anchor_tokens:
        return []
    filtered: list[str] = []
    for candidate in candidates:
        if _candidate_matches_heading(
            candidate,
            heading_text=heading_text,
            post_context=post_context,
            anchor_text=anchor_text,
        ):
            filtered.append(candidate)
    return list(dict.fromkeys(filtered))


def _candidate_metadata_row(candidate: str) -> Dict[str, Any] | None:
    db_path = get_visual_memory_db_path()
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            if candidate.startswith("icloud://"):
                source_id = candidate.removeprefix("icloud://")
                row = conn.execute(
                    """
                    SELECT source_id, source_path, title, location, city, state_province,
                           country, scene, activity, summary, description,
                           ai_keywords_json, apple_labels_json
                    FROM asset_index
                    WHERE source_id = ?
                    LIMIT 1
                    """,
                    (source_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT source_id, source_path, title, location, city, state_province,
                           country, scene, activity, summary, description,
                           ai_keywords_json, apple_labels_json
                    FROM asset_index
                    WHERE source_path = ?
                    LIMIT 1
                    """,
                    (candidate,),
                ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    except Exception:
        return None


def _candidate_matches_heading(
    candidate: str,
    heading_text: str,
    post_context: Dict[str, Any] | None = None,
    anchor_text: str = "",
    required_tokens: set[str] | None = None,
) -> bool:
    row = _candidate_metadata_row(candidate)
    if not row:
        return False
    anchor_tokens = _context_anchor_tokens(
        post_context or {},
        heading_text=heading_text,
        anchor_text=anchor_text,
    )
    if not anchor_tokens:
        return False
    candidate_tokens = _candidate_tokens_from_row(row)
    if required_tokens:
        # A numbered H3 may be an app or a named location. One incidental
        # token ("Field" in a landscape) is never enough to represent
        # "Field Trip" the app.
        if not required_tokens <= candidate_tokens:
            return False
    return _matches_anchor_tokens(candidate_tokens, anchor_tokens)


def _numbered_entity_text(heading: Dict[str, Any]) -> str:
    """Return the named entity of a numbered list heading.

    The level is deliberately not checked. Plenty of published guides number
    their list items as H2 rather than H3, and requiring H3 left those posts
    with no entity contract at all — every heading then fell back to a loose
    prose query.
    """
    text = str(heading.get("text") or "")
    if not re.match(r"^\s*\d{1,3}\s*[.\-):]", text):
        return ""
    entity_text = re.sub(r"^\s*\d{1,3}\s*[.\-):]\s*", "", text)
    # List headings often use `Name - editorial explanation`. The explanation
    # is prose, not part of the entity contract; requiring it made exact
    # provider matches such as "Ohrid Lake" impossible.
    return re.split(r"\s+(?:[-—–:])\s+", entity_text, maxsplit=1)[0].strip()


def _numbered_entity_tokens(heading: Dict[str, Any]) -> set[str]:
    """Return the full entity contract for a numbered list item."""
    return _specific_tokens(_token_set_from_text(_numbered_entity_text(heading)))


_ENTITY_PROVIDER_TOKEN_MAP = {
    "antik": "ancient",
    "tiyatro": "theater",
    "kilisesi": "church",
    "camii": "mosque",
    "manastiri": "monastery",
}


def _numbered_provider_tokens(heading: Dict[str, Any]) -> set[str]:
    """Translate only concrete entity words for provider-title verification."""
    tokens = _numbered_entity_tokens(heading)
    return {_ENTITY_PROVIDER_TOKEN_MAP.get(token, token) for token in tokens}


def _heading_specific_selection(
    *,
    post_context: Dict[str, Any],
    content_filter: str | None,
    limit: int,
    allow_external: bool,
    plan_only: bool = False,
    diagnostics: list[str] | None = None,
) -> tuple[list[str], dict[str, Dict[str, Any]]]:
    available_headings = post_context.get("available_headings") or []
    if not available_headings:
        return [], {}

    # Existing images belong to their nearest heading. When a post already has
    # a Pictova (or editor) image there, fill another concrete heading first
    # rather than spending a download on the same section again.
    occupied = {
        (
            re.sub(r"\s+", " ", str(item.get("text") or "")).strip().casefold(),
            int(item.get("level") or 0),
        )
        for item in (post_context.get("occupied_headings") or [])
        if str(item.get("text") or "").strip()
    }
    if occupied:
        available_headings = [
            heading for heading in available_headings
            if (
                re.sub(r"\s+", " ", str(heading.get("text") or "")).strip().casefold(),
                int(heading.get("level") or 0),
            ) not in occupied
        ]
    if not available_headings:
        return [], {}

    # A numbered list item is the content's concrete unit (places, apps,
    # activities…); a lead-in question heading is an introduction, not a visual
    # subject. Published posts show the difference plainly — a numbered heading
    # carries an image roughly 70% of the time, a plain H2 under 20% — so the
    # order comes from that measurement rather than a hardcoded level test.
    # The old rule only recognised numbered H3s and therefore treated a post
    # whose list items are numbered H2s as if it had no concrete subjects.
    ranked_headings = rank_headings(available_headings)
    has_priority_targets = any(is_placement_target(heading) for heading in available_headings)
    available_headings = ranked_headings

    files: list[str] = []
    assignments: dict[str, Dict[str, Any]] = {}
    post_location = _turkify_to_english_query(_extract_location(post_context))
    # A numbered list has more concrete subjects than the requested count, and
    # some of them will not match. Probe further down the list before accepting
    # a partial batch, but never broaden into a generic fallback image.
    record_limit = max(limit * 2, 10) if has_priority_targets else limit
    records: list[dict[str, Any]] = []
    for heading in available_headings:
        if len(records) >= record_limit:
            break

        heading_text = str(heading.get("text", "") or "").strip()
        if not heading_text:
            continue
        semantic_query = _heading_to_semantic_query(heading_text, post_location=post_location)
        if not semantic_query:
            continue

        chosen = None
        semantic_anchor = _specific_anchor_text(semantic_query)
        entity_tokens = _numbered_entity_tokens(heading)
        provider_entity_tokens = _numbered_provider_tokens(heading)
        candidates = search_semantic_assets(
            location_query=semantic_query,
            count=max(limit * 3, 10),
            content_filter=content_filter,
            post_context=post_context,
            include_icloud=True,
        )
        for candidate in candidates:
            if _candidate_matches_heading(
                candidate,
                heading_text=heading_text,
                post_context=post_context,
                anchor_text=semantic_anchor,
                required_tokens=entity_tokens or None,
            ):
                chosen = candidate
                break

        external_spec = None
        if not chosen and allow_external:
            if entity_tokens:
                # Do not contaminate a named entity query with article prose
                # such as "kendinizi yerli gibi". A numbered list item already
                # names its own place, so appending the post location only
                # pushed real words out of the five-word query budget.
                entity_text = _numbered_entity_text(heading) or heading_text
                search_query = _heading_to_search_query(entity_text)
                anchor_tokens = provider_entity_tokens
            else:
                search_query = _heading_to_search_query(heading_text, post_location=post_location)
                anchor_tokens = _context_anchor_tokens(
                    post_context,
                    heading_text=heading_text,
                    anchor_text=semantic_anchor,
                )
            external_spec = (search_query, anchor_tokens)

        heading_contract = dict(heading)
        if entity_tokens:
            # Preserve the selector's concrete entity contract through media
            # processing. A later vision response that only says "a phone"
            # must not erase the exact app/place match that justified this
            # source candidate.
            heading_contract["required_heading_tokens"] = sorted(entity_tokens)
        records.append({
            "heading": heading_contract,
            "chosen": chosen,
            "external_spec": external_spec,
        })

    # Previewing four independent headings must not wait for four serial
    # provider round-trips. Actual licensed downloads are deliberately serial:
    # four XL transfers in parallel saturate a personal hotspot and turn a
    # recoverable partial transfer into four stalled ones.
    external_results: dict[int, str | None] = {}
    external_failures: dict[int, str] = {}
    pending = [
        (index, record["external_spec"])
        for index, record in enumerate(records)
        if record["chosen"] is None and record["external_spec"]
    ]

    def fetch_external(spec: tuple[str, set[str] | None]) -> str | None:
        query, strict_tokens = spec
        return next(
            iter(_deposit_search_download(
                query=query,
                count=1,
                plan_only=plan_only,
                strict_tokens=strict_tokens,
            )),
            None,
        )

    if pending and plan_only:
        with ThreadPoolExecutor(max_workers=min(4, len(pending))) as pool:
            futures = {
                index: pool.submit(fetch_external, spec)
                for index, spec in pending
            }
            for index, _spec in pending:
                try:
                    external_results[index] = futures[index].result()
                except Exception as exc:
                    external_results[index] = None
                    external_failures[index] = type(exc).__name__
    elif pending:
        for index, spec in pending:
            try:
                external_results[index] = fetch_external(spec)
            except Exception as exc:
                external_results[index] = None
                external_failures[index] = type(exc).__name__

    if diagnostics is not None:
        for index, error_type in external_failures.items():
            heading_text = str(records[index]["heading"].get("text") or "başlık")
            diagnostics.append(
                f"DepositPhotos exact retrieval failed for {heading_text!r} "
                f"({error_type}); no generic fallback was used"
            )

    unmatched: list[str] = []
    for index, record in enumerate(records):
        chosen = record["chosen"] or external_results.get(index)
        if chosen and chosen not in assignments:
            files.append(chosen)
            assignments[chosen] = record["heading"]
        elif not chosen and index not in external_failures:
            # No provider error, simply nothing that met the exact contract.
            # Without this line a fail-closed run reported zero images and gave
            # no reason at all, which is indistinguishable from a broken run.
            spec = record.get("external_spec")
            query = spec[0] if spec else ""
            unmatched.append(
                f"{str(record['heading'].get('text') or 'başlık')!r}"
                + (f" (sorgu: {query!r})" if query else "")
            )

    if diagnostics is not None and unmatched:
        prefix = (
            "Hiçbir başlık için tam eşleşen görsel bulunamadı"
            if not files
            else f"{len(files)} başlık eşleşti, {len(unmatched)} başlık boş kaldı"
        )
        diagnostics.append(
            f"{prefix}; eşleşmeyen: " + ", ".join(unmatched[:5])
        )

    deduped_files = list(dict.fromkeys(files))
    return deduped_files, {
        file: assignments[file]
        for file in deduped_files
        if file in assignments
    }


def _heading_specific_files(
    *,
    post_context: Dict[str, Any],
    content_filter: str | None,
    limit: int,
    allow_external: bool,
    plan_only: bool = False,
) -> list[str]:
    """Compatibility wrapper for callers that only need candidate paths."""
    files, _assignments = _heading_specific_selection(
        post_context=post_context,
        content_filter=content_filter,
        limit=limit,
        allow_external=allow_external,
        plan_only=plan_only,
    )
    return files


def _heading_to_search_query(heading_text: str, post_location: str = "") -> str:
    """Convert a Turkish blog heading into an English DepositPhotos search query.

    Generated by Qwen2.5-Coder-14B, fixed for multi-word phrases + diacritics.
    """
    import re
    import unicodedata

    def _norm(s: str) -> str:
        s = s.replace("ı", "i").replace("I", "I")  # dotless-i doesn't decompose via NFKD
        return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()

    # Normalize curly/smart quotes to ASCII apostrophe
    heading_text = heading_text.replace("‘", "'").replace("’", "'").replace("‚", "'")
    # Strip leading number patterns: "3. ", "10- ", "1) "
    text = re.sub(r"^\d+[\.\-\)]\s*", "", heading_text.strip())
    # Extract destination from "X'den/tan/dan Y'a/ya/na Kaçış" pattern
    m_dest = re.search(r"'?\w+'?(?:den|dan|tan|ten)\s+(.+?)'?(?:ya|na|a)\s+[KkGg]", text)
    if m_dest:
        text = m_dest.group(1).strip()
    # Split an editorial suffix (`Name - why it matters`) and keep only the
    # visual entity. A plain hyphen is common in WordPress H3s, alongside en
    # and em dashes; require surrounding spaces so compound place names remain
    # intact.
    text = re.split(r"\s+(?:[—–-]|:)\s+", text, maxsplit=1)[0].strip()
    # Remove emoji, parentheticals and editorial markers
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    text = re.sub(r"\s*\([^)]*\)", "", text)
    text = re.sub(r"\[[^\]]*\]", " ", text)
    # A list heading names a place and its district ("Şirince, Selçuk"). The
    # comma is punctuation, not part of either name, and a provider search
    # never matches it.
    text = re.sub(r"[,;/]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Multi-word phrase replacements (must run before word-level)
    PHRASES = [
        ("antik kenti", "ancient ruins"), ("antik kent", "ancient ruins"),
        ("milli parki", "national park"), ("milli park", "national park"),
        ("kaplicalari", "hot springs"), ("kaplica", "hot springs"),
    ]
    norm_text = _norm(text)
    for tr_phrase, en_phrase in PHRASES:
        if tr_phrase in norm_text:
            # Replace case-insensitively in original text
            text = re.sub(re.escape(tr_phrase), en_phrase, text, flags=re.IGNORECASE)
            norm_text = _norm(text)

    # Word-level translations
    WORD_MAP = {
        "antik": "ancient", "tiyatro": "theater",
        "plaji": "beach", "plaj": "beach",
        "golu": "lake", "gol": "lake",
        "selalesi": "waterfall", "selale": "waterfall",
        "kalesi": "castle", "kale": "castle",
        "kilisesi": "church", "kilise": "church",
        "camii": "mosque", "cami": "mosque",
        "vadisi": "valley", "vadi": "valley",
        "ormani": "forest", "orman": "forest",
        "yaylasi": "plateau", "yayla": "plateau",
        "koyu": "bay", "koy": "bay",
        "limani": "harbor", "liman": "harbor",
        "adasi": "island", "ada": "island",
        "magarasi": "cave", "magara": "cave",
        "sahili": "coast", "sahil": "coast",
        "tepesi": "hill", "tepe": "hill",
        "nehri": "river", "nehir": "river",
    }
    words = text.split()
    result = []
    for w in words:
        mapped = WORD_MAP.get(_norm(w))
        result.append(mapped if mapped else w)

    query = " ".join(result).strip()

    # The post itself is the only source of geography. A hardcoded country
    # guess used to relocate every destination it did not know about — Ohrid
    # into Turkey, Kosovo into Greece — and each fix only added another
    # special case.
    if post_location and _norm(post_location) not in _norm(query):
        query = f"{query} {post_location}"

    # Final pass: catch any remaining Turkish words via the slug translator
    query = _turkify_to_english_query(query)
    return " ".join(query.split()[:5])


def _heading_to_semantic_query(heading_text: str, post_location: str = "") -> str:
    """Convert a heading into a compact local semantic-search query.

    The local index is Turkish, so the leading English geography word is
    translated back. A country name no longer has to be filtered out here:
    nothing appends one any more.
    """
    query = _heading_to_search_query(heading_text, post_location=post_location)
    tokens = [token for token in re.split(r"\s+", query) if token]
    if not tokens:
        return ""
    first = tokens[0].strip()
    if not first:
        return ""
    return {
        "harbor": "liman",
        "beach": "plaj",
        "bay": "koy",
        "island": "ada",
        "castle": "kale",
        "coast": "sahil",
        "waterfall": "selale",
        "museum": "muze",
    }.get(first.lower(), first)


def _semantic_heading_files(
    *,
    post_context: Dict[str, Any],
    content_filter: str | None,
    limit: int,
) -> list[str]:
    available_headings = post_context.get("available_headings") or []
    if not available_headings:
        return []

    files: list[str] = []
    post_location = _turkify_to_english_query(_extract_location(post_context))
    for heading in available_headings[:limit]:
        heading_text = str(heading.get("text", "") or "").strip()
        h_q = _heading_to_semantic_query(heading_text, post_location=post_location)
        if not h_q:
            continue
        semantic_anchor = _specific_anchor_text(h_q)
        candidates = search_semantic_assets(
            location_query=h_q,
            count=1,
            content_filter=content_filter,
            post_context=post_context,
        )
        for candidate in candidates:
            if candidate not in files and _candidate_matches_heading(
                candidate,
                heading_text=heading_text,
                post_context=post_context,
                anchor_text=semantic_anchor,
            ):
                files.append(candidate)
                break
    return files


def _turkify_to_english_query(location_query: str) -> str:
    """Translate the generic Turkish words in a slug/title into English.

    Only common nouns are translated (``plaj`` → ``beach``). Place names pass
    through untouched: a proper-noun table can only ever cover the destinations
    someone remembered to add, and the country fallback that accompanied it
    silently moved unknown places into the wrong country.
    """
    import unicodedata

    def _norm(w: str) -> str:
        w = w.replace("ı", "i")  # dotless-i doesn't decompose via NFKD
        return unicodedata.normalize("NFKD", w).encode("ascii", "ignore").decode().lower()

    TR_STOP = {
        "nerede", "nasil", "gidilir", "gezilecek", "yerler", "yerleri", "rehberi",
        "rota", "rotasi", "rotalari", "seyahat", "tatil", "gezi", "bilmeniz",
        "gerekenler", "once", "hakkinda", "ile", "icin", "ve", "bir", "en",
        "iyi", "ucuz", "guncel", "detayli", "travel", "guide", "the", "and",
        "notlari", "notlar", "deneyimler", "kisisel", "kent", "kenti",
        "islemleri", "işlemleri", "esnek", "bilet", "kurallari", "kuralları",
        "kurallar", "adasi", "adasi", "adası", "adalari", "adaları", "yakin",
        "yakın", "yunan", "yaz", "tatilinde", "kacabileceginiz",
        "kaçabileceğiniz", "kaçabileceginiz",
    }
    TR_GEO = {
        "deniz": "sea", "dag": "mountain", "dagi": "mountain",
        "koy": "bay", "koyu": "bay",
        "sehir": "city",
        "kale": "castle", "kalesi": "castle",
        "plaj": "beach", "plaji": "beach", "sahil": "coast", "sahili": "coast",
        "orman": "forest", "ormani": "forest", "ormanlari": "forest",
        "gol": "lake", "golu": "lake",
        "nehir": "river", "nehri": "river",
        "vadi": "valley", "vadisi": "valley",
        "yayla": "plateau", "yaylasi": "plateau",
        "selale": "waterfall", "selalesi": "waterfall",
        "mezar": "tombs", "mezarlari": "tombs", "mezarligi": "cemetery",
        "muze": "museum", "muzesi": "museum",
        "antik": "ancient",
        "kaya": "rock",
        "tepe": "hill", "tepesi": "hill",
        "ada": "island", "adasi": "island",
        "liman": "harbor", "limani": "harbor",
        "magara": "cave", "magarasi": "cave",
        "ornek": "",
    }
    result = []
    for w in location_query.split():
        norm = _norm(w)
        if norm in TR_STOP:
            continue
        if norm in TR_GEO and TR_GEO[norm]:
            result.append(TR_GEO[norm])
        else:
            # A place name keeps its own spelling; the provider indexes it too.
            result.append(w)

    return " ".join(result[:4])


def _enrich_query_for_theme(
    query: str,
    post_context: Dict[str, Any],
    content_filter: str | None,
    *,
    source: str = "deposit",
) -> str:
    """Append a modifier to the query based on the post theme.

    source='unsplash': atmospheric modifier (sunset/evening/landscape)
    source='deposit' : specific modifier (night/coast/landscape)
    """
    # Deposit needs English queries — translate Turkish slug tokens first
    if source == "deposit":
        query = _turkify_to_english_query(query)

    text = " ".join([
        query.lower(),
        str(post_context.get("title") or "").lower(),
        str(post_context.get("slug") or "").lower(),
        str(content_filter or "").lower(),
    ])

    if any(kw in text for kw in _THEME_NIGHT_KEYWORDS):
        if source == "unsplash":
            if "sunset" not in query and "evening" not in query:
                return query + " sunset"
        else:
            if "night" not in query and "gece" not in query:
                return query + " night"
    elif any(kw in text for kw in _THEME_NATURE_KEYWORDS):
        if "landscape" not in query and "nature" not in query:
            return query + " landscape"
    elif any(kw in text for kw in _THEME_BEACH_KEYWORDS):
        if "beach" not in query and "coast" not in query:
            return query + " coast"

    return query


def _deposit_search_download(
    query: str,
    count: int,
    plan_only: bool = False,
    *,
    strict_tokens: set[str] | None = None,
) -> list[str]:
    """Search + download exact DepositPhotos candidates.

    plan_only=True: search only (free, no credits), returns preview URLs.
    plan_only=False: search + download (credits charged), returns local paths.

    An empty result means no exact candidate met the semantic contract. A
    transfer failure raises so the attach receipt can distinguish a provider
    problem from a legitimate fail-closed selection.
    """
    try:
        from src.pictova.providers import deposit as deposit_provider

        cache_key = (query, max(count * 4, 20))
        results = _DEPOSIT_DISCOVERY_CACHE.get(cache_key)
        if results is None:
            results = _load_deposit_discovery(cache_key)
        if results is None:
            results = deposit_provider.search(query=query, count=max(count * 4, 20))
            _save_deposit_discovery(cache_key, results)
        _DEPOSIT_DISCOVERY_CACHE[cache_key] = results
        if strict_tokens is not None:
            query_tokens = _specific_tokens(_token_set_from_text(query))
            required_query_matches = min(2, len(query_tokens))
            filtered = [
                r for r in results
                if _matches_anchor_tokens(_deposit_result_tokens(r), strict_tokens)
                and _literal_matching_anchor_count(_deposit_result_tokens(r), query_tokens) >= required_query_matches
            ]
            results = filtered
        if len(results) < count:
            return []

        if plan_only:
            selected = results[:count]
            return [r["preview_url"] for r in selected if r.get("preview_url")]

        session_id = deposit_provider._login()
        paths: list[str] = []
        download_failures: list[str] = []
        # Each failed licensed transfer can consume scarce hotspot bandwidth
        # (and may consume a provider credit). Two exact candidates per slot
        # are enough to recover from a transient CDN stall without scanning
        # the whole search page.
        attempt_limit = min(len(results), max(count + 1, count * 2))
        # A licensed asset CDN can occasionally stall even though search and
        # licensing succeeded. Keep the exact-query filter, but advance to the
        # next exact candidate instead of aborting the whole post batch.
        for result in results[:attempt_limit]:
            try:
                path = deposit_provider.download(result["id"], session_id)
            except Exception as exc:
                download_failures.append(
                    f"{result.get('id', 'unknown')}:{type(exc).__name__}"
                )
                continue
            if path and path not in paths:
                paths.append(path)
            elif not path:
                download_failures.append(f"{result.get('id', 'unknown')}:empty-result")
            if len(paths) == count:
                break
        if len(paths) != count:
            detail = ", ".join(download_failures) or "no downloadable exact candidate"
            raise RuntimeError(
                "DepositPhotos exact download incomplete "
                f"({len(paths)}/{count}; attempted {attempt_limit}; {detail})"
            )
        return paths
    except Exception as e:
        raise RuntimeError(f"DepositPhotos failed for query {query!r}: {e}") from e


def _safe_deposit_search(
    *,
    diagnostics: list[str] | None,
    context: str,
    **kwargs: Any,
) -> list[str]:
    """Degrade the selection on a provider outage instead of aborting.

    `_heading_specific_selection` already records the failure and continues.
    The batch paths used to let the same RuntimeError escape, so a DepositPhotos
    outage turned `plan` and `process` into raw tracebacks rather than the
    structured fail-closed result every other command returns.
    """
    try:
        return _deposit_search_download(**kwargs)
    except Exception as exc:
        if diagnostics is not None:
            diagnostics.append(
                f"DepositPhotos exact retrieval failed for {context!r} "
                f"({type(exc).__name__}); no generic fallback was used"
            )
        return []


def _unsplash_search_download(query: str, count: int) -> list[str]:
    """Search + download from Unsplash. Returns an empty list on error."""
    try:
        from yo_unsplash import YOUnsplashDownloader
        d = YOUnsplashDownloader()
        # Quality filter: min 3000px width, prefer likes>0
        results = d.search(query, count=count * 3)
        scored = []
        for r in results:
            w = r.get("width", 0)
            likes = r.get("likes", 0)
            if w < 3000:
                continue
            score = likes + (2 if w >= 5000 else 0)
            scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        best = [r for _, r in scored[:count]]
        if not best:
            return []
        # Download
        downloaded = []
        for i, r in enumerate(best, 1):
            try:
                import tempfile, requests as _req, pathlib as _pl
                from src.utils.config import env_str
                dl_url = r["links"]["download"]
                access_key = env_str("UNSPLASH_ACCESS_KEY", "") or ""
                resp = _req.get(dl_url, headers={"Authorization": f"Client-ID {access_key}"}, timeout=30)
                resp.raise_for_status()
                import re
                photographer = r.get("user", {}).get("name", "Unknown")
                photographer_safe = re.sub(r'[^a-zA-Z0-9]', '_', photographer)
                slug = query.split()[0].lower()
                dest = _pl.Path(tempfile.gettempdir()) / f"pictova_unsplash" / f"{slug}-{i}-by-{photographer_safe}.jpg"
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(resp.content)
                downloaded.append(str(dest))
            except Exception as e:
                print(f"  ⚠ Unsplash download error ({i}): {e}")
        return downloaded
    except Exception as e:
        print(f"  ⚠ Unsplash skipped: {e}")
        return []


def _extract_location(post_context: Dict[str, Any]) -> str:
    """Extract location token from the post slug/title.

    A draft title can carry an editorial marker such as ``[Penova]``. It is
    workflow bookkeeping, not geography, and it used to travel all the way into
    the provider query when the post had no slug yet.
    """
    slug = str(post_context.get("slug") or "").replace("-", " ")
    if slug.strip():
        return slug
    title = re.sub(r"\[[^\]]*\]", " ", str(post_context.get("title") or ""))
    return re.sub(r"\s+", " ", title).strip()


def _destination_index_uuids(query: str, count: int) -> list[str]:
    """Fetch the best UUIDs from the destination index JSON."""
    try:
        idx_path = get_visual_memory_db_path().parent / "destination_index.json"
        if not idx_path.exists():
            return []
        index = json.loads(idx_path.read_text(encoding="utf-8"))
        q_lower = query.lower()
        # Name match (prefix or contains)
        for dest_name, uuids in index.items():
            if q_lower in dest_name.lower() or dest_name.lower() in q_lower:
                return [f"icloud://{u}" for u in uuids[:count]]
    except Exception:
        pass
    return []


__all__ = ["load_vil_images_from_index_for_post", "resolve_source_images", "search_semantic_assets"]
