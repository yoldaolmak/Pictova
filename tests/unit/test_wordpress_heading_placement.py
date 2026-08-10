from src.services.wordpress import _insert_block_after_heading


def _heading_content(tail: str) -> str:
    return (
        '<!-- wp:heading {"level":3} -->\n'
        '<h3>Demirkazık Tepesi</h3>\n'
        '<!-- /wp:heading -->\n'
        f'{tail}'
    )


def test_heading_insertion_does_not_treat_distant_image_as_nearby():
    content = _heading_content(
        '<!-- wp:paragraph --><p>Birinci paragraf</p><!-- /wp:paragraph -->\n'
        '<!-- wp:paragraph --><p>İkinci paragraf</p><!-- /wp:paragraph -->\n'
        '<!-- wp:image {"id":9} --><figure><img class="wp-image-9"/></figure><!-- /wp:image -->'
    )

    updated = _insert_block_after_heading(
        content,
        heading_text="Demirkazık Tepesi",
        heading_level=3,
        block_html="NEW-IMAGE",
    )

    assert updated != content
    assert updated.index("NEW-IMAGE") < updated.index("Birinci paragraf")


def test_heading_insertion_still_blocks_image_after_one_paragraph():
    content = _heading_content(
        '<!-- wp:paragraph --><p>Tek paragraf</p><!-- /wp:paragraph -->\n'
        '<!-- wp:image {"id":9} --><figure><img class="wp-image-9"/></figure><!-- /wp:image -->'
    )

    updated = _insert_block_after_heading(
        content,
        heading_text="Demirkazık Tepesi",
        heading_level=3,
        block_html="NEW-IMAGE",
    )

    assert updated == content
