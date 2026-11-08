from src.services.wordpress import _extract_available_headings, _insert_block_after_heading


def _heading_content(tail: str) -> str:
    return '<!-- wp:heading {"level":3} -->\n' "<h3>Demirkazık Tepesi</h3>\n" "<!-- /wp:heading -->\n" f"{tail}"


def test_heading_insertion_does_not_treat_distant_image_as_nearby():
    content = _heading_content(
        "<!-- wp:paragraph --><p>Birinci paragraf</p><!-- /wp:paragraph -->\n"
        "<!-- wp:paragraph --><p>İkinci paragraf</p><!-- /wp:paragraph -->\n"
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
        "<!-- wp:paragraph --><p>Tek paragraf</p><!-- /wp:paragraph -->\n"
        '<!-- wp:image {"id":9} --><figure><img class="wp-image-9"/></figure><!-- /wp:image -->'
    )

    updated = _insert_block_after_heading(
        content,
        heading_text="Demirkazık Tepesi",
        heading_level=3,
        block_html="NEW-IMAGE",
    )

    assert updated == content


def test_previous_peer_heading_image_does_not_block_next_section():
    content = (
        "<!-- wp:heading --><h2>Uçhisar Kalesi</h2><!-- /wp:heading -->"
        '<!-- wp:image {"id":71} --><figure><img class="wp-image-71"/></figure><!-- /wp:image -->'
        "<!-- wp:paragraph --><p>Uçhisar bölümü açıklaması</p><!-- /wp:paragraph -->"
        "<!-- wp:heading --><h2>Avanos Çömlekçiliği</h2><!-- /wp:heading -->"
        "<!-- wp:paragraph --><p>Avanos bölümü açıklaması</p><!-- /wp:paragraph -->"
    )

    available = _extract_available_headings(content)
    assert {"text": "Avanos Çömlekçiliği", "level": 2} in available
    assert {"text": "Uçhisar Kalesi", "level": 2} not in available

    updated = _insert_block_after_heading(
        content,
        heading_text="Avanos Çömlekçiliği",
        heading_level=2,
        block_html=('<!-- wp:image {"id":72} -->' '<figure><img class="wp-image-72"/></figure><!-- /wp:image -->'),
    )

    assert updated != content
    assert updated.index("wp-image-72") > updated.index("Avanos Çömlekçiliği")
    assert updated.index("wp-image-72") < updated.index("Avanos bölümü açıklaması")
    assert _extract_available_headings(updated) == []


def test_image_after_parent_h2_still_blocks_immediate_h3_child():
    content = (
        "<!-- wp:heading --><h2>Gezilecek Yerler</h2><!-- /wp:heading -->"
        '<!-- wp:image {"id":71} --><figure><img class="wp-image-71"/></figure><!-- /wp:image -->'
        "<!-- wp:paragraph --><p>Genel açıklama</p><!-- /wp:paragraph -->"
        '<!-- wp:heading {"level":3} --><h3>Uçhisar Kalesi</h3><!-- /wp:heading -->'
        "<!-- wp:paragraph --><p>Kaleye dair ayrıntı</p><!-- /wp:paragraph -->"
    )

    assert (
        _insert_block_after_heading(
            content,
            heading_text="Uçhisar Kalesi",
            heading_level=3,
            block_html="SECOND-IMAGE",
        )
        == content
    )
    assert {"text": "Uçhisar Kalesi", "level": 3} not in _extract_available_headings(content)
