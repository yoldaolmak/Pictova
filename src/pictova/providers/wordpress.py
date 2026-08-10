"""Canonical WordPress provider exports."""

from __future__ import annotations

from src.services.wordpress import YOWordPressUploader, fetch_post_context, upload_images_batch


def resolve_post_site(post_id: int, *, site: str = "auto") -> tuple[str, dict]:
    """Resolve a WordPress post ID to one configured site without guessing.

    Site-local IDs can collide, therefore more than one positive response is
    an error rather than a silent first-match.  Credentials are never exposed.
    """
    requested = str(site or "auto").strip().lower()
    if requested != "auto":
        context = fetch_post_context(post_id, site=requested)
        if context:
            return requested, context
        access = YOWordPressUploader.check_site_access(requested)
        if access.get("status") == "rejected":
            raise ValueError(
                f"WordPress authentication rejected for site: {requested} "
                f"(HTTP {access.get('http_status')})"
            )
        if access.get("status") == "unreachable":
            raise ValueError(f"WordPress could not be reached for site: {requested}")
        return requested, context

    matches: list[tuple[str, dict]] = []
    unavailable: list[str] = []
    rejected: list[str] = []
    unreachable: list[str] = []
    for candidate in YOWordPressUploader.SITE_ENDPOINTS:
        try:
            context = fetch_post_context(post_id, site=candidate)
        except ValueError:
            unavailable.append(candidate)
            continue
        if context:
            matches.append((candidate, context))
            continue
        access = YOWordPressUploader.check_site_access(candidate)
        if access.get("status") == "rejected":
            rejected.append(f"{candidate} (HTTP {access.get('http_status')})")
        elif access.get("status") == "unreachable":
            unreachable.append(candidate)

    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(name for name, _ in matches)
        raise ValueError(f"Post {post_id} exists on more than one configured site: {names}; specify site")
    missing = f"; unavailable credentials: {', '.join(unavailable)}" if unavailable else ""
    auth = f"; authentication rejected: {', '.join(rejected)}" if rejected else ""
    offline = f"; unreachable sites: {', '.join(unreachable)}" if unreachable else ""
    raise ValueError(f"Post {post_id} could not be resolved on configured WordPress sites{missing}{auth}{offline}")


def guard_post_media(
    post_id: int,
    *,
    site: str = "yoldaolmak",
    repair: bool = False,
    reposition: bool = False,
    adopt: bool = False,
    media_ids: list[int] | None = None,
) -> dict:
    uploader = YOWordPressUploader(site=site)
    return uploader.guard_post_media(
        post_id,
        repair=repair,
        reposition=reposition,
        adopt=adopt,
        media_ids=media_ids,
    )


def reset_post_media(post_id: int, *, site: str = "yoldaolmak") -> dict:
    uploader = YOWordPressUploader(site=site)
    return uploader.reset_post_media_content(post_id)


def remove_post_media(
    post_id: int,
    *,
    media_ids: list[int],
    site: str = "yoldaolmak",
    delete_attachments: bool = True,
) -> dict:
    """Remove only explicit Pictova-managed duplicate media."""
    uploader = YOWordPressUploader(site=site)
    return uploader.remove_managed_media_items(
        post_id,
        media_ids,
        delete_attachments=delete_attachments,
    )


def refresh_post_captions(
    post_id: int,
    *,
    media_items: list[dict],
    site: str = "yoldaolmak",
) -> dict:
    """Repair visible captions for existing Pictova-managed media only."""
    uploader = YOWordPressUploader(site=site)
    return uploader.refresh_managed_media_captions(post_id, media_items)


__all__ = [
    "YOWordPressUploader",
    "fetch_post_context",
    "guard_post_media",
    "remove_post_media",
    "refresh_post_captions",
    "reset_post_media",
    "resolve_post_site",
    "upload_images_batch",
]
