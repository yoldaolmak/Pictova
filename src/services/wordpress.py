#!/usr/bin/env python3
"""
YO OS WordPress Uploader — REST API media upload and attachment
"""

import requests
import json
import os
import re
import html
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional
import base64

from src.services.post_media_guard import (
    assess_post_media,
    load_post_media_manifest,
    manifest_path as post_media_manifest_path,
    media_items_from_content,
    save_post_media_manifest,
)
from src.utils.config import env_str, load_project_env

load_project_env()

AUTO_MEDIA_START = "<!-- yo:auto-media:start -->"
AUTO_MEDIA_END = "<!-- yo:auto-media:end -->"


def _first_env(*names: str) -> str:
    """Accept the documented and legacy app-password names for each site."""
    for name in names:
        value = env_str(name)
        if value:
            return value
    return ""


def _replace_managed_figure_captions(
    content: str,
    captions_by_media_id: Dict[int, str],
) -> tuple[str, set[int]]:
    """Replace captions only inside explicitly managed Gutenberg image blocks."""
    found: set[int] = set()

    def replace_block(match: re.Match) -> str:
        block = match.group(0)
        media_match = re.search(r"\bwp-image-(\d+)\b", block)
        if not media_match:
            return block
        media_id = int(media_match.group(1))
        if media_id not in captions_by_media_id:
            return block
        found.add(media_id)
        caption = str(captions_by_media_id[media_id] or "").strip()
        figcaption = re.compile(
            r"<figcaption\b[^>]*>.*?</figcaption>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not caption:
            return figcaption.sub("", block)
        rendered = f'<figcaption class="wp-element-caption">{html.escape(caption, quote=False)}</figcaption>'
        if figcaption.search(block):
            return figcaption.sub(rendered, block, count=1)
        close_figure = block.rfind("</figure>")
        if close_figure < 0:
            return block
        return block[:close_figure] + rendered + block[close_figure:]

    updated = re.sub(
        r"<!--\s*wp:image\b.*?<!--\s*/wp:image\s*-->",
        replace_block,
        content or "",
        flags=re.IGNORECASE | re.DOTALL,
    )
    return updated, found


class YOWordPressUploader:
    """Upload processed images to WordPress via REST API"""

    SITE_ENDPOINTS = {
        "yoldaolmak": {
            "url": env_str("WP_URL", "https://yoldaolmak.com"),
            "user": env_str("WP_USER", "hamal"),
            "password": _first_env("WP_APP_PASSWORD", "WP_PASSWORD"),
            "credential_names": "WP_APP_PASSWORD or WP_PASSWORD",
        },
        "gezievreni": {
            "url": env_str("GEZIEVRENI_URL", "https://gezievreni.com"),
            "user": env_str("GEZIEVRENI_USER", "hamal"),
            "password": _first_env("GEZIEVRENI_PASS", "GEZIEVRENI_WP_APP_PASSWORD", "GEZIEVRENI_PASSWORD"),
            "credential_names": "GEZIEVRENI_PASS, GEZIEVRENI_WP_APP_PASSWORD or GEZIEVRENI_PASSWORD",
        },
        "gezgindunyasi": {
            "url": env_str("GEZGINDUNYASI_URL", "https://gezgindunyasi.com"),
            "user": env_str("GEZGINDUNYASI_USER", "clawdbot"),
            "password": _first_env("GEZGINDUNYASI_PASS", "GEZGINDUNYASI_WP_APP_PASSWORD", "GEZGINDUNYASI_PASSWORD"),
            "credential_names": "GEZGINDUNYASI_PASS, GEZGINDUNYASI_WP_APP_PASSWORD or GEZGINDUNYASI_PASSWORD",
        },
    }

    @classmethod
    def site_readiness(cls, *, verify_remote: bool = False) -> Dict[str, Dict[str, object]]:
        """Return publish readiness without ever returning credential values.

        A missing app password used to appear only after a job had already
        attempted automatic site resolution.  Surface it in health checks so
        a batch can stop before selection, download, or upload work starts.
        """
        readiness: Dict[str, Dict[str, object]] = {}
        for site, config in cls.SITE_ENDPOINTS.items():
            missing = [
                name
                for name, value in (
                    ("url", config.get("url")),
                    ("user", config.get("user")),
                    ("app_password", config.get("password")),
                )
                if not value
            ]
            result: Dict[str, object] = {
                "status": "ready" if not missing else "blocked",
                "missing": missing,
                "credential_names": config.get("credential_names", "") if "app_password" in missing else "",
            }
            if verify_remote and not missing:
                result.update(cls.check_site_access(site))
            readiness[site] = result
        return readiness

    @classmethod
    def check_site_access(cls, site: str) -> Dict[str, object]:
        """Verify WordPress application-password access without exposing it."""
        if site not in cls.SITE_ENDPOINTS:
            return {"status": "blocked", "missing": ["site"]}
        config = cls.SITE_ENDPOINTS[site]
        missing = [
            name
            for name, value in (
                ("url", config.get("url")),
                ("user", config.get("user")),
                ("app_password", config.get("password")),
            )
            if not value
        ]
        if missing:
            return {
                "status": "blocked",
                "missing": missing,
                "credential_names": config.get("credential_names", "") if "app_password" in missing else "",
            }
        return cls(site).verify_access()

    def __init__(self, site: str = "yoldaolmak"):
        if site not in self.SITE_ENDPOINTS:
            raise ValueError(f"Unknown site: {site}")

        config = self.SITE_ENDPOINTS[site]
        self.site = site
        self.base_url = config["url"]
        self.user = config["user"]
        self.password = config["password"]
        if not self.base_url or not self.user or not self.password:
            raise ValueError(
                f"Missing WordPress credentials for site: {site}; set {config.get('credential_names', 'the site app-password variable')}"
            )
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create authenticated session"""
        session = requests.Session()
        session.auth = (self.user, self.password)
        session.headers.update({
            "User-Agent": "YO-OS-Media-Uploader/1.0",
        })
        return session

    def verify_access(self) -> Dict[str, object]:
        """Return a compact live access status for this configured site."""
        try:
            response = self.session.get(
                f"{self.base_url}/wp-json/wp/v2/users/me?context=edit",
                timeout=15,
            )
        except requests.exceptions.RequestException:
            return {"status": "unreachable"}
        if response.status_code == 200:
            return {"status": "ready", "http_status": 200}
        if response.status_code in {401, 403}:
            return {"status": "rejected", "http_status": response.status_code}
        return {"status": "unreachable", "http_status": response.status_code}


    def upload_media(
        self,
        file_path: str,
        title: str,
        alt_text: str,
        description: str = "",
        caption: str = "",
    ) -> Dict:
        """Upload single image to WordPress media library.
        Aynı slug'lı eski media varsa önce siler (slug çakışması / -1 -2 sorunu).

        Returns:
            dict with media_id and details
        """
        file_p = Path(file_path)
        if not file_p.exists():
            return {"success": False, "error": f"File not found: {file_path}"}

        endpoint = f"{self.base_url}/wp-json/wp/v2/media"

        # Read file
        with open(file_path, "rb") as f:
            file_data = f.read()

        # Upload
        headers = {
            "Content-Disposition": f'attachment; filename="{file_p.name}"',
            "Content-Type": "image/webp",
        }

        try:
            resp = self.session.post(
                endpoint,
                data=file_data,
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()

            media = resp.json()
            media_id = media["id"]

            # Update media metadata
            update_data = {
                "title": title,
                "description": description,
                "caption": caption,
                "alt_text": alt_text,
            }

            update_endpoint = f"{self.base_url}/wp-json/wp/v2/media/{media_id}"
            update_resp = self.session.post(
                update_endpoint,
                json=update_data,
                timeout=30,
            )
            update_resp.raise_for_status()

            return {
                "success": True,
                "media_id": media_id,
                "url": media.get("source_url", ""),
                "title": title,
                "alt_text": alt_text,
                "file": file_p.name,
            }

        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": str(e),
                "file": file_p.name,
            }

    def attach_to_post(
        self,
        media_id: int,
        post_id: int,
    ) -> Dict:
        """Attach media to post (not as featured image)

        Args:
            media_id: WordPress media ID
            post_id: WordPress post ID

        Returns:
            dict with success status
        """
        endpoint = f"{self.base_url}/wp-json/wp/v2/media/{media_id}"

        try:
            resp = self.session.post(
                endpoint,
                json={"post": post_id},
                timeout=30,
            )
            resp.raise_for_status()

            return {
                "success": True,
                "media_id": media_id,
                "post_id": post_id,
            }

        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": str(e),
                "media_id": media_id,
            }

    def update_media_metadata(
        self,
        media_id: int,
        *,
        title: str,
        alt_text: str,
        caption: str = "",
        description: str = "",
    ) -> Dict:
        """Update WordPress attachment metadata through Pictova's API client."""
        endpoint = f"{self.base_url}/wp-json/wp/v2/media/{media_id}"
        try:
            resp = self.session.post(
                endpoint,
                json={
                    "title": title,
                    "alt_text": alt_text,
                    "caption": caption,
                    "description": description,
                },
                timeout=30,
            )
            resp.raise_for_status()
            return {"success": True, "media_id": media_id}
        except requests.exceptions.RequestException as exc:
            return {"success": False, "media_id": media_id, "error": str(exc)}

    def refresh_managed_media_captions(self, post_id: int, media_items: List[Dict]) -> Dict:
        """Safely replace Pictova figure captions without moving media blocks.

        This is a repair path, not an upload path: every target must already
        be manifest-managed and present in the current post. The post is
        optimistically checked and read back before the local manifest is
        updated.
        """
        post = self.fetch_post_context(post_id)
        if not post:
            return {"success": False, "error": "Post context could not be loaded"}
        try:
            manifest = load_post_media_manifest(self.site, post_id) or {}
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {"success": False, "error": str(exc)}
        managed_items = list(manifest.get("media_items") or [])
        managed_by_id = {
            int(item.get("media_id") or 0): dict(item)
            for item in managed_items
            if int(item.get("media_id") or 0) > 0
        }
        requested_by_id = {
            int(item.get("media_id") or 0): dict(item)
            for item in media_items
            if int(item.get("media_id") or 0) > 0
        }
        if not requested_by_id:
            return {"success": False, "error": "No managed media items were provided"}
        unknown_ids = sorted(set(requested_by_id) - set(managed_by_id))
        if unknown_ids:
            return {
                "success": False,
                "error": "Caption refresh accepts only manifest-managed media",
                "unknown_media_ids": unknown_ids,
            }
        integrity = assess_post_media(manifest, post.get("content_raw", "") or "")
        if integrity.get("state") != "healthy":
            return {
                "success": False,
                "code": "media_manifest_drift",
                "error": "Post media integrity check failed before caption refresh",
                **integrity,
            }

        refreshed_items: List[Dict] = []
        for item in managed_items:
            media_id = int(item.get("media_id") or 0)
            refreshed = dict(item)
            if media_id in requested_by_id:
                requested = requested_by_id[media_id]
                refreshed["caption"] = str(requested.get("caption") or "").strip()
                refreshed["description"] = str(requested.get("description") or refreshed["caption"] or refreshed.get("alt") or "").strip()
            refreshed_items.append(refreshed)

        captions_by_media_id = {
            media_id: str(requested_by_id[media_id].get("caption") or "").strip()
            for media_id in requested_by_id
        }
        original_content = post.get("content_raw", "") or ""
        updated_content, found_ids = _replace_managed_figure_captions(
            original_content,
            captions_by_media_id,
        )
        missing_ids = sorted(set(captions_by_media_id) - found_ids)
        if missing_ids:
            return {
                "success": False,
                "error": "One or more managed media blocks could not be located for caption refresh",
                "missing_media_ids": missing_ids,
            }

        if updated_content != original_content:
            content_result = self._commit_post_content(
                post_id=post_id,
                original_content=original_content,
                original_modified=post.get("modified", ""),
                new_content=updated_content,
                media_items=refreshed_items,
                inserted=0,
                removed_broken=0,
            )
        else:
            content_result = self._record_verified_media(
                post_id=post_id,
                post=post,
                media_items=refreshed_items,
                updated=False,
                inserted=0,
                removed_broken=0,
            )
        if not content_result.get("success"):
            return content_result

        attachment_updates = []
        for media_id, requested in requested_by_id.items():
            existing = managed_by_id[media_id]
            attachment_updates.append(
                self.update_media_metadata(
                    media_id,
                    title=str(existing.get("title") or "Image"),
                    alt_text=str(existing.get("alt") or ""),
                    caption=str(requested.get("caption") or ""),
                    description=str(requested.get("description") or requested.get("caption") or existing.get("alt") or ""),
                )
            )
        failed_updates = [item for item in attachment_updates if not item.get("success")]
        return {
            **content_result,
            "attachment_updates": attachment_updates,
            "status": "partial" if failed_updates else "success",
        }

    def delete_media(self, media_id: int) -> Dict:
        """Permanently remove a failed Pictova upload during a controlled retry."""
        try:
            resp = self.session.delete(
                f"{self.base_url}/wp-json/wp/v2/media/{int(media_id)}",
                params={"force": "true"},
                timeout=30,
            )
            resp.raise_for_status()
            return {"success": True, "media_id": int(media_id)}
        except requests.exceptions.RequestException as exc:
            return {"success": False, "media_id": int(media_id), "error": str(exc)}

    def remove_managed_media_items(
        self,
        post_id: int,
        media_ids: List[int],
        *,
        delete_attachments: bool = True,
    ) -> Dict:
        """Remove an explicit duplicate subset without touching other media.

        This is deliberately narrower than a post reset: IDs must already be
        Pictova-managed, and a requested image may not share a gallery block
        with a retained item. The content/manifest update is verified before
        its orphaned WordPress attachments are deleted.
        """
        target_ids = {int(media_id) for media_id in media_ids if int(media_id) > 0}
        if not target_ids:
            return {"success": False, "error": "No managed media IDs were provided"}
        post = self.fetch_post_context(post_id)
        if not post:
            return {"success": False, "error": "Post context could not be loaded"}
        try:
            manifest = load_post_media_manifest(self.site, post_id)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {"success": False, "error": str(exc)}
        if not manifest:
            return {"success": False, "error": "Post has no Pictova media manifest"}

        managed_items = list(manifest.get("media_items") or [])
        managed_ids = {int(item.get("media_id") or 0) for item in managed_items}
        unmanaged = sorted(target_ids - managed_ids)
        if unmanaged:
            return {"success": False, "error": "Refusing to remove untracked media", "media_ids": unmanaged}

        current_content = post.get("content_raw", "") or ""
        # Removing one member of a gallery would also remove its retained
        # sibling because Gutenberg nests both blocks. Refuse instead of
        # silently changing that sibling's placement.
        for gallery in re.findall(r"<!-- wp:gallery\b.*?<!-- /wp:gallery -->", current_content, flags=re.S | re.I):
            gallery_ids = {int(value) for value in re.findall(r"wp-image-(\d+)", gallery)}
            if gallery_ids & target_ids and not gallery_ids <= target_ids:
                return {
                    "success": False,
                    "error": "Requested media shares a gallery with retained media",
                    "gallery_media_ids": sorted(gallery_ids),
                }

        cleaned_content, removed_blocks = self._remove_managed_media_blocks(current_content, target_ids)
        if removed_blocks == 0:
            return {"success": False, "error": "Requested managed media blocks were not found"}
        remaining_items = [
            item for item in managed_items
            if int(item.get("media_id") or 0) not in target_ids
        ]
        committed = self._commit_post_content(
            post_id=post_id,
            original_content=current_content,
            original_modified=post.get("modified", ""),
            new_content=cleaned_content,
            media_items=remaining_items,
            inserted=0,
            removed_broken=removed_blocks,
        )
        if not committed.get("success"):
            return {"success": False, "content_update": committed}

        deleted: List[int] = []
        delete_failures: List[Dict] = []
        if delete_attachments:
            for media_id in sorted(target_ids):
                deleted_result = self.delete_media(media_id)
                if deleted_result.get("success"):
                    deleted.append(media_id)
                else:
                    delete_failures.append(deleted_result)
        return {
            "success": True,
            "post_id": post_id,
            "removed_media_ids": sorted(target_ids),
            "removed_blocks": removed_blocks,
            "deleted_media_ids": deleted,
            "delete_failures": delete_failures,
            "content_update": committed,
        }

    def fetch_post_context(self, post_id: int) -> Dict:
        endpoint = f"{self.base_url}/wp-json/wp/v2/posts/{post_id}?context=edit"
        try:
            resp = self.session.get(endpoint, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            excerpt_raw = _extract_post_field(data.get("excerpt", {}), prefer="raw")
            content_raw = _extract_post_field(data.get("content", {}), prefer="raw")
            occupied_headings = [
                {
                    "text": str(item.get("heading") or "").strip(),
                    "level": int(item.get("heading_level") or 0),
                }
                for item in media_items_from_content(content_raw)
                if str(item.get("heading") or "").strip()
            ]
            return {
                "id": post_id,
                "status": str(data.get("status", "")).strip(),
                "modified": str(data.get("modified", "")).strip(),
                "modified_gmt": str(data.get("modified_gmt", "")).strip(),
                "title": html.unescape(data.get("title", {}).get("rendered", "")).strip(),
                "slug": str(data.get("slug", "")).strip(),
                "excerpt": _strip_html(excerpt_raw),
                "content": _strip_html(content_raw)[:2500],
                "content_raw": content_raw,
                "available_headings": _extract_available_headings(content_raw),
                "occupied_headings": occupied_headings,
            }
        except requests.exceptions.RequestException:
            return {}

    def append_media_to_post_content(
        self,
        post_id: int,
        media_items: List[Dict],
        *,
        allow_manifest_repair: bool = False,
        reposition_managed: bool = False,
    ) -> Dict:
        incoming_items = list(media_items)
        post = self.fetch_post_context(post_id)
        if not post:
            return {"success": False, "error": "Post context could not be loaded"}

        current_content = post.get("content_raw", "") or ""
        original_content = current_content
        try:
            manifest = load_post_media_manifest(self.site, post_id)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "success": False,
                "code": "media_manifest_invalid",
                "error": str(exc),
            }
        if manifest and not allow_manifest_repair:
            integrity = assess_post_media(manifest, current_content)
            if integrity["state"] == "drift":
                return {
                    "success": False,
                    "code": "media_manifest_drift",
                    "error": "Pictova-managed media blocks are missing; run guard --repair before attaching new media",
                    **integrity,
                }
            existing_items = list(manifest.get("media_items") or [])
            combined: Dict[int, Dict] = {
                int(item.get("media_id") or 0): item
                for item in existing_items
                if item.get("media_id")
            }
            for item in media_items:
                media_id = int(item.get("media_id") or 0)
                if media_id:
                    combined[media_id] = item
            media_items = list(combined.values())
            existing_heading_keys = {
                (str(item.get("heading") or "").strip().casefold(), int(item.get("heading_level") or 0))
                for item in existing_items
                if str(item.get("heading") or "").strip()
            }
            incoming_heading_keys = {
                (str(item.get("heading") or "").strip().casefold(), int(item.get("heading_level") or 0))
                for item in incoming_items
                if str(item.get("heading") or "").strip()
            }
            # A second image for the same heading must rebuild the managed
            # block as a gallery; the nearby-image guard intentionally blocks
            # simply stacking another singleton figure.
            if existing_heading_keys & incoming_heading_keys:
                reposition_managed = True

        repositioned = 0
        if reposition_managed:
            managed_ids = {
                int(item.get("media_id") or 0)
                for item in media_items
                if item.get("media_id")
            }
            current_content, repositioned = self._remove_managed_media_blocks(
                current_content,
                managed_ids,
            )
            current_content = _remove_auto_media_region(current_content)

        current_content, removed_empty = self._remove_empty_image_blocks(current_content)
        current_content, removed_broken = self._remove_broken_local_image_blocks(current_content)
        removed_broken += removed_empty + repositioned
        has_unanchored_items = any(not str(item.get("heading", "") or "").strip() for item in media_items)
        if has_unanchored_items:
            current_content = _remove_auto_media_region(current_content)

        from collections import defaultdict

        groups = defaultdict(list)
        for item in media_items:
            heading_text = str(item.get("heading", "") or "").strip()
            heading_level = int(item.get("heading_level", 0) or 0)
            groups[(heading_text, heading_level)].append(item)

        auto_blocks: list[str] = []
        placement_failures: list[dict] = []
        inserted = 0

        for (heading_text, heading_level), items in groups.items():
            valid_items = []
            for item in items:
                media_id = item.get("media_id")
                url = item.get("url", "")
                if not media_id or not url:
                    continue
                marker = f"wp-image-{media_id}"
                if marker in current_content or url in current_content:
                    continue
                valid_items.append(item)

            if not valid_items:
                continue

            # The placement policy decides what becomes a gallery; the renderer
            # only honours it. Hardcoding "exactly two" here silently dropped
            # the rare three-image gallery back into stacked single blocks.
            use_gallery = len(valid_items) >= 2 and all(bool(item.get("gallery")) for item in valid_items)
            if not use_gallery:
                # A count is not a gallery request.  Keep images as individual
                # Gutenberg blocks unless the caller explicitly asks for a
                # two-image gallery (normally a deliberate portrait pair).
                image_blocks = []
                for item in valid_items:
                    media_id = item.get("media_id")
                    url = item.get("url", "")
                    alt_text = _escape_attr(item.get("alt", ""))
                    caption = _escape_html(item.get("caption", ""))
                    image_block = (
                        f'<!-- wp:image {{"id":{media_id},"sizeSlug":"full","linkDestination":"none"}} -->\n'
                        f'<figure class="wp-block-image size-full"><img src="{url}" alt="{alt_text}" '
                        f'class="wp-image-{media_id}"/>'
                    )
                    if caption:
                        image_block += f'<figcaption class="wp-element-caption">{caption}</figcaption>'
                    image_blocks.append(image_block + "</figure>\n<!-- /wp:image -->")
                block = "\n\n".join(image_blocks)
            else:
                # Grup wp:gallery
                block = '<!-- wp:gallery {"linkTo":"none"} -->\n'
                block += '<figure class="wp-block-gallery has-nested-images columns-default is-cropped">\n'
                for item in valid_items:
                    media_id = item.get("media_id")
                    url = item.get("url", "")
                    alt_text = _escape_attr(item.get("alt", ""))
                    caption = _escape_html(item.get("caption", ""))
                    block += (
                        f'<!-- wp:image {{"id":{media_id},"sizeSlug":"large","linkDestination":"none"}} -->\n'
                        f'<figure class="wp-block-image size-large"><img src="{url}" alt="{alt_text}" '
                        f'class="wp-image-{media_id}"/>'
                    )
                    if caption:
                        block += f'<figcaption class="wp-element-caption">{caption}</figcaption>'
                    block += "</figure>\n<!-- /wp:image -->\n"
                block += '</figure>\n<!-- /wp:gallery -->'

            if heading_text:
                updated_content = _insert_block_after_heading(
                    current_content,
                    heading_text=heading_text,
                    block_html=block,
                    heading_level=heading_level or None,
                )
                if updated_content != current_content:
                    current_content = updated_content
                    inserted += len(valid_items)
                    continue

                placement_failures.append(
                    {
                        "heading": heading_text,
                        "heading_level": heading_level,
                        "media_ids": [item.get("media_id") for item in valid_items],
                    }
                )
                continue

            auto_blocks.append(block)
            inserted += len(valid_items)

        if placement_failures:
            return {
                "success": False,
                "code": "heading_insertion_failed",
                "error": "Anchored media could not be inserted at its requested heading; no content was changed",
                "placement_failures": placement_failures,
            }

        if not auto_blocks:
            if current_content != original_content or removed_broken:
                return self._commit_post_content(
                    post_id=post_id,
                    original_content=original_content,
                    original_modified=post.get("modified", ""),
                    new_content=current_content,
                    media_items=media_items,
                    inserted=inserted,
                    removed_broken=removed_broken,
                )
            return self._record_verified_media(
                post_id=post_id,
                post=post,
                media_items=media_items,
                updated=False,
                inserted=0,
                removed_broken=removed_broken,
            )

        combined_blocks = AUTO_MEDIA_START + "\n" + "\n\n".join(auto_blocks) + "\n" + AUTO_MEDIA_END
        new_content = _insert_before_first_h2(current_content, combined_blocks)
        return self._commit_post_content(
            post_id=post_id,
            original_content=original_content,
            original_modified=post.get("modified", ""),
            new_content=new_content,
            media_items=media_items,
            inserted=inserted,
            removed_broken=removed_broken,
        )

    def _commit_post_content(
        self,
        *,
        post_id: int,
        original_content: str,
        original_modified: str,
        new_content: str,
        media_items: List[Dict],
        inserted: int,
        removed_broken: int,
    ) -> Dict:
        """Optimistic write followed by a read-after-write integrity check."""
        latest = self.fetch_post_context(post_id)
        if not latest:
            return {"success": False, "error": "Post could not be reloaded before update"}
        if (latest.get("content_raw", "") or "") != original_content:
            return {
                "success": False,
                "code": "post_content_conflict",
                "error": "Post changed while Pictova was preparing media blocks; no content was overwritten",
                "expected_modified": original_modified,
                "current_modified": latest.get("modified", ""),
            }

        endpoint = f"{self.base_url}/wp-json/wp/v2/posts/{post_id}"
        try:
            resp = self.session.post(
                endpoint,
                json={"content": new_content},
                timeout=30,
            )
            resp.raise_for_status()
        except requests.exceptions.RequestException as exc:
            return {"success": False, "error": str(exc)}

        verified = self.fetch_post_context(post_id)
        if not verified:
            return {"success": False, "error": "Post update could not be verified"}
        return self._record_verified_media(
            post_id=post_id,
            post=verified,
            media_items=media_items,
            updated=True,
            inserted=inserted,
            removed_broken=removed_broken,
        )

    def _record_verified_media(
        self,
        *,
        post_id: int,
        post: Dict,
        media_items: List[Dict],
        updated: bool,
        inserted: int,
        removed_broken: int,
    ) -> Dict:
        expected_ids = [int(item.get("media_id") or 0) for item in media_items if item.get("media_id")]
        if not expected_ids:
            return {
                "success": True,
                "updated": updated,
                "inserted": inserted,
                "removed_broken": removed_broken,
            }

        content_raw = post.get("content_raw", "") or ""
        present_ids = {int(value) for value in re.findall(r"wp-image-(\d+)", content_raw)}
        missing_ids = [media_id for media_id in expected_ids if media_id not in present_ids]
        if missing_ids:
            return {
                "success": False,
                "code": "post_update_verification_failed",
                "error": "WordPress accepted the update but expected media blocks are missing",
                "missing_media_ids": missing_ids,
            }

        try:
            manifest = save_post_media_manifest(
                site=self.site,
                post_id=post_id,
                media_items=media_items,
                content_raw=content_raw,
                post_modified=post.get("modified", ""),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "success": False,
                "code": "media_manifest_write_failed",
                "error": str(exc),
            }
        return {
            "success": True,
            "updated": updated,
            "inserted": inserted,
            "removed_broken": removed_broken,
            "manifest_path": manifest["manifest_path"],
            "expected_media_ids": manifest["expected_media_ids"],
        }

    def guard_post_media(
        self,
        post_id: int,
        *,
        repair: bool = False,
        reposition: bool = False,
        adopt: bool = False,
        media_ids: Optional[List[int]] = None,
    ) -> Dict:
        """Check, adopt, or safely reconstruct Pictova-managed media blocks."""
        post = self.fetch_post_context(post_id)
        if not post:
            return {"command": "guard", "status": "failed", "error": "Post context could not be loaded"}

        try:
            manifest = load_post_media_manifest(self.site, post_id)
            if adopt:
                items = media_items_from_content(
                    post.get("content_raw", "") or "",
                    allowed_media_ids=media_ids,
                )
                if not items:
                    return {
                        "command": "guard",
                        "status": "untracked",
                        "state": "untracked",
                        "post_id": post_id,
                        "error": "No media blocks were available to adopt",
                    }
                manifest = save_post_media_manifest(
                    site=self.site,
                    post_id=post_id,
                    media_items=items,
                    content_raw=post.get("content_raw", "") or "",
                    post_modified=post.get("modified", ""),
                )
            if manifest is None:
                return {
                    "command": "guard",
                    "status": "untracked",
                    "state": "untracked",
                    "site": self.site,
                    "post_id": post_id,
                }

            integrity = assess_post_media(manifest, post.get("content_raw", "") or "")
            repaired = False
            if reposition:
                result = self.append_media_to_post_content(
                    post_id,
                    manifest.get("media_items", []),
                    allow_manifest_repair=True,
                    reposition_managed=True,
                )
                if not result.get("success"):
                    return {
                        "command": "guard",
                        "status": "failed",
                        "state": integrity["state"],
                        "site": self.site,
                        "post_id": post_id,
                        "reposition": result,
                        **integrity,
                    }
                post = self.fetch_post_context(post_id)
                manifest = load_post_media_manifest(self.site, post_id) or manifest
                integrity = assess_post_media(manifest, post.get("content_raw", "") or "")
                repaired = integrity["state"] == "healthy"
            if integrity["state"] == "drift" and repair:
                result = self.append_media_to_post_content(
                    post_id,
                    manifest.get("media_items", []),
                    allow_manifest_repair=True,
                )
                if not result.get("success"):
                    return {
                        "command": "guard",
                        "status": "failed",
                        "state": "drift",
                        "site": self.site,
                        "post_id": post_id,
                        "repair": result,
                        **integrity,
                    }
                post = self.fetch_post_context(post_id)
                manifest = load_post_media_manifest(self.site, post_id) or manifest
                integrity = assess_post_media(manifest, post.get("content_raw", "") or "")
                repaired = integrity["state"] == "healthy"

            status = "success" if integrity["state"] in {"healthy", "empty"} else "drift"
            return {
                "command": "guard",
                "status": status,
                "state": integrity["state"],
                "site": self.site,
                "post_id": post_id,
                "repaired": repaired,
                "manifest_path": str(post_media_manifest_path(self.site, post_id)),
                **integrity,
            }
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "command": "guard",
                "status": "failed",
                "state": "invalid",
                "site": self.site,
                "post_id": post_id,
                "error": str(exc),
            }

    def reset_post_media_content(self, post_id: int) -> Dict:
        post = self.fetch_post_context(post_id)
        if not post:
            return {"success": False, "error": "Post context could not be loaded"}

        current_content = post.get("content_raw", "") or ""
        try:
            manifest = load_post_media_manifest(self.site, post_id)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {"success": False, "error": str(exc)}
        managed_ids = set((manifest or {}).get("expected_media_ids") or [])
        cleaned_content, removed_media = self._remove_managed_media_blocks(current_content, managed_ids)
        cleaned_content = _remove_auto_media_region(cleaned_content)

        manifest_path = post_media_manifest_path(self.site, post_id)
        manifest_exists = manifest_path.exists()

        if cleaned_content == current_content:
            if manifest_exists:
                try:
                    manifest_path.unlink()
                except OSError as exc:
                    return {"success": False, "error": str(exc)}
            return {
                "success": True,
                "updated": False,
                "removed_media_blocks": removed_media,
                "manifest_removed": manifest_exists,
            }

        # Same optimistic conflict guard as every other write path: a reset must
        # not silently discard an edit made while it was being prepared.
        committed = self._commit_post_content(
            post_id=post_id,
            original_content=current_content,
            original_modified=post.get("modified", ""),
            new_content=cleaned_content,
            media_items=[],
            inserted=0,
            removed_broken=removed_media,
        )
        if not committed.get("success"):
            return committed
        try:
            if manifest_exists:
                manifest_path.unlink()
        except OSError as e:
            return {"success": False, "error": str(e)}
        return {
            "success": True,
            "updated": True,
            "removed_media_blocks": removed_media,
            "manifest_removed": manifest_exists,
        }

    def _image_is_missing(self, src: str) -> bool:
        """Probe one uploaded image without transferring its bytes."""
        try:
            resp = self.session.get(src, timeout=15, allow_redirects=True, stream=True)
        except requests.exceptions.RequestException:
            return False
        try:
            return resp.status_code == 404
        finally:
            resp.close()

    def _remove_broken_local_image_blocks(self, content: str) -> tuple[str, int]:
        """Drop image blocks whose uploaded file no longer exists.

        Every attach runs this. Probing each block serially inside the re.sub
        callback made a media-heavy post pay N sequential 15s-timeout requests,
        and the old non-streaming GET downloaded each full image just to read
        its status code.
        """
        block_pattern = re.compile(r"<!-- wp:image\b.*?<!-- /wp:image -->\s*", flags=re.S)
        prefix = self.base_url + "/wp-content/uploads/"

        sources: list[str] = []
        for match in block_pattern.finditer(content):
            src_match = re.search(r'<img[^>]+src="([^"]+)"', match.group(0), flags=re.I)
            if src_match and src_match.group(1).startswith(prefix):
                sources.append(src_match.group(1))

        missing: set[str] = set()
        if sources:
            unique_sources = list(dict.fromkeys(sources))
            with ThreadPoolExecutor(max_workers=min(6, len(unique_sources))) as pool:
                for src, is_missing in zip(
                    unique_sources, pool.map(self._image_is_missing, unique_sources)
                ):
                    if is_missing:
                        missing.add(src)

        removed = 0

        def replace_block(match: re.Match[str]) -> str:
            nonlocal removed
            block = match.group(0)
            src_match = re.search(r'<img[^>]+src="([^"]+)"', block, flags=re.I)
            if src_match and src_match.group(1) in missing:
                removed += 1
                return ""
            return block

        cleaned = block_pattern.sub(replace_block, content)
        return cleaned.strip() + ("\n" if cleaned.strip() else ""), removed

    def _remove_empty_image_blocks(self, content: str) -> tuple[str, int]:
        removed = 0

        def replace_block(match: re.Match[str]) -> str:
            nonlocal removed
            block = match.group(0)
            src_match = re.search(
                r'<img\b[^>]*\bsrc\s*=\s*(["\'])(.*?)\1',
                block,
                flags=re.I | re.S,
            )
            if not src_match or not src_match.group(2).strip():
                removed += 1
                return ""
            return block

        cleaned = re.sub(
            r"<!-- wp:image\b.*?<!-- /wp:image -->\s*",
            replace_block,
            content,
            flags=re.S | re.I,
        )
        return cleaned.strip() + ("\n" if cleaned.strip() else ""), removed

    def _remove_managed_media_blocks(self, content: str, media_ids: set[int]) -> tuple[str, int]:
        """Remove only blocks owned by the current Pictova manifest."""
        if not media_ids:
            return content, 0

        markers = {f"wp-image-{media_id}" for media_id in media_ids}
        removed = 0

        def remove_if_managed(match: re.Match[str]) -> str:
            nonlocal removed
            block = match.group(0)
            if any(marker in block for marker in markers):
                removed += 1
                return ""
            return block

        cleaned = re.sub(
            r"<!-- wp:gallery\b.*?<!-- /wp:gallery -->\s*",
            remove_if_managed,
            content,
            flags=re.S | re.I,
        )
        cleaned = re.sub(
            r"<!-- wp:image\b.*?<!-- /wp:image -->\s*",
            remove_if_managed,
            cleaned,
            flags=re.S | re.I,
        )
        cleaned = re.sub(
            re.escape(AUTO_MEDIA_START) + r"\s*" + re.escape(AUTO_MEDIA_END) + r"\s*",
            "",
            cleaned,
            flags=re.I,
        )
        return cleaned.strip() + ("\n" if cleaned.strip() else ""), removed


