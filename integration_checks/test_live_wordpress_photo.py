"""Live HTTP smoke test against an ephemeral WordPress + real Commons photo.

Never point this at a production site. A throwaway draft and image are removed
after testing native WebP processing, Gutenberg placement and managed rollback.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.request import Request, urlopen

import pytest
import requests

from src.pictova.engine.processor import process_selected_images
from src.services.wordpress import YOWordPressUploader


PHOTO = "https://upload.wikimedia.org/wikipedia/commons/b/b1/U%C3%A7hisar_Castle_01.jpg"
PHOTO_CREDIT = "Bernard Gagnon / Wikimedia Commons (CC BY-SA); Uçhisar Castle 01.jpg"
ARTICLE = (
    '<!-- wp:paragraph --><p>Original editor text stays untouched.</p><!-- /wp:paragraph -->'
    '<!-- wp:heading {"level":2} --><h2 class="wp-block-heading">Uçhisar Kalesi</h2>'
    '<!-- /wp:heading -->'
    '<!-- wp:paragraph --><p>End of original draft.</p><!-- /wp:paragraph -->'
)


def _real_photo(path: Path) -> None:
    request = Request(PHOTO, headers={"User-Agent": "PictovaIntegration/0.1 (github.com/yoldaolmak/Pictova)"})
    with urlopen(request, timeout=45) as response:
        size = response.headers.get("Content-Length")
        if size and int(size) > 16 * 1024 * 1024:
            pytest.fail("Real Commons photo exceeds test safety bound")
        output = response.read(16 * 1024 * 1024 + 1)
    assert 100_000 < len(output) <= 16 * 1024 * 1024, "Real photo must not be a placeholder"
    path.write_bytes(output)


def test_real_commons_photo_to_live_wordpress_draft_and_guarded_rollback(tmp_path, monkeypatch):
    base = os.environ.get("PICTOVA_SANDBOX_URL", "")
    if base != "http://127.0.0.1:8080":
        pytest.fail("Sandbox must use exactly the ephemeral loopback WordPress port")
    user = os.environ["PICTOVA_SANDBOX_USER"]
    password = os.environ["PICTOVA_SANDBOX_APP_PASSWORD"]
    assert len(password) >= 20

    monkeypatch.setitem(
        YOWordPressUploader.SITE_ENDPOINTS,
        "pictova-ci",
        {"url": base, "user": user, "password": password, "credential_names": "sandbox only"},
    )
    monkeypatch.setenv("PICTOVA_POST_MANIFEST_DIR", str(tmp_path / "managed"))
    wp = YOWordPressUploader(site="pictova-ci")
    assert wp.verify_access()["status"] == "ready", "Real WP Application Password authorization failed"

    post_id = None
    media_id = None
    response = wp.session.post(
        base + "/wp-json/wp/v2/posts",
        json={"title": "Pictova isolated image integration", "status": "draft", "content": ARTICLE},
        timeout=30,
    )
    response.raise_for_status()
    post_id = response.json()["id"]

    try:
        initial = wp.fetch_post_context(post_id)
        assert initial and "Uçhisar Kalesi" in initial["content_raw"]
        assert "Original editor text" in initial["content_raw"]

        photo = tmp_path / "uchisar-commons.jpg"
        _real_photo(photo)
        prepared = process_selected_images([str(photo)], work_dir=str(tmp_path / "processed"))
        files = prepared["processed_images"]
        assert len(files) == 1, prepared
        assert Path(files[0]).is_file()
        assert Path(files[0]).stat().st_size > 10_000

        metadata = {
            "title": "Uçhisar Kalesi",
            "alt": "Kapadokya Uçhisar Kalesi kaya oluşumu",
            "description": PHOTO_CREDIT,
            "caption": PHOTO_CREDIT,
            "heading": "Uçhisar Kalesi",
            "heading_level": 2,
        }
        uploaded = wp.upload_media(
            files[0], metadata["title"], metadata["alt"],
            description=metadata["description"], caption=metadata["caption"],
        )
        assert uploaded["success"], uploaded
        media_id = uploaded["media_id"]

        attached = wp.attach_to_post(media_id, post_id)
        assert attached["success"], attached
        placed = wp.append_media_to_post_content(
            post_id, [{"media_id": media_id, "url": uploaded["url"], "file": Path(files[0]).name, **metadata}]
        )
        assert placed["success"], placed

        committed = wp.fetch_post_context(post_id)
        assert committed
        raw = committed["content_raw"]
        assert f"wp-image-{media_id}" in raw
        assert "Uçhisar Kalesi" in raw
        assert "Original editor text stays untouched." in raw
        assert "End of original draft." in raw

        result = wp.reset_post_media_content(post_id)
        assert result["success"], result
        restored = wp.fetch_post_context(post_id)["content_raw"]
        assert f"wp-image-{media_id}" not in restored
        assert "Original editor text stays untouched." in restored
        assert "End of original draft." in restored
    finally:
        # Never leave a public post or media behind, even on a failed assertion.
        if media_id:
            removed = wp.delete_media(media_id)
            assert removed["success"], removed
        if post_id:
            result = wp.session.delete(
                f"{base}/wp-json/wp/v2/posts/{post_id}", params={"force": "true"}, timeout=30
            )
            result.raise_for_status()
