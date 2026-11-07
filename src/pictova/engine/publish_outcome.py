"""One verified WordPress publishing outcome contract for native and legacy paths.

A successful media-library upload is not proof that the article contains an
image. A partial result never means "published successfully": it means some
verified blocks were added or WordPress commit verification is inconclusive.
"""

from __future__ import annotations

from typing import Any, Mapping


_UNCERTAIN_POST_WRITE = {"post_update_verification_failed", "media_manifest_write_failed"}


def classify_publish_result(
    published: Mapping[str, Any], *, warnings: bool = False
) -> tuple[str, str, bool]:
    """Return (status, reason, needs_reconciliation).

    success: post edit is verified, or exact already-managed assets were found;
    partial: verified edits plus failures, or a possibly committed edit cannot
             be verified and requires human reconciliation;
    failed: no verified post edit and no successful idempotent replay.
    """
    content = published.get("content_update")
    if not isinstance(content, dict):
        return "failed", "missing_content_update", True

    if content.get("success") is not True:
        code = str(content.get("code") or "")
        reason = code or "post_content_update_failed"
        uncertain = code in _UNCERTAIN_POST_WRITE or "could not be verified" in str(content.get("error") or "")
        return ("partial" if uncertain else "failed"), reason, uncertain

    try:
        inserted = int(content.get("inserted") or 0)
    except (TypeError, ValueError):
        return "failed", "invalid_inserted_count", True
    if inserted < 0:
        return "failed", "invalid_inserted_count", True
    existing = published.get("skipped") or []
    idempotent = bool(content.get("idempotent")) and bool(existing)

    if inserted == 0 and not idempotent:
        return "failed", "no_verified_media_placement", False

    if published.get("failed") or warnings:
        return "partial", "verified_with_warnings", False

    if idempotent and inserted == 0:
        return "success", "already_present", False
    return "success", "verified_post_update", False


def classify_job_result(status: object) -> str:
    """Preserve partial; never collapse an unknown result to success."""
    if status in {"success", "ok", "local"}:
        return "success"
    if status == "partial":
        return "partial"
    return "failed"


__all__ = ["classify_publish_result", "classify_job_result"]