def _strip_html(value: str) -> str:
    text = re.sub(r"<style[^>]*>.*?</style>", " ", value, flags=re.S | re.I)
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def fetch_post_context(post_id: int, site: str = "yoldaolmak") -> Dict:
    uploader = YOWordPressUploader(site=site)
    return uploader.fetch_post_context(post_id)


def _extract_post_field(value: object, *, prefer: str = "rendered") -> str:
    if isinstance(value, dict):
        preferred = value.get(prefer)
        if isinstance(preferred, str):
            return preferred
        rendered = value.get("rendered")
        if isinstance(rendered, str):
            return rendered
    return str(value or "")


def _escape_attr(value: str) -> str:
    return html.escape(str(value or ""), quote=True)


def _escape_html(value: str) -> str:
    return html.escape(str(value or ""))


def _insert_before_first_h2(content: str, block_html: str) -> str:
    block_match = re.search(
        r"<!-- wp:heading(?:\s+\{.*?\})? -->\s*<h2\b[^>]*>.*?</h2>\s*<!-- /wp:heading -->",
        content,
        flags=re.S | re.I,
    )
    if block_match:
        insert_at = block_match.start()
    else:
        match = re.search(r"<h2\b[^>]*>", content, flags=re.I)
        if not match:
            return content.rstrip() + "\n\n" + block_html + "\n"
        insert_at = match.start()
    prefix = content[:insert_at].rstrip()
    suffix = content[insert_at:].lstrip()
    return prefix + "\n\n" + block_html + "\n\n" + suffix


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_strip_html(value))).strip().lower()


