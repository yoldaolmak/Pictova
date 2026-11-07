"""Publishing must not delete image blocks outside Pictova's ownership."""
from unittest.mock import Mock

from src.services.wordpress import YOWordPressUploader


def test_attach_preserves_unmanaged_broken_url_placeholder_and_post_text(monkeypatch, tmp_path):
    monkeypatch.setenv("PICTOVA_POST_MANIFEST_DIR", str(tmp_path / "manifests"))
    monkeypatch.setitem(
        YOWordPressUploader.SITE_ENDPOINTS,
        "yoldaolmak",
        {"url": "https://example.test", "user": "unit-test", "password": "fake-credential"},
    )
    uploader = YOWordPressUploader()

    old_image = (
        '<!-- wp:image {"id":444} -->\n'
        '<figure class="wp-block-image"><img src="https://example.test/wp-content/uploads/missing.jpg" '
        'class="wp-image-444"/></figure>\n'
        '<!-- /wp:image -->'
    )
    empty_placeholder = (
        '<!-- wp:image {"id":445} -->\n'
        '<figure class="wp-block-image"><img src="" class="wp-image-445"/></figure>\n'
        '<!-- /wp:image -->'
    )
    heading = '<!-- wp:heading -->\n<h2>New section</h2>\n<!-- /wp:heading -->'
    editorial_paragraph = "<!-- wp:paragraph -->\n<p>Preserve this editorial copy exactly.</p>\n<!-- /wp:paragraph -->"
    # Two editorial paragraphs separate the old media from this new section.
    # The existing no-stacking guard must remain effective.
    intro = "<!-- wp:paragraph -->\n<p>Earlier section.</p>\n<!-- /wp:paragraph -->"
    gap = "<!-- wp:paragraph -->\n<p>Independent text.</p>\n<!-- /wp:paragraph -->"
    original = "\n\n".join((old_image, empty_placeholder, intro, gap, heading, editorial_paragraph))

    uploader.session.post = Mock()
    uploader.session.post.return_value.raise_for_status = Mock()
    uploader.fetch_post_context = Mock(
        side_effect=lambda _post_id: {
            "content_raw": (
                uploader.session.post.call_args.kwargs["json"]["content"]
                if uploader.session.post.called
                else original
            ),
            "modified": "2026-11-07T10:00:00",
        }
    )
    uploader._remove_broken_local_image_blocks = Mock(
        side_effect=AssertionError("normal attach must never probe or remove other media")
    )
    uploader._remove_empty_image_blocks = Mock(
        side_effect=AssertionError("normal attach must never delete empty editorial placeholders")
    )

    result = uploader.append_media_to_post_content(
        1234,
        [
            {
                "media_id": 999,
                "url": "https://example.test/wp-content/uploads/new.jpg",
                "heading": "New section",
                "heading_level": 2,
                "alt": "A visible subject",
            }
        ],
    )

    assert result["success"] is True
    assert result["inserted"] == 1
    assert result["removed_broken"] == 0
    published = uploader.session.post.call_args.kwargs["json"]["content"]
    assert old_image in published
    assert empty_placeholder in published
    assert heading in published
    assert editorial_paragraph in published
    assert "wp-image-999" in published
    uploader._remove_broken_local_image_blocks.assert_not_called()
    uploader._remove_empty_image_blocks.assert_not_called()


def test_attach_does_not_rewrite_post_when_image_already_present(monkeypatch, tmp_path):
    monkeypatch.setenv("PICTOVA_POST_MANIFEST_DIR", str(tmp_path / "manifests"))
    monkeypatch.setitem(
        YOWordPressUploader.SITE_ENDPOINTS,
        "yoldaolmak",
        {"url": "https://example.test", "user": "unit-test", "password": "fake-credential"},
    )
    uploader = YOWordPressUploader()
    original = (
        '<!-- wp:image {"id":999} -->'
        '<figure><img src="https://example.test/wp-content/uploads/999.jpg" class="wp-image-999"/></figure>'
        '<!-- /wp:image -->\n'
        '<!-- wp:image {"id":445} --><figure><img src=""/></figure><!-- /wp:image -->'
    )
    uploader.fetch_post_context = Mock(return_value={"content_raw": original, "modified": "2026-11-07"})
    uploader.session.post = Mock(side_effect=AssertionError("no write needed for an already present image"))
    uploader._remove_broken_local_image_blocks = Mock(side_effect=AssertionError("must not probe"))
    uploader._remove_empty_image_blocks = Mock(side_effect=AssertionError("must not remove"))

    result = uploader.append_media_to_post_content(
        1235,
        [{"media_id": 999, "url": "https://example.test/wp-content/uploads/999.jpg"}],
    )

    assert result["success"] is True
    assert result["updated"] is False
    assert result["inserted"] == 0
    uploader.session.post.assert_not_called()
