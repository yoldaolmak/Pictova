"""Canonical attach orchestration helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import fcntl
from pathlib import Path
import re
from typing import Any, Dict, Tuple

from src.main import YOOrchestrator
from src.core.media_publish import build_publish_slug_candidates, embed_metadata, ensure_unique_slug
from src.pictova.profiles.yoldaolmak import apply_environment
from src.pictova.engine.metadata import build_native_metadata_map
from src.pictova.engine.quality import quality_gate_native_batch
from src.pictova.providers.wordpress import fetch_post_context, resolve_post_site
from src.pictova.engine.processor import process_selected_images
from src.pictova.engine.publisher import publish_processed_images
from src.pictova.engine.selector import (
    _matching_anchor_count,
    _token_set_from_text,
    resolve_source_images,
)
from src.pictova.engine.vision_chain import download_icloud_photo


_ATTACH_LOCK_DIR = Path(__file__).resolve().parents[3] / "data" / "attach_locks"


def _try_acquire_attach_lock(site: str, post_id: Any):
    """Return a process-scoped post lock, or None when another attach owns it."""
    safe_site = re.sub(r"[^a-z0-9_-]+", "-", str(site).casefold()).strip("-") or "site"
    _ATTACH_LOCK_DIR.mkdir(parents=True, exist_ok=True)
    path = _ATTACH_LOCK_DIR / f"{safe_site}-{int(post_id)}.lock"
    handle = path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _release_attach_lock(handle: Any) -> None:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _photo_index_stats() -> dict:
    """Visual memory DB summary statistics."""
    import sqlite3 as _sq
    try:
        from src.pictova.config import get_visual_memory_db_path
        db = get_visual_memory_db_path()
        con = _sq.connect(str(db))
        row = con.execute("""
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN source_path != '' THEN 1 ELSE 0 END) AS local_count,
              SUM(CASE WHEN source_path  = '' THEN 1 ELSE 0 END) AS icloud_count,
              SUM(CASE WHEN vision_scan_status = 'done' THEN 1 ELSE 0 END) AS scanned
            FROM asset_index WHERE is_personal = 0
        """).fetchone()
        con.close()
        return {"total": row[0], "local": row[1], "icloud": row[2], "vision_scanned": row[3]}
    except Exception as exc:
        return {"error": str(exc)}


def resolve_icloud_files(files: list[str], warnings: list[str]) -> list[str]:
    """Downloads iCloud UUID (icloud://UUID) files and replaces them with local paths."""
    resolved = []
    for f in files:
        if f.startswith("icloud://"):
            uuid = f.removeprefix("icloud://")
            try:
                local = download_icloud_photo(uuid)
                resolved.append(local)
            except Exception as exc:
                warnings.append(f"iCloud download failed ({uuid[:8]}): {exc}")
        else:
            resolved.append(f)
    return resolved


def summarize_post_context(post_context: Dict[str, Any]) -> Dict[str, Any]:
    if not post_context:
        return {}
    return {
        "id": post_context.get("id"),
        "title": post_context.get("title"),
        "slug": post_context.get("slug"),
        "excerpt_preview": str(post_context.get("excerpt", ""))[:100] + "...",
        "headings_count": len(post_context.get("available_headings", [])),
    }


def _compute_assigned_headings(
    processed_images: list[str],
    request: Dict[str, Any],
    post_context: Dict[str, Any],
    *,
    processed_details: Dict[str, Dict[str, Any]] | None = None,
    heading_assignments: Dict[str, Dict[str, Any]] | None = None,
) -> Dict[str, Dict[str, Any]]:
    assigned = {}
    force_heading = request.get("heading")
    if force_heading:
        for img in processed_images:
            assigned[img] = {
                "text": force_heading,
                "level": request.get("heading_level") or 0,
            }
        return assigned

    # Selection is heading-aware. Preserve that exact source-to-heading link
    # through image processing; otherwise an Airbnb image can be selected for
    # its H3 and then get inserted below an unrelated introductory H2 merely
    # because the H2 appears first in the post.
    processed_details = processed_details or {}
    heading_assignments = heading_assignments or {}
    for img in processed_images:
        source = str(processed_details.get(img, {}).get("input") or "")
        heading = heading_assignments.get(source)
        if heading:
            assigned[img] = dict(heading)

    available = post_context.get("available_headings") or []
    explicit_query = request.get("location_query") or request.get("query")
    if available and explicit_query:
        query_tokens = _token_set_from_text(explicit_query)
        ranked = [
            (_matching_anchor_count(_token_set_from_text(item.get("text", "")), query_tokens), pos, item)
            for pos, item in enumerate(available)
        ]
        relevant = [item for score, _, item in sorted(ranked, key=lambda row: (-row[0], row[1])) if score > 0]
        if relevant:
            available = relevant
    remaining_images = [img for img in processed_images if img not in assigned]
    if available and remaining_images:
        n_images = len(remaining_images)
        n_heads = len(available)
        if n_images > n_heads:
            # More images than headings — round-robin across headings
            for slot, img in enumerate(remaining_images):
                assigned[img] = dict(available[slot % n_heads])
        else:
            # Prefer the earliest available headings first.
            # The previous spacing formula skipped the first main heading and
            # pushed the first image into later logistics sections.
            for slot, img in enumerate(remaining_images):
                idx = min(slot, n_heads - 1)
                assigned[img] = dict(available[idx])
    return assigned


def _is_comprehensive_places_article(post_context: Dict[str, Any]) -> bool:
    """Whether a two-image H3 gallery helps scan a long places list."""
    title = str(post_context.get("title") or "").casefold()
    headings = post_context.get("available_headings") or []
    h3_count = sum(int(item.get("level") or 0) == 3 for item in headings)
    return ("gezilecek yer" in title or "görülecek yer" in title) and h3_count >= 3


def apply_semantic_gallery_policy(
    metadata_dict: Dict[str, Dict[str, Any]],
    processed_details: Dict[str, Dict[str, Any]],
    post_context: Dict[str, Any],
    *,
    requested_count: int,
) -> Dict[str, Dict[str, Any]]:
    """Mark only visually and structurally justified image pairs as galleries.

    A gallery is presentation, not a shorthand for a requested count.  It is
    useful for a pair of portrait images in a larger run, or for a pair placed
    under one H3 in a long "gezilecek yerler" list.  Everything else remains a
    sequence of individual responsive image blocks.
    """
    grouped: Dict[tuple[str, int], list[str]] = {}
    for image_file, metadata in metadata_dict.items():
        metadata["gallery"] = False
        heading = str(metadata.get("heading") or "").strip()
        level = int(metadata.get("heading_level") or 0)
        if heading:
            grouped.setdefault((heading, level), []).append(image_file)

    places_article = _is_comprehensive_places_article(post_context)
    for (_, heading_level), files in grouped.items():
        if len(files) != 2:
            continue
        portrait_pair = all(
            float((processed_details.get(image_file) or {}).get("aspect_ratio") or 1.0) < 0.92
            for image_file in files
        )
        long_run_portrait_pair = requested_count > 4 and portrait_pair
        places_subheading_pair = requested_count >= 6 and places_article and heading_level == 3
        if long_run_portrait_pair or places_subheading_pair:
            for image_file in files:
                metadata_dict[image_file]["gallery"] = True
    return metadata_dict


_SLUG_GENERIC = {
    "gezilecek", "yerler", "yerleri", "gezi", "rehberi", "rehber",
    "nerede", "nasil", "nasil-gidilir", "seyahat", "travel", "guide",
    "rota", "rotasi", "rotalar", "detayli", "guncel", "notlari",
    "ve", "ile", "icin", "the", "and", "bir",
    "yakin", "yakın", "ulasim", "ulaşım", "gecis", "geçiş",
    "tavsiyelerim", "tavsiyesi", "ipuclari", "ipuçları",
}


def derive_location_query(post_context: Dict[str, Any]) -> str:
    """Extract the first meaningful destination token from the slug.

    Full title breaks AND-logic semantic search. The destination name alone is
    usually enough: 'sinop-gezilecek-yerler' → 'sinop'.
    """
    slug = str(post_context.get("slug") or "").strip()
    tokens = [
        t for t in slug.split("-")
        if t and t not in _SLUG_GENERIC and len(t) >= 3 and not t.isdigit()
    ]
    if tokens:
        return tokens[0]
    title = str(post_context.get("title") or "").strip()
    title = re.split(r"\s+[—–|]\s+", title, maxsplit=1)[0]
    title_tokens = []
    for token in re.findall(r"[a-zA-Z0-9çğıöşüÇĞİÖŞÜ]+", title):
        normalized = token.lower()
        if normalized in _SLUG_GENERIC or len(normalized) < 3 or normalized.isdigit():
            continue
        if normalized not in title_tokens:
            title_tokens.append(normalized)
    return title_tokens[0] if title_tokens else ""


def build_failed_attach_result(
    *,
    site: str,
    post_id: Any,
    request: Dict[str, Any],
    post_context: Dict[str, Any],
    constraints: Dict[str, Any],
    warning: str,
) -> Dict[str, Any]:
    return {
        "command": "attach",
        "site": site,
        "post_id": post_id,
        "request": request,
        "post_context": summarize_post_context(post_context),
        "status": "failed",
        "selected_assets": [],
        "rejected_assets": [],
        "uploaded_media_ids": [],
        "inserted_blocks": 0,
        "uploaded": [],
        "failed_uploads": [],
        "constraints": constraints,
        "warnings": [warning],
        "duration_ms": 0,
        "raw": {},
    }


def normalize_attach_result(
    raw: Dict[str, Any],
    *,
    constraints: Dict[str, Any],
    duration_ms: int,
    request: Dict[str, Any],
    post_context: Dict[str, Any],
) -> Dict[str, Any]:
    upload_complete = raw.get("steps", {}).get("upload_complete", {})
    uploaded = upload_complete.get("uploaded", [])
    content_update = upload_complete.get("content_update", {})
    warning = raw.get("warning") or raw.get("error")
    quality_gate = raw.get("steps", {}).get("quality_gate", {})
    return {
        "command": "attach",
        "site": raw.get("site"),
        "post_id": raw.get("post_id"),
        "request": request,
        "post_context": summarize_post_context(post_context),
        "status": raw.get("status"),
        "selected_assets": raw.get("steps", {}).get("images_loaded", {}).get("files", []),
        "rejected_assets": quality_gate.get("blocked", []),
        "uploaded_media_ids": [item.get("media_id") for item in uploaded if item.get("media_id")],
        "inserted_blocks": content_update.get("inserted", 0),
        "uploaded": uploaded,
        "failed_uploads": upload_complete.get("failed", []),
        "constraints": constraints,
        "warnings": [warning] if warning else [],
        "duration_ms": duration_ms,
        "raw": raw,
    }


def prepare_attach_request(**kwargs: Any) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    site = kwargs.get("site", "auto")
    apply_environment()  # always load .env (DP/Unsplash/Gemini creds are shared)

    request = dict(kwargs)
    post_id = request.get("post_id")
    post_context = {}
    if post_id:
        try:
            if str(site).strip().lower() == "auto":
                site, post_context = resolve_post_site(int(post_id), site=site)
            else:
                post_context = fetch_post_context(int(post_id), site=site)
        except Exception as exc:
            post_context = {}
            request["_site_resolution_error"] = str(exc)
    request["site"] = site

    if request.get("source") == "semantic" and not request.get("location_query"):
        request["location_query"] = derive_location_query(post_context)

    constraints = {
        "language": request.pop("language", "tr"),
        "people_first": bool(request.pop("people_first", False)),
    }
    if constraints["people_first"] and not request.get("content_filter"):
        request["content_filter"] = "insan"

    return request, post_context, constraints


def validate_attach_request(
    *,
    site: str,
    request: Dict[str, Any],
    post_context: Dict[str, Any],
    constraints: Dict[str, Any],
) -> Dict[str, Any] | None:
    post_id = request.get("post_id")
    source = request.get("source", "semantic")
    if request.get("_site_resolution_error"):
        return build_failed_attach_result(
            site=site,
            post_id=post_id,
            request=request,
            post_context=post_context,
            constraints=constraints,
            warning=str(request["_site_resolution_error"]),
        )
    if source == "semantic" and not request.get("location_query"):
        return build_failed_attach_result(
            site=site,
            post_id=post_id,
            request=request,
            post_context=post_context,
            constraints=constraints,
            warning="location_query could not be derived; provide --location-query or ensure the post has a usable title/slug",
        )
    if source == "unsplash" and not request.get("query"):
        return build_failed_attach_result(
            site=site,
            post_id=post_id,
            request=request,
            post_context=post_context,
            constraints=constraints,
            warning="query is required when source=unsplash",
        )
    # post_id is optional during the plan phase — required in execute_native_attach
    return None


def _validate_execute_request(
    *,
    site: str,
    request: Dict[str, Any],
    post_context: Dict[str, Any],
    constraints: Dict[str, Any],
) -> Dict[str, Any] | None:
    """Additional validation for execute_native_attach — post_id is required."""
    failure = validate_attach_request(
        site=site, request=request, post_context=post_context, constraints=constraints
    )
    if failure:
        return failure
    if not request.get("post_id"):
        return build_failed_attach_result(
            site=site,
            post_id=None,
            request=request,
            post_context=post_context,
            constraints=constraints,
            warning="post_id is required for attach",
        )
    return None


def execute_legacy_attach(
    *,
    site: str,
    request: Dict[str, Any],
    post_context: Dict[str, Any],
    constraints: Dict[str, Any],
) -> Dict[str, Any]:
    started = datetime.now(timezone.utc)
    orchestrator = YOOrchestrator()
    raw = orchestrator.run_pipeline(**request)
    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return normalize_attach_result(
        raw,
        constraints=constraints,
        duration_ms=duration_ms,
        request=request,
        post_context=post_context,
    )


def build_attach_plan(
    *,
    site: str,
    request: Dict[str, Any],
    post_context: Dict[str, Any],
    constraints: Dict[str, Any],
) -> Dict[str, Any]:
    failure = validate_attach_request(
        site=site,
        request=request,
        post_context=post_context,
        constraints=constraints,
    )
    if failure:
        failure["command"] = "plan"
        return failure

    selection = resolve_source_images(
        source=request.get("source", "semantic"),
        count=request.get("count"),
        name=request.get("name"),
        query=request.get("query"),
        location_query=request.get("location_query"),
        content_filter=request.get("content_filter"),
        post_context=post_context,
        plan_only=True,
    )
    return {
        "command": "plan",
        "site": site,
        "post_id": request.get("post_id"),
        "request": request,
        "post_context": summarize_post_context(post_context),
        "constraints": constraints,
        "status": "success",
        "selection": selection,
        "photo_index_stats": _photo_index_stats(),
        "warnings": list(selection.get("warnings", [])),
    }


def build_process_result(
    *,
    site: str,
    request: Dict[str, Any],
    post_context: Dict[str, Any],
    constraints: Dict[str, Any],
) -> Dict[str, Any]:
    failure = validate_attach_request(
        site=site,
        request=request,
        post_context=post_context,
        constraints=constraints,
    )
    if failure:
        failure["command"] = "process"
        return failure

    selection = resolve_source_images(
        source=request.get("source", "semantic"),
        count=request.get("count"),
        name=request.get("name"),
        query=request.get("query"),
        location_query=request.get("location_query"),
        content_filter=request.get("content_filter"),
        post_context=post_context,
    )
    icloud_warnings: list[str] = []
    _files = resolve_icloud_files(selection.get("files", []), icloud_warnings)
    processed = process_selected_images(_files)
    return {
        "command": "process",
        "site": site,
        "post_id": request.get("post_id"),
        "request": request,
        "post_context": summarize_post_context(post_context),
        "constraints": constraints,
        "status": "success",
        "selection": selection,
        "processed_images": processed.get("processed_images", []),
        "panoramic_images": processed.get("panoramic_images", {}),
        "work_dir": processed.get("work_dir"),
        # An iCloud asset that failed to download silently disappeared from the
        # result; the caller saw a short list with no reason for it.
        "warnings": list(selection.get("warnings", [])) + icloud_warnings,
    }


def finalize_publish_assets(
    *,
    processed_images: list[str],
    metadata_dict: Dict[str, Dict[str, Any]],
    processed_details: Dict[str, Dict[str, Any]],
    post_context: Dict[str, Any],
    work_dir: str | None,
) -> tuple[list[str], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    used_slugs: set[str] = set()
    finalized_files: list[str] = []
    finalized_metadata: Dict[str, Dict[str, Any]] = {}
    finalized_details: Dict[str, Dict[str, Any]] = {}
    target_dir = Path(work_dir) if work_dir else (Path(processed_images[0]).parent if processed_images else Path("/tmp"))

    for file in processed_images:
        meta = dict(metadata_dict.get(file, {}))
        process_info = dict(processed_details.get(file, {}))
        slug_source_path = str(process_info.get("input") or file)
        slug_candidates = build_publish_slug_candidates(meta, post_context, slug_source_path)
        # Find the best (first / location-based) candidate.
        # Use directly if not already taken; try other candidates if it clashes;
        # if all clash, use a suffixed version of the best candidate —
        # this avoids falling back to a generic name (e.g. 'gumusluk-bodrum-koy-kayalik-detay').
        best_candidate = slug_candidates[0] if slug_candidates else "seyahat-kare"
        candidate_slug = None
        for slug in slug_candidates:
            trial = ensure_unique_slug(slug, used_slugs)
            if trial == slug:
                candidate_slug = trial
                break
        if candidate_slug is None:
            # All candidates already used — generate a suffixed version of the best candidate
            candidate_slug = ensure_unique_slug(best_candidate, used_slugs)
        used_slugs.add(candidate_slug)

        # `used_slugs` above is the only collision domain that matters for an
        # attach batch.  A previous controlled retry can leave the same name in
        # `work_dir`; treating that temporary artifact as a new public-media
        # collision used to turn a stable name such as
        # `yalniz-seyahat-sokak` into `yalniz-seyahat-sokak-detay`.
        # Replacing the deterministic work artifact is safe and preserves the
        # intended WordPress filename on retries.
        final_path = target_dir / f"{candidate_slug}.webp"
        source_path = Path(file)
        if source_path != final_path:
            source_path.replace(final_path)

        embedded = embed_metadata(str(final_path), meta)
        meta["embedded"] = embedded
        meta["final_slug"] = final_path.stem

        finalized_path = str(final_path)
        finalized_files.append(finalized_path)
        finalized_metadata[finalized_path] = meta
        finalized_details[finalized_path] = process_info

    return finalized_files, finalized_metadata, finalized_details


def execute_native_attach(
    *,
    site: str,
    request: Dict[str, Any],
    post_context: Dict[str, Any],
    constraints: Dict[str, Any],
) -> Dict[str, Any]:
    failure = _validate_execute_request(
        site=site,
        request=request,
        post_context=post_context,
        constraints=constraints,
    )
    if failure:
        return failure

    lock = _try_acquire_attach_lock(site, request["post_id"])
    if lock is None:
        return build_failed_attach_result(
            site=site,
            post_id=request.get("post_id"),
            request=request,
            post_context=post_context,
            constraints=constraints,
            warning="Pictova attach is already in progress for this post; no duplicate work was started",
        )
    try:
        return _execute_native_attach_locked(
            site=site,
            request=request,
            post_context=post_context,
            constraints=constraints,
        )
    finally:
        _release_attach_lock(lock)


def _execute_native_attach_locked(
    *,
    site: str,
    request: Dict[str, Any],
    post_context: Dict[str, Any],
    constraints: Dict[str, Any],
) -> Dict[str, Any]:
    """Run one attach while this post's process lock is held."""

    started = datetime.now(timezone.utc)
    selection = resolve_source_images(
        source=request.get("source", "semantic"),
        count=request.get("count"),
        name=request.get("name"),
        query=request.get("query"),
        location_query=request.get("location_query"),
        content_filter=request.get("content_filter"),
        post_context=post_context,
    )
    requested_count = int(request.get("count") or 0)
    selected_assets = list(selection.get("files", []))
    selection_warnings: list[str] = list(selection.get("warnings", []))
    if not selected_assets:
        failure = build_failed_attach_result(
            site=site,
            post_id=request.get("post_id"),
            request=request,
            post_context=post_context,
            constraints=constraints,
            warning=(
                f"Strict selection produced 0/{requested_count} exact matches; "
                "nothing was uploaded"
            ),
        )
        failure["selected_assets"] = selected_assets
        failure["warnings"] = selection_warnings + failure["warnings"]
        failure["raw"] = {"selection": selection}
        return failure
    if requested_count and len(selected_assets) < requested_count:
        selection_warnings.append(
            f"Strict selection produced {len(selected_assets)}/{requested_count} exact matches; "
            "only verified assets were uploaded"
        )
    # An iCloud download failure removes a selected asset from the run. It has
    # to reach the receipt, otherwise a short upload looks like a clean success.
    _resolved_files = resolve_icloud_files(selected_assets, selection_warnings)
    processed = process_selected_images(_resolved_files)
    processed_images = processed.get("processed_images", [])
    selector_assignments = dict(selection.get("heading_assignments", {}))
    approved_assignments = request.get("approved_heading_assignments", {})
    if isinstance(approved_assignments, dict):
        # An approved plan may be replayed from locally downloaded assets.
        # Retain its exact source-to-H-heading binding so a retry does not
        # rediscover DepositPhotos or lose the original semantic placement.
        selector_assignments.update(approved_assignments)
    assigned_headings = _compute_assigned_headings(
        processed_images,
        request,
        post_context,
        processed_details=processed.get("processed_details", {}),
        heading_assignments=selector_assignments,
    )

    metadata_dict, metadata_warnings = build_native_metadata_map(
        processed_images,
        assigned_headings=assigned_headings,
        post_context=post_context,
        mode=request.get("metadata_mode", "auto"),
    )

    approved_files, approved_metadata, approved_details, blocked = quality_gate_native_batch(
        processed_images=processed_images,
        metadata_dict=metadata_dict,
        processed_details=processed.get("processed_details", {}),
        post_context=post_context,
    )
    approved_metadata = apply_semantic_gallery_policy(
        approved_metadata,
        approved_details,
        post_context,
        requested_count=requested_count,
    )
    if not approved_files:
        failure = build_failed_attach_result(
            site=site,
            post_id=request.get("post_id"),
            request=request,
            post_context=post_context,
            constraints=constraints,
            warning=(
                f"Quality gate approved 0/{len(selected_assets)} selected assets; "
                "nothing was uploaded"
            ),
        )
        failure["selected_assets"] = selected_assets
        failure["rejected_assets"] = blocked
        failure["warnings"].extend(metadata_warnings)
        failure["raw"] = {"selection": selection, "processed": processed}
        return failure
    finalized_files, finalized_metadata, finalized_details = finalize_publish_assets(
        processed_images=approved_files,
        metadata_dict=approved_metadata,
        processed_details=approved_details,
        post_context=post_context,
        work_dir=processed.get("work_dir"),
    )
    published = publish_processed_images(
        site=site,
        post_id=request["post_id"],
        processed_images=finalized_files,
        metadata_dict=finalized_metadata,
    )
    duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return {
        "command": "attach",
        "site": site,
        "post_id": request.get("post_id"),
        "request": request,
        "post_context": summarize_post_context(post_context),
        "status": "partial" if (published.get("failed") or selection_warnings or blocked) else "success",
        "selected_assets": selection.get("files", []),
        "rejected_assets": blocked,
        "uploaded_media_ids": [item.get("media_id") for item in published.get("uploaded", []) if item.get("media_id")],
        "inserted_blocks": published.get("content_update", {}).get("inserted", 0),
        "uploaded": published.get("uploaded", []),
        "failed_uploads": published.get("failed", []),
        "constraints": constraints,
        "warnings": selection_warnings + metadata_warnings,
        "duration_ms": duration_ms,
        "raw": {
            "selection": selection,
            "processed": processed,
            "approved_files": finalized_files,
            "approved_details": finalized_details,
            "published": published,
        },
    }
