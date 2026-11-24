"""Live HTTP smoke test against an ephemeral WordPress + real public-domain photo.

Never point this at a production site. A throwaway draft and image are removed
after testing native WebP processing, Gutenberg placement and managed rollback.
"""

from __future__ import annotations

import os
from pathlib import Path
import hashlib

import pytest
import requests

from src.pictova.engine.processor import process_selected_images
from src.services.wordpress import YOWordPressUploader


PHOTO = Path(__file__).with_name("fixtures") / "rocket.jpg"
PHOTO_BLOB = "32bdd33960c60d012fc71b5fd80a7ccc24d3b906"
PHOTO_CREDIT = "SpaceX, public domain; Falcon 9 DSCOVR launch"
ARTICLE = (
    '<!-- wp:paragraph --><p>Original editor text stays untouched.</p><!-- /wp:paragraph -->'
    '<!-- wp:heading {"level":2} --><h2 class="wp-block-heading">Falcon 9 DSCOVR launch</h2>'
    '<!-- /wp:heading -->'
    '<!-- wp:paragraph --><p>End of original draft.</p><!-- /wp:paragraph -->'
)


def _real_photo(path: Path) -> None:
    output = PHOTO.read_bytes()
    assert 100_000 < len(output) <= 16 * 1024 * 1024
    git_object = b"blob " + str(len(output)).encode("ascii") + b"\0" + output
    assert hashlib.sha1(git_object).hexdigest() == PHOTO_BLOB
    path.write_bytes(output)


def test_real_photo_to_live_wordpress_draft_and_guarded_rollback(tmp_path, monkeypatch):
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
        assert initial and "Falcon 9 DSCOVR launch" in initial["content_raw"]
        assert "Original editor text" in initial["content_raw"]

        photo = tmp_path / "launch.jpg"
        _real_photo(photo)
        prepared = process_selected_images([str(photo)], work_dir=str(tmp_path / "processed"))
        files = prepared["processed_images"]
        assert len(files) == 1, prepared
        assert Path(files[0]).is_file()
        assert Path(files[0]).stat().st_size > 10_000

        metadata = {
            "title": "Falcon 9 DSCOVR launch",
            "alt": "Falcon 9 on the launch pad at Cape Canaveral",
            "description": PHOTO_CREDIT,
            "caption": PHOTO_CREDIT,
            "heading": "Falcon 9 DSCOVR launch",
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
        assert "Falcon 9 DSCOVR launch" in raw
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
        try:
            if media_id:
                removed = wp.delete_media(media_id)
                assert removed["success"], removed
        finally:
            if post_id:
                result = wp.session.delete(
                    f"{base}/wp-json/wp/v2/posts/{post_id}", params={"force": "true"}, timeout=30
                )
                result.raise_for_status()
