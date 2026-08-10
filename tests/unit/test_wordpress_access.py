from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_verify_access_reports_rejected_credentials_without_secret():
    from src.services.wordpress import YOWordPressUploader

    class Response:
        status_code = 401

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    uploader = object.__new__(YOWordPressUploader)
    uploader.base_url = "https://example.test"
    uploader.session = Session()

    assert uploader.verify_access() == {"status": "rejected", "http_status": 401}


def test_resolve_post_site_reports_auth_rejection_instead_of_not_found(monkeypatch):
    from src.pictova.providers import wordpress

    monkeypatch.setattr(wordpress, "fetch_post_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        wordpress.YOWordPressUploader,
        "SITE_ENDPOINTS",
        {"gezgindunyasi": {"url": "https://example.test", "user": "pictova", "password": "set"}},
    )
    monkeypatch.setattr(
        wordpress.YOWordPressUploader,
        "check_site_access",
        classmethod(lambda cls, site: {"status": "rejected", "http_status": 401}),
    )

    with pytest.raises(ValueError, match=r"authentication rejected: gezgindunyasi \(HTTP 401\)"):
        wordpress.resolve_post_site(34853, site="auto")


def test_upload_batch_skips_existing_managed_file_and_heading(tmp_path, monkeypatch):
    from src.services.post_media_guard import save_post_media_manifest
    from src.services import wordpress

    monkeypatch.setenv("PICTOVA_POST_MANIFEST_DIR", str(tmp_path / "manifests"))
    image = tmp_path / "airbnb-uygulama.webp"
    image.write_bytes(b"already managed")
    content = '<img class="wp-image-42" src="https://example.test/airbnb.webp"/>'
    save_post_media_manifest(
        site="gezgindunyasi",
        post_id=34661,
        media_items=[{
            "media_id": 42,
            "url": "https://example.test/airbnb.webp",
            "file": image.name,
            "heading": "1. Airbnb",
            "heading_level": 3,
        }],
        content_raw=content,
    )
    uploader = MagicMock()
    uploader.guard_post_media.return_value = {"status": "success"}
    monkeypatch.setattr(wordpress, "YOWordPressUploader", lambda site: uploader)

    result = wordpress.upload_images_batch(
        image_files=[str(image)],
        metadata_dict={str(image): {"heading": "1. Airbnb", "heading_level": 3}},
        post_id=34661,
        site="gezgindunyasi",
    )

    assert result["uploaded"] == []
    assert result["skipped"] == [{
        "file": image.name,
        "media_id": 42,
        "reason": "identical managed file and heading already present",
    }]
    assert result["content_update"]["idempotent"] is True
    uploader.upload_media.assert_not_called()


def test_replace_managed_figure_captions_touches_only_requested_media():
    from src.services.wordpress import _replace_managed_figure_captions

    content = (
        '<!-- wp:image {"id":42} -->\n'
        '<figure><img class="wp-image-42"/><figcaption>Eski açıklama.</figcaption></figure>\n'
        '<!-- /wp:image -->\n'
        '<!-- wp:image {"id":43} -->\n'
        '<figure><img class="wp-image-43"/><figcaption>Korunacak açıklama.</figcaption></figure>\n'
        '<!-- /wp:image -->'
    )

    updated, found = _replace_managed_figure_captions(
        content,
        {42: "İnsan yalnız seyahatten değil, kendi komutasına geçmekten korkuyor."},
    )

    assert found == {42}
    assert "İnsan yalnız seyahatten değil, kendi komutasına geçmekten korkuyor." in updated
    assert "Korunacak açıklama." in updated


def test_refresh_managed_media_captions_preserves_positions_and_updates_attachment(tmp_path, monkeypatch):
    from src.services.post_media_guard import save_post_media_manifest
    from src.services.wordpress import YOWordPressUploader

    monkeypatch.setenv("PICTOVA_POST_MANIFEST_DIR", str(tmp_path / "manifests"))
    content = (
        '<!-- wp:image {"id":42} -->\n'
        '<figure><img class="wp-image-42" src="https://example.test/solo.webp" alt="Dar sokak"/>'
        '<figcaption>Dar bir sokakta duran kadın.</figcaption></figure>\n'
        '<!-- /wp:image -->'
    )
    managed = {
        "media_id": 42,
        "url": "https://example.test/solo.webp",
        "file": "yalniz-seyahat.webp",
        "title": "Yalnız Seyahat",
        "alt": "Dar sokakta duran kadın.",
        "caption": "Dar bir sokakta duran kadın.",
        "heading": "",
        "heading_level": 0,
    }
    save_post_media_manifest(
        site="gezgindunyasi",
        post_id=88,
        media_items=[managed],
        content_raw=content,
    )
    uploader = object.__new__(YOWordPressUploader)
    uploader.site = "gezgindunyasi"
    uploader.fetch_post_context = MagicMock(return_value={"content_raw": content, "modified": "2026-08-05T12:00:00"})
    uploader._commit_post_content = MagicMock(return_value={"success": True, "updated": True})
    uploader.update_media_metadata = MagicMock(return_value={"success": True, "media_id": 42})

    result = uploader.refresh_managed_media_captions(
        88,
        [{
            **managed,
            "caption": "İnsan yalnız seyahatten değil, kendi komutasına geçmekten korkuyor.",
            "description": "İnsan yalnız seyahatten değil, kendi komutasına geçmekten korkuyor.",
        }],
    )

    assert result["status"] == "success"
    assert "İnsan yalnız seyahatten değil, kendi komutasına geçmekten korkuyor." in uploader._commit_post_content.call_args.kwargs["new_content"]
    uploader.update_media_metadata.assert_called_once_with(
        42,
        title="Yalnız Seyahat",
        alt_text="Dar sokakta duran kadın.",
        caption="İnsan yalnız seyahatten değil, kendi komutasına geçmekten korkuyor.",
        description="İnsan yalnız seyahatten değil, kendi komutasına geçmekten korkuyor.",
    )
