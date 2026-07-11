"""Selection helpers exposed from the canonical engine package."""

from __future__ import annotations

from typing import Any, Dict, List

import json
from src.core.processor import get_vil_images
from src.main import load_vil_images_from_index_for_post, search_semantic_assets
from src.pictova.config import get_visual_memory_db_path


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
        # 1. Local photos (semantic search)
        files = search_semantic_assets(
            location_query=location_query or _extract_location(post_context),
            count=_count,
            content_filter=content_filter,
            post_context=post_context,
        )
        if len(files) >= _count:
            return {"source": "semantic", "query": location_query or "", "content_filter": content_filter, "files": files}

        # 2. iCloud candidate photos — first destination index, then FTS fallback
        need = _count - len(files)
        loc_q = location_query or _extract_location(post_context)
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
            files = files + icloud_uuids[:need]

        # 3. External sources — heading-aware when headings exist, batch otherwise
        if len(files) < _count:
            need = _count - len(files)
            base_q = location_query or _extract_location(post_context)
            available_headings = post_context.get("available_headings") or []
            post_location = _extract_location(post_context)

            if available_headings and not plan_only:
                # Per-heading selection: 1 photo per heading, specific query per slot
                # headings to fill = the ones that don't yet have a local/icloud photo
                already_filled = len(files)
                target_headings = available_headings[already_filled: already_filled + need]
                if not target_headings:
                    target_headings = available_headings[:need]

                external = []
                for h in target_headings:
                    h_q = _heading_to_search_query(h.get("text", ""), post_location=post_location)
                    # Try DepositPhotos first (1 per heading)
                    dep = _deposit_search_download(query=h_q, count=1, plan_only=False)
                    if dep:
                        external.append(dep[0])
                        continue
                    # Fallback: Unsplash
                    uns = _unsplash_search_download(query=h_q, count=1)
                    if uns:
                        external.append(uns[0])
                    else:
                        # Last resort: base query from DP
                        fallback = _deposit_search_download(query=base_q + " Turkey", count=1, plan_only=False)
                        external.extend(fallback)

                files = files + external[:need]
            else:
                # No headings (or plan_only preview) — batch mode
                uns_target = max(1, int(need * 0.25)) if need >= 4 else (1 if need > 1 else 0)
                dep_target = need - uns_target

                dep_q = _enrich_query_for_theme(base_q, post_context, content_filter, source="deposit")
                uns_q = _enrich_query_for_theme(base_q, post_context, content_filter, source="unsplash")

                dep_files = _deposit_search_download(query=dep_q, count=dep_target, plan_only=plan_only) if dep_target > 0 else []
                missing_dep = dep_target - len(dep_files)
                if missing_dep > 0:
                    uns_target += missing_dep
                uns_files = _unsplash_search_download(query=uns_q, count=uns_target) if uns_target > 0 else []

                merged = []
                for d, u in zip(dep_files, uns_files):
                    merged += [d, u]
                merged += dep_files[len(uns_files):] + uns_files[len(dep_files):]
                files = files + merged

        return {"source": "auto", "query": location_query or "", "content_filter": content_filter, "files": files}

    if source == "semantic":
        files = search_semantic_assets(
            location_query=location_query or "",
            count=_count,
            content_filter=content_filter,
            post_context=post_context,
        )
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
        loc_q = location_query or query or _extract_location(post_context)
        enriched_q = _enrich_query_for_theme(loc_q, post_context, content_filter)
        files = _deposit_search_download(query=enriched_q, count=_count, plan_only=plan_only)
        return {"source": "deposit", "query": enriched_q, "content_filter": None, "files": files}

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


