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

def test_created_media_is_deleted_if_metadata_update_fails(tmp_path):
    import requests

    from src.services.wordpress import YOWordPressUploader

    source = tmp_path / "new-image.webp"
    source.write_bytes(b"example file")
    uploader = object.__new__(YOWordPressUploader)
    uploader.base_url = "https://example.test"
    uploader.session = MagicMock()
    created = MagicMock()
    created.raise_for_status.return_value = None
    created.json.return_value = {"id": 712, "source_url": "https://example.test/712.webp"}
    metadata = MagicMock()
    metadata.raise_for_status.side_effect = requests.exceptions.HTTPError("metadata rejected")
    uploader.session.post.side_effect = [created, metadata]
    uploader.delete_media = MagicMock(return_value={"success": True, "media_id": 712})

    result = uploader.upload_media(str(source), title="Kale", alt_text="Kale")
    assert result["success"] is False
    assert result["reverted_media_id"] == 712
    assert "orphaned_media_id" not in result
    uploader.delete_media.assert_called_once_with(712)


def test_metadata_rollback_failure_is_explicit_orphan(tmp_path):
    import requests

    from src.services.wordpress import YOWordPressUploader

    source = tmp_path / "image.webp"
    source.write_bytes(b"example file")
    uploader = object.__new__(YOWordPressUploader)
    uploader.base_url = "https://example.test"
    uploader.session = MagicMock()
    created = MagicMock()
    created.json.return_value = {"id": 719}
    metadata = MagicMock()
    metadata.raise_for_status.side_effect = requests.exceptions.HTTPError("metadata failed")
    uploader.session.post.side_effect = [created, metadata]
    uploader.delete_media = MagicMock(return_value={"success": False, "error": "not allowed"})

    result = uploader.upload_media(str(source), title="Kale", alt_text="Kale")
    assert result["success"] is False
    assert result["orphaned_media_id"] == 719
    assert result["cleanup_error"] == "not allowed"

    from src.pictova.engine.publish_outcome import classify_publish_result

    publish = {
        "uploaded": [], "failed": [result],
        "content_update": {"success": True, "idempotent": False, "inserted": 0},
    }
    assert classify_publish_result(publish) == ("failed", "no_verified_media_placement", True)


def test_unconfirmed_media_http_upload_does_not_claim_no_side_effect(tmp_path):
    import requests

    from src.services.wordpress import YOWordPressUploader

    source = tmp_path / "image.webp"
    source.write_bytes(b"example file")
    uploader = object.__new__(YOWordPressUploader)
    uploader.base_url = "https://example.test"
    uploader.session = MagicMock()
    uploader.session.post.side_effect = requests.exceptions.Timeout("unknown upload state")
    uploader.delete_media = MagicMock()

    result = uploader.upload_media(str(source), title="Kale", alt_text="Kale")
    assert result["success"] is False
    assert result["upload_unconfirmed"] is True
    uploader.delete_media.assert_not_called()


def test_failed_post_association_is_partial_even_if_block_is_inserted(monkeypatch, tmp_path):
    from src.services import wordpress
    from src.pictova.engine.publish_outcome import classify_publish_result

    source = tmp_path / "one.webp"
    source.write_bytes(b"image content")
    uploader = MagicMock()
    uploader.guard_post_media.return_value = {"status": "success"}
    uploader.upload_media.return_value = {
        "success": True, "media_id": 711, "url": "https://example.test/711.webp",
    }
    uploader.attach_to_post.return_value = {
        "success": False, "error": "WordPress association rejected",
    }
    uploader.append_media_to_post_content.return_value = {
        "success": True, "updated": True, "inserted": 1,
    }
    monkeypatch.setattr(wordpress, "YOWordPressUploader", lambda site: uploader)
    monkeypatch.setattr(wordpress, "load_post_media_manifest", lambda site, post_id: None)
    result = wordpress.upload_images_batch(
        image_files=[str(source)],
        metadata_dict={str(source): {"title": "Kale", "alt": "Kale", "heading": "Kale"}},
        site="yoldaolmak", post_id=711,
    )
    assert result["uploaded"][0]["media_id"] == 711
    assert result["failed"][0]["code"] == "post_media_association_failed"
    assert classify_publish_result(result) == ("partial", "verified_with_warnings", True)


def test_managed_media_identity_normalizes_manifest_and_selected_asset_equally():
    from src.services.wordpress import _managed_media_identity

    manifest_identity = _managed_media_identity("  ISPARTA-KOYU.WEBP  ", "  Göl Kenarı  ", "3")
    selection_identity = _managed_media_identity("isparta-koyu.webp", "göl kenarı", 3)

    assert manifest_identity == selection_identity
    assert _managed_media_identity("photo.webp", None, None) == ("photo.webp", "", 0)