def _leading_gutenberg_block_end(value: str, block_name: str) -> Optional[int]:
    """Return the end of the first block without spanning later blocks."""
    stripped = value.lstrip()
    leading = len(value) - len(stripped)
    open_marker = f"<!-- wp:{block_name}"
    if not stripped.lower().startswith(open_marker.lower()):
        return None
    open_end = stripped.find("-->")
    if open_end < 0:
        return None
    close_marker = f"<!-- /wp:{block_name} -->"
    close_start = stripped.lower().find(close_marker.lower(), open_end + 3)
    if close_start < 0:
        return None
    return leading + close_start + len(close_marker)


def _trailing_gutenberg_block_start(value: str, block_name: str) -> Optional[int]:
    """Return the start of the last block when it ends the value."""
    stripped = value.rstrip()
    close_marker = f"<!-- /wp:{block_name} -->"
    if not stripped.lower().endswith(close_marker.lower()):
        return None
    close_start = len(stripped) - len(close_marker)
    open_marker = f"<!-- wp:{block_name}"
    open_start = stripped.lower().rfind(open_marker.lower(), 0, close_start)
    if open_start < 0:
        return None
    open_end = stripped.find("-->", open_start)
    if open_end < 0 or open_end >= close_start:
        return None
    return open_start


def _has_nearby_image_before(value: str) -> bool:
    stripped = value.rstrip()
    if _trailing_gutenberg_block_start(stripped, "image") is not None:
        return True
    paragraph_start = _trailing_gutenberg_block_start(stripped, "paragraph")
    if paragraph_start is None:
        return False
    return _trailing_gutenberg_block_start(stripped[:paragraph_start], "image") is not None