def _heading_to_search_query(heading_text: str, post_location: str = "") -> str:
    """Convert a Turkish blog heading into an English DepositPhotos search query.

    Generated by Qwen2.5-Coder-14B, fixed for multi-word phrases + diacritics.
    """
    import re
    import unicodedata

    def _norm(s: str) -> str:
        return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()

    # Strip leading number patterns: "3. ", "10- ", "1) "
    text = re.sub(r"^\d+[\.\-\)]\s*", "", heading_text.strip())
    # Split on em-dash / colon and keep only location part
    text = re.split(r"\s*[—–]\s*|\s*:\s*", text)[0].strip()
    # Remove emoji and parenthetical
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    text = re.sub(r"\s*\([^)]*\)", "", text)
    text = text.strip()

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
        "plaji": "beach", "plaj": "beach",
        "golu": "lake", "gol": "lake",
        "selalesi": "waterfall", "selale": "waterfall",
        "kalesi": "castle", "kale": "castle",
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

    if post_location and _norm(post_location) not in _norm(query):
        query = f"{query} {post_location}"

    if "Turkey" not in query and "turkey" not in query.lower() and len(query.split()) < 4:
        query += " Turkey"

    return " ".join(query.split()[:5])


def _turkify_to_english_query(location_query: str) -> str:
    """Convert a Turkish slug/title into an English DepositPhotos search query.

    Generated by Qwen2.5-Coder-14B, reviewed and extended for diacritics + proper nouns.
    """
    import unicodedata

    def _norm(w: str) -> str:
        return unicodedata.normalize("NFKD", w).encode("ascii", "ignore").decode().lower()

    TR_STOP = {
        "nerede", "nasil", "gidilir", "gezilecek", "yerler", "yerleri", "rehberi",
        "rota", "rotasi", "rotalari", "seyahat", "tatil", "gezi", "bilmeniz",
        "gerekenler", "once", "hakkinda", "ile", "icin", "ve", "bir", "en",
        "iyi", "ucuz", "guncel", "detayli", "travel", "guide", "the", "and",
        "notlari", "notlar", "deneyimler", "kisisel",
    }
    TR_GEO = {
        "deniz": "sea", "dag": "mountain", "koy": "bay", "sehir": "city",
        "kale": "castle", "plaj": "beach", "orman": "forest", "gol": "lake",
        "nehir": "river", "vadi": "valley", "yayla": "plateau", "ornek": "",
    }
    TR_PROPER = {
        "kapadokya": "Cappadocia", "istanbul": "Istanbul", "ankara": "Ankara",
        "izmir": "Izmir", "antalya": "Antalya", "bodrum": "Bodrum",
        "oludeniz": "Oludeniz", "goreme": "Goreme", "efes": "Ephesus",
        "pamukkale": "Pamukkale", "trabzon": "Trabzon", "sinop": "Sinop",
        "mugla": "Mugla", "fethiye": "Fethiye", "kas": "Kas",
    }

    words = location_query.split()
    result = []
    for w in words:
        norm = _norm(w)
        if norm in TR_STOP:
            continue
        if norm in TR_PROPER:
            result.append(TR_PROPER[norm])
        elif norm in TR_GEO and TR_GEO[norm]:
            result.append(TR_GEO[norm])
        else:
            result.append(w)

    if len(result) < 4 and "Turkey" not in result:
        result.append("Turkey")

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


def _deposit_search_download(query: str, count: int, plan_only: bool = False) -> list[str]:
    """Search + download from DepositPhotos. Returns an empty list on error.

    plan_only=True: search only (free, no credits), returns preview URLs.
    plan_only=False: search + download (credits charged), returns local paths.
    """
    try:
        if plan_only:
            from src.pictova.providers.deposit import search
            results = search(query=query, count=count)
            return [r["preview_url"] for r in results if r.get("preview_url")]
        from src.pictova.providers.deposit import search_and_download
        return search_and_download(query=query, count=count)
    except Exception as e:
        print(f"  ⚠ DepositPhotos skipped: {e}")
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
                dl_url = r["links"]["download"]
                import os
                access_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
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
    """Extract location token from the post slug/title."""
    slug = str(post_context.get("slug") or "").replace("-", " ")
    title = str(post_context.get("title") or "")
    return slug or title


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
