"""Managed-media repair must preserve editor-owned Gutenberg content."""

from unittest.mock import MagicMock, patch

import pytest

from src.services.wordpress import YOWordPressUploader


def _image(media_id: int) -> str:
    return (
        f'<!-- wp:image {{"id":{media_id}}} -->'
        f'<figure><img src="https://example.test/{media_id}.webp" '
        f'class="wp-image-{media_id}"/></figure>'
        '<!-- /wp:image -->'
    )


def _gallery(*media_ids: int) -> str:
    return (
        '<!-- wp:gallery {"linkTo":"none"} -->'
        '<figure class="wp-block-gallery">'
        + "".join(_image(media_id) for media_id in media_ids)
        + '</figure><!-- /wp:gallery -->'
    )


def _uploader(content: str):
    uploader = object.__new__(YOWordPressUploader)
    uploader.site = "yoldaolmak"
    uploader.fetch_post_context = MagicMock(return_value={
        "content_raw": content, "modified": "2026-11-07T11:00:00",
    })
    uploader._commit_post_content = MagicMock(
        side_effect=AssertionError("mixed-ownership repair must not send a WordPress write")
    )
    return uploader


def test_media_id_match_is_exact_not_a_numeric_prefix():
    uploader = _uploader(_image(123))
    content = _image(123)
    cleaned, removed = uploader._remove_managed_media_blocks(content, {12})
    assert removed == 0
    assert cleaned == content


def test_mixed_gallery_refuses_remove_instead_of_deleting_editor_image():
    uploader = _uploader(_gallery(12, 123))
    with pytest.raises(ValueError, match="untracked images"):
        uploader._remove_managed_media_blocks(_gallery(12, 123), {12})


def test_only_owned_gallery_can_be_removed_without_touching_editor_content():
    uploader = _uploader(_gallery(12, 13))
    editor_image = _image(123)
    original = "Editorial introduction\n" + _gallery(12, 13) + "\n" + editor_image
    cleaned, removed = uploader._remove_managed_media_blocks(original, {12, 13})
    assert removed == 1
    assert "wp:gallery" not in cleaned
    assert editor_image in cleaned
    assert "Editorial introduction" in cleaned


def test_gallery_level_editor_caption_blocks_removal():
    uploader = _uploader(_gallery(12))
    content = _gallery(12).replace(
        '</figure><!-- /wp:gallery -->',
        '<figcaption>Edited gallery caption</figcaption></figure><!-- /wp:gallery -->',
    )
    with pytest.raises(ValueError, match="editorial content"):
        uploader._remove_managed_media_blocks(content, {12})


def test_reposition_mixed_gallery_returns_error_without_any_wordpress_write():
    content = _gallery(12, 123)
    uploader = _uploader(content)
    with patch("src.services.wordpress.load_post_media_manifest", return_value=None):
        result = uploader.append_media_to_post_content(
            7001,
            [{"media_id": 12, "url": "https://example.test/12.webp"}],
            reposition_managed=True,
        )
    assert result["success"] is False
    assert result["code"] == "mixed_media_ownership"
    uploader._commit_post_content.assert_not_called()


def test_reset_mixed_gallery_returns_error_without_any_wordpress_write():
    uploader = _uploader(_gallery(12, 123))
    manifest = {"expected_media_ids": [12], "media_items": [{"media_id": 12}]}
    with patch("src.services.wordpress.load_post_media_manifest", return_value=manifest):
        result = uploader.reset_post_media_content(7001)
    assert result["success"] is False
    assert result["code"] == "mixed_media_ownership"
    uploader._commit_post_content.assert_not_called()