def _has_nearby_image_after(value: str) -> bool:
    if _leading_gutenberg_block_end(value, "image") is not None:
        return True
    paragraph_end = _leading_gutenberg_block_end(value, "paragraph")
    if paragraph_end is None:
        return False
    return _leading_gutenberg_block_end(value[paragraph_end:], "image") is not None


def _insert_block_after_heading(
    content: str,
    *,
    heading_text: str,
    block_html: str,
    heading_level: Optional[int] = None,
) -> str:
    def _inside_code_like_block(full: str, start: int, end: int) -> bool:
        containers = [
            re.compile(r"<!-- wp:code(?:\s+\{.*?\})? -->.*?<!-- /wp:code -->", flags=re.S | re.I),
            re.compile(r"<!-- wp:preformatted(?:\s+\{.*?\})? -->.*?<!-- /wp:preformatted -->", flags=re.S | re.I),
            re.compile(r"<!-- wp:html(?:\s+\{.*?\})? -->.*?<!-- /wp:html -->", flags=re.S | re.I),
            re.compile(r"<pre\b[^>]*>.*?</pre>", flags=re.S | re.I),
        ]
        for container in containers:
            for block in container.finditer(full):
                if start >= block.start() and end <= block.end():
                    return True
        return False

    pattern = re.compile(
        r"<!-- wp:heading(?:\s+\{.*?\})? -->\s*<h(?P<level>[1-6])\b[^>]*>.*?</h(?P=level)>\s*<!-- /wp:heading -->",
        flags=re.S | re.I,
    )
    target = _normalize_text(heading_text)

    for match in pattern.finditer(content):
        level = int(match.group("level"))
        if heading_level and level != heading_level:
            continue

        heading_block = match.group(0)
        if target not in _normalize_text(heading_block):
            continue
        if _inside_code_like_block(content, match.start(), match.end()):
            continue

        # Guardrail: skip insertion when an image already exists directly
        # above/below the heading, or with only one paragraph gap.
        before = content[: match.start()]
        after = content[match.end() :]
        has_nearby_image_before = _has_nearby_image_before(before)
        has_nearby_image_after = _has_nearby_image_after(after)
        if has_nearby_image_before or has_nearby_image_after:
            continue

        insert_at = match.end()
        prefix = content[:insert_at].rstrip()
        suffix = content[insert_at:].lstrip()
        return prefix + "\n\n" + block_html + "\n\n" + suffix

    return content


