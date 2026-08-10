"""Thin API surface over the canonical VIL app jobs."""

from __future__ import annotations

from typing import Any, Dict

from src.pictova.app.health import run_health_check
from src.pictova.app.jobs import run_attach_job
from src.pictova.engine.attach import build_attach_plan, build_process_result, prepare_attach_request
from src.pictova.providers.wordpress import (
    fetch_post_context,
    guard_post_media,
    remove_post_media,
    refresh_post_captions as refresh_managed_post_captions,
    resolve_post_site,
)


def gallery_query(payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST /gallery — zengin fotoğraf galerisi araması."""
    from src.pictova.engine.gallery import gallery_search, gallery_stats
    query = str(payload.get("query", "")).strip()
    if not query:
        return {"status": "success", "stats": gallery_stats(), "results": []}
    results = gallery_search(
        query,
        count=int(payload.get("count", 10)),
        only_local=bool(payload.get("only_local", True)),
        only_scanned=bool(payload.get("only_scanned", False)),
        city=payload.get("city"),
    )
    return {"status": "success", "query": query, "count": len(results), "results": results}


def search_photos(payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST /search — lokasyon bazlı fotoğraf arama."""
    from src.main import search_semantic_assets
    query = str(payload.get("query", "")).strip()
    if not query:
        return {"status": "failed", "warning": "query gerekli"}
    count = int(payload.get("count", 5))
    include_icloud = bool(payload.get("include_icloud", False))
    content_filter = payload.get("content_filter")
    results = search_semantic_assets(
        location_query=query,
        count=count,
        content_filter=content_filter,
        include_icloud=include_icloud,
    )
    return {"status": "success", "query": query, "count": len(results), "results": results}


def review_post(payload: Dict[str, Any]) -> Dict[str, Any]:
    site = payload.get("site", "auto")
    post_id = payload.get("post_id")
    try:
        from src.main import search_semantic_assets
        if str(site).strip().lower() == "auto":
            site, ctx = resolve_post_site(int(post_id), site=site)
        else:
            ctx = fetch_post_context(int(post_id), site=site)
        slug = str(ctx.get("slug") or "").replace("-", " ")
        title = str(ctx.get("title") or "")
        query = slug or title
        candidates = []
        if query:
            candidates = search_semantic_assets(
                location_query=query,
                count=payload.get("count", 8),
                post_context=ctx,
            )
        return {
            "command": "review",
            "status": "success",
            "site": site,
            "post_context": ctx,
            "query": query,
            "photo_candidates": candidates,
            "candidate_count": len(candidates),
        }
    except Exception as exc:
        return {
            "command": "review",
            "status": "failed",
            "post_context": {},
            "warnings": [str(exc)],
        }


def guard_post(payload: Dict[str, Any]) -> Dict[str, Any]:
    post_id = payload.get("post_id")
    if not post_id:
        return {"command": "guard", "status": "failed", "warning": "post_id gerekli"}
    try:
        site, _ = resolve_post_site(int(post_id), site=payload.get("site", "auto"))
        return guard_post_media(
            int(post_id),
            site=site,
            repair=bool(payload.get("repair", False)),
            adopt=bool(payload.get("adopt", False)),
            media_ids=payload.get("media_ids"),
        )
    except Exception as exc:
        return {"command": "guard", "status": "failed", "warnings": [str(exc)]}


def remove_managed_post_media(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Pictova-only selective cleanup for verified duplicate attachments."""
    post_id = payload.get("post_id")
    media_ids = payload.get("media_ids") or []
    if not post_id or not media_ids:
        return {"command": "remove-media", "status": "failed", "warning": "post_id and media_ids gerekli"}
    try:
        site, _ = resolve_post_site(int(post_id), site=payload.get("site", "auto"))
        result = remove_post_media(
            int(post_id),
            media_ids=[int(value) for value in media_ids],
            site=site,
            delete_attachments=bool(payload.get("delete_attachments", True)),
        )
        return {"command": "remove-media", "site": site, **result}
    except Exception as exc:
        return {"command": "remove-media", "status": "failed", "warnings": [str(exc)]}


def refresh_post_captions(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Replace only Pictova-managed figure captions with article copy."""
    post_id = payload.get("post_id")
    if not post_id:
        return {"command": "refresh-captions", "status": "failed", "warning": "post_id gerekli"}
    try:
        from src.pictova.engine.metadata import build_article_caption_map
        from src.services.post_media_guard import load_post_media_manifest

        site, post_context = resolve_post_site(int(post_id), site=payload.get("site", "auto"))
        manifest = load_post_media_manifest(site, int(post_id)) or {}
        managed_items = list(manifest.get("media_items") or [])
        if not managed_items:
            return {
                "command": "refresh-captions",
                "status": "failed",
                "site": site,
                "warning": "Pictova-managed media bulunamadı",
            }
        keys = [str(item.get("media_id")) for item in managed_items if item.get("media_id")]
        assignments = {
            str(item.get("media_id")): {
                "text": item.get("heading", ""),
                "level": item.get("heading_level", 0),
            }
            for item in managed_items
            if item.get("media_id")
        }
        captions = build_article_caption_map(
            keys,
            assigned_headings=assignments,
            post_context=post_context,
        )
        if bool(payload.get("dry_run", False)):
            return {
                "command": "refresh-captions",
                "status": "success",
                "dry_run": True,
                "site": site,
                "post_id": int(post_id),
                "captions": {
                    int(media_id): caption
                    for media_id, caption in captions.items()
                    if caption
                },
            }
        refreshed_items = [
            {
                **item,
                "caption": captions.get(str(item.get("media_id")), ""),
                "description": captions.get(str(item.get("media_id")), "") or item.get("alt", ""),
            }
            for item in managed_items
            if item.get("media_id")
        ]
        result = refresh_managed_post_captions(
            int(post_id),
            media_items=refreshed_items,
            site=site,
        )
        return {
            "command": "refresh-captions",
            "site": site,
            "post_id": int(post_id),
            "captions": {
                int(media_id): caption
                for media_id, caption in captions.items()
                if caption
            },
            **result,
        }
    except Exception as exc:
        return {"command": "refresh-captions", "status": "failed", "warnings": [str(exc)]}


def stats_summary() -> Dict[str, Any]:
    """GET /stats — kısa istatistik özeti."""
    from src.pictova.engine.gallery import gallery_stats
    from src.pictova.engine.vision_chain import has_any_vision_source
    stats = gallery_stats()
    scan_pct = int(stats["scanned"] / stats["local"] * 100) if stats["local"] else 0
    return {
        "status": "ok",
        **stats,
        "scan_progress_pct": scan_pct,
        "vision_ready": has_any_vision_source(),
    }


def health_status() -> Dict[str, Any]:
    return run_health_check()


def plan_attach(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _run_attach_stage("plan", build_attach_plan, payload)


def process_attach(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _run_attach_stage("process", build_process_result, payload)


def _run_attach_stage(command: str, builder: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return the structured failure contract instead of raising.

    `attach` and `review` already convert an unexpected error into a result
    document. Without the same wrapper here, a provider outage reached the CLI
    as a raw traceback and no JSON was printed at all.
    """
    try:
        request, post_context, constraints = prepare_attach_request(**payload)
        return builder(
            site=request.get("site", "auto"),
            request=request,
            post_context=post_context,
            constraints=constraints,
        )
    except Exception as exc:
        return {
            "command": command,
            "status": "failed",
            "site": payload.get("site", "auto"),
            "post_id": payload.get("post_id"),
            "selection": {"files": []},
            "warnings": [str(exc)],
        }


def attach_images(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Thin API-style wrapper over the attach job."""
    return run_attach_job(**payload)
