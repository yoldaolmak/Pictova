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

        # 3. External sources: 75-80% DepositPhotos, 20-25% Unsplash
        if len(files) < _count:
            need = _count - len(files)
            base_q = location_query or _extract_location(post_context)
            
            # Ratio calculation: 25% Unsplash (at least 1), the rest Deposit
            uns_target = max(1, int(need * 0.25)) if need >= 4 else (1 if need > 1 else 0)
            dep_target = need - uns_target

            dep_q = _enrich_query_for_theme(base_q, post_context, content_filter, source="deposit")
            uns_q = _enrich_query_for_theme(base_q, post_context, content_filter, source="unsplash")
            
            # Fetch Deposit first
            dep_files = _deposit_search_download(query=dep_q, count=dep_target, plan_only=plan_only) if dep_target > 0 else []
            
            # If Deposit fell short, hand the deficit to Unsplash
            missing_dep = dep_target - len(dep_files)
            if missing_dep > 0:
                uns_target += missing_dep
                
            # Fetch Unsplash
            uns_files = _unsplash_search_download(query=uns_q, count=uns_target) if uns_target > 0 else []
            
            # If Unsplash couldn't find any and Deposit wasn't short earlier, it's hard to retry Deposit since there's no offset.
            # So we merge the lists.
            # Interlace: To avoid consecutive results from the same source
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