def _extract_available_headings(content: str) -> list[dict]:
    """Return eligible, image-free H2/H3 Gutenberg headings.

    A ``Gezilecek Yerler`` section is a structural container, never an image
    target. Its H3 children take precedence; when list items are H2 siblings,
    only consecutively numbered H2 items are eligible.
    """
    heading_pattern = re.compile(
        r"<!-- wp:heading(?:\s+\{.*?\})? -->\s*<h(?P<level>[2-3])\b[^>]*>(?P<inner>.*?)</h(?P=level)>\s*<!-- /wp:heading -->",
        flags=re.S | re.I,
    )
    matches = list(heading_pattern.finditer(content))
    headings = [
        {
            "text": _strip_html(match.group("inner")).strip(),
            "level": int(match.group("level")),
            "match": match,
        }
        for match in matches
    ]

    list_parents = {
        idx for idx, heading in enumerate(headings)
        if heading["level"] == 2
        and re.search(
            r"\b(?:gezilecek\s+yer(?:ler|leri)?|görülmesi\s+gereken\s+yer(?:ler|leri)?)\b",
            heading["text"].casefold(),
        )
    }
    list_targets: set[int] = set()
    for parent_idx in list_parents:
        idx = parent_idx + 1
        while idx < len(headings) and headings[idx]["level"] == 3:
            list_targets.add(idx)
            idx += 1

        idx = parent_idx + 1
        while idx < len(headings):
            heading = headings[idx]
            if heading["level"] == 3:
                idx += 1
                continue
            if not re.match(r"^\s*\d{1,3}\s*[.\-):]", heading["text"]):
                break
            list_targets.add(idx)
            idx += 1

    results = []
    for idx, heading in enumerate(headings):
        if list_parents and idx not in list_targets:
            continue
        match = heading["match"]
        level = heading["level"]
        text = heading["text"]
        if not text:
            continue
        before = content[: match.start()]
        after = content[match.end() :]
        # Reuse the same proximity guards used in _insert_block_after_heading
        has_image_before = _has_nearby_image_before(before)
        has_image_after = _has_nearby_image_after(after)
        if has_image_before or has_image_after:
            continue
        results.append({"text": text, "level": level})
    return results


def _remove_auto_media_region(content: str) -> str:
    cleaned = re.sub(
        re.escape(AUTO_MEDIA_START) + r".*?" + re.escape(AUTO_MEDIA_END) + r"\s*",
        "",
        content,
        flags=re.S,
    )
    return cleaned.strip() + ("\n" if cleaned.strip() else "")


def _rollback_unreferenced_uploads(
    uploader: "YOWordPressUploader",
    post_id: int,
    uploaded: List[Dict],
) -> Dict:
    """Remove this run's uploads when the post never referenced them.

    A failed content update used to leave every uploaded attachment in the
    media library. The manifest is only written after a verified update, so the
    idempotency check could not recognise those attachments either and each
    retry uploaded another copy. Anything the post does reference is kept —
    only a genuinely orphaned upload from this run is deleted.
    """
    post = uploader.fetch_post_context(post_id)
    if not post:
        return {
            "attempted": False,
            "reason": "post could not be reloaded; uploaded media was left untouched",
        }
    referenced = {int(value) for value in re.findall(r"wp-image-(\d+)", post.get("content_raw", "") or "")}
    deleted: List[int] = []
    kept: List[int] = []
    failures: List[Dict] = []
    for item in uploaded:
        media_id = int(item.get("media_id") or 0)
        if not media_id:
            continue
        if media_id in referenced:
            kept.append(media_id)
            continue
        result = uploader.delete_media(media_id)
        if result.get("success"):
            deleted.append(media_id)
        else:
            failures.append(result)
    return {
        "attempted": True,
        "deleted_media_ids": deleted,
        "kept_referenced_media_ids": kept,
        "delete_failures": failures,
    }


def upload_images_batch(
    image_files: List[str],
    metadata_dict: Dict,  # filepath → {alt, title, caption, description}
    post_id: int,
    site: str = "yoldaolmak",
) -> Dict:
    """Upload multiple processed images and attach to post

    Args:
        image_files: list of WebP file paths
        metadata_dict: metadata per file
        post_id: target WordPress post ID
        site: site name (yoldaolmak, gezievreni, etc)

    Returns:
        dict with results
    """
    uploader = YOWordPressUploader(site=site)
    results = {
        "site": site,
        "post_id": post_id,
        "uploaded": [],
        "failed": [],
    }

    guard = uploader.guard_post_media(post_id)
    results["media_guard"] = guard
    if guard.get("status") in {"drift", "failed"}:
        results["failed"].append({
            "error": "Post media integrity check failed before upload",
            "guard": guard,
        })
        return results

    # A repeated Pictova request must be idempotent. The public filename is
    # deterministic from its exact heading, so the manifest can identify the
    # same processed asset before any new WordPress upload is attempted.
    try:
        manifest = load_post_media_manifest(site, post_id) or {}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        results["failed"].append({"error": f"Media manifest could not be read: {exc}"})
        return results
    existing_by_identity = {
        (
            str(item.get("file") or "").strip().casefold(),
            str(item.get("heading") or "").strip().casefold(),
            int(item.get("heading_level") or 0),
        ): item
        for item in manifest.get("media_items", [])
        if item.get("media_id")
    }
    results["skipped"] = []

    for i, file_path in enumerate(image_files, 1):
        print(f"\n[{i}/{len(image_files)}] Uploading: {Path(file_path).name}")

        meta = metadata_dict.get(file_path, {})
        if not meta:
            print(f"  ✗ No metadata found", file=sys.stderr)
            results["failed"].append({
                "file": file_path,
                "error": "No metadata",
            })
            continue

        identity = (
            Path(file_path).name.casefold(),
            str(meta.get("heading") or "").strip().casefold(),
            int(meta.get("heading_level") or 0),
        )
        existing = existing_by_identity.get(identity)
        if existing:
            results["skipped"].append({
                "file": Path(file_path).name,
                "media_id": int(existing["media_id"]),
                "reason": "identical managed file and heading already present",
            })
            continue

        # Upload media
        upload_result = uploader.upload_media(
            file_path=file_path,
            title=meta.get("title", "Image"),
            alt_text=meta.get("alt", ""),
            description=meta.get("description", ""),
            caption=meta.get("caption", ""),
        )

        if not upload_result["success"]:
            print(f"  ✗ Upload failed: {upload_result['error']}")
            results["failed"].append({
                "file": file_path,
                "error": upload_result["error"],
            })
            continue

        media_id = upload_result["media_id"]
        print(f"  ✓ Uploaded: ID {media_id}", file=sys.stderr)

        # Attach to post
        attach_result = uploader.attach_to_post(
            media_id=media_id,
            post_id=post_id,
        )

        if attach_result["success"]:
            print(f"  ✓ Attached to post {post_id}")
            results["uploaded"].append({
                "file": Path(file_path).name,
                "media_id": media_id,
                "post_id": post_id,
                "title": meta.get("title"),
                "alt": meta.get("alt"),
                "caption": meta.get("caption"),
                "heading": meta.get("heading"),
                "heading_level": meta.get("heading_level"),
                "gallery": bool(meta.get("gallery")),
                "url": upload_result.get("url", ""),
            })
        else:
            print(f"  ⚠️  Upload OK but attach failed: {attach_result['error']}")
            results["uploaded"].append({
                "file": Path(file_path).name,
                "media_id": media_id,
                "attach_error": attach_result["error"],
                "caption": meta.get("caption"),
                "title": meta.get("title"),
                "alt": meta.get("alt"),
                "heading": meta.get("heading"),
                "heading_level": meta.get("heading_level"),
                "gallery": bool(meta.get("gallery")),
                "url": upload_result.get("url", ""),
            })

    if not results["uploaded"]:
        results["content_update"] = {
            "success": True,
            "updated": False,
            "inserted": 0,
            "idempotent": bool(results["skipped"]),
        }
        return results

    content_result = uploader.append_media_to_post_content(post_id, results["uploaded"])
    results["content_update"] = content_result
    if content_result.get("success") and content_result.get("updated"):
        print(f"\n✓ Post content updated: {content_result.get('inserted', 0)} image block added")
    elif not content_result.get("success"):
        print(f"\n⚠️  Post content update failed: {content_result.get('error', 'unknown error')}")
        results["rollback"] = _rollback_unreferenced_uploads(uploader, post_id, results["uploaded"])

    return results


if __name__ == "__main__":
    # Test auth
    uploader = YOWordPressUploader(site="yoldaolmak")
    print(f"✓ Connected to {uploader.base_url}")
    print(f"  User: {uploader.user}")
    print("\nReady for image uploads")
