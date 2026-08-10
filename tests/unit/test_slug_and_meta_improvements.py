"""Yeni iyileştirmeleri kapsayan unit testler:
- build_publish_slug: destinasyon prefix ekleme (gumusluk + bodrum-koy-kayalik)
- _enrich_from_cache: İngilizce scene → Türkçe çeviri
"""
from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# ── build_publish_slug: Destinasyon prefix ────────────────────────────────────

def test_slug_prepends_destination_when_stem_lacks_it(tmp_path):
    """bodrum-koy-kayalik.webp + post='gumusluk-gezilecek-yerler'
    → slug 'gumusluk-bodrum-koy-kayalik' (gumusluk öne eklenmiş)
    """
    from src.core.media_publish import build_publish_slug

    img = tmp_path / "bodrum-koy-kayalik_yo.webp"
    img.write_bytes(b"fake")

    post_context = {
        "title": "Gümüşlük Gezilecek Yerler",
        "slug": "gumusluk-gezilecek-yerler",
    }
    slug = build_publish_slug({}, post_context, str(img))

    assert "gumusluk" in slug, f"Beklenen 'gumusluk', alınan: {slug}"
    tokens = slug.split("-")
    assert tokens[0] == "gumusluk", f"Destinasyon başta olmalı; alınan: {slug}"
    assert len(tokens) <= 5, f"Max 5 token; alınan {len(tokens)}: {slug}"


def test_slug_does_not_double_destination_when_already_present(tmp_path):
    """gumusluk-koy.webp + post=gumusluk-... → gumusluk tekrarlanmamalı."""
    from src.core.media_publish import build_publish_slug

    img = tmp_path / "gumusluk-koy_yo.webp"
    img.write_bytes(b"fake")

    post_context = {"title": "Gümüşlük", "slug": "gumusluk-gezilecek-yerler"}
    slug = build_publish_slug({}, post_context, str(img))

    tokens = slug.split("-")
    assert tokens.count("gumusluk") == 1, (
        f"'gumusluk' yalnızca bir kez bulunmalı; alınan: {slug}"
    )


def test_slug_returns_valid_without_post_context(tmp_path):
    """Post context olmadan da slug üretilmeli; boş veya sadece '-' olmamalı."""
    from src.core.media_publish import build_publish_slug

    img = tmp_path / "xf23kabc_yo.webp"
    img.write_bytes(b"fake")

    slug = build_publish_slug({}, {}, str(img))
    assert slug and "-" in slug, f"Geçersiz slug: {slug!r}"

def test_slug_incorporates_heading_if_present(tmp_path):
    """Metadata içinde heading varsa slug'a dahil olmalı."""
    from src.core.media_publish import build_publish_slug

    img = tmp_path / "sahil-restoran_yo.webp"
    img.write_bytes(b"fake")

    metadata = {"heading": "10. Turgutreis"}
    post_context = {"slug": "bodrum-gezilecek-yerler"}
    
    slug = build_publish_slug(metadata, post_context, str(img))
    
    assert "turgutreis" in slug, f"Heading slug'a eklenmeli: {slug}"
    assert "bodrum" in slug, f"Post slug prefix'i (bodrum) korunmalı: {slug}"
    assert "10" not in slug, f"Numara prefix'leri atılmalı: {slug}"


def test_slug_discards_editorial_headline_filler(tmp_path):
    """Article-title filler must not become a published filename."""
    from src.core.media_publish import build_publish_slug

    img = tmp_path / "karadag-nasil-bir-yer-kisa-atmosfer-atmosfer_yo.webp"
    img.write_bytes(b"fake")
    slug = build_publish_slug(
        {"heading": "Karadağ'a Nasıl Gidilir?"},
        {"slug": "karadag-nasil-bir-yer"},
        str(img),
    )

    assert slug == "karadag-nasil-gidilir"
    assert "atmosfer" not in slug
    assert "kisa" not in slug


def test_slug_keeps_route_entities_not_headline_words(tmp_path):
    """Çeşme → Sakız route remains, while 'en' and suffixes disappear."""
    from src.core.media_publish import build_publish_slug

    img = tmp_path / "en-cesme-den-sakiz-adasi-atmosfer_yo.webp"
    img.write_bytes(b"fake")
    slug = build_publish_slug(
        {"heading": "Çeşme'den Sakız Adası'na Ulaşım"},
        {"slug": "en-cesme-den-sakiz-adasi-ulasim-rehberi"},
        str(img),
    )

    assert slug == "cesme-sakiz-adasi-ulasim"


def test_thematic_post_slug_uses_visual_scene_not_heading_filler(tmp_path):
    from src.core.media_publish import build_publish_slug_candidates

    post_context = {
        "title": "Yalnız Seyahat Rehberi: Yalnız Seyahat Etmek Gerçekten Nasıl Bir Deneyim?",
        "slug": "yalniz-seyahat-etmek",
    }
    street = build_publish_slug_candidates(
        {
            "heading": "Yalnız Seyahat Etmek Gerçekten Nasıl Bir Deneyim?",
            "title": "Yalnız Seyahat Deneyimi: Avrupa Şehrinde",
            "alt": "Dar bir sokakta yukarı bakan genç kadın.",
        },
        post_context,
        str(tmp_path / "deposit_1_yo.webp"),
    )
    planning = build_publish_slug_candidates(
        {
            "heading": "Yalnız Seyahatin En Büyük Avantajları",
            "title": "Yalnız Seyahat Planı: Evden Dünya Keşfi",
            "alt": "Harita ve notlarla dizüstü bilgisayarına bakan kadın.",
        },
        post_context,
        str(tmp_path / "deposit_2_yo.webp"),
    )

    assert street[0] == "yalniz-seyahat-sokak"
    assert planning[0] == "yalniz-seyahat-planlama"


def test_thematic_slug_prefers_specific_street_over_generic_city(tmp_path):
    from src.core.media_publish import build_publish_slug_candidates

    candidates = build_publish_slug_candidates(
        {"alt": "Dar bir şehir sokağında yukarıya doğru bakan bir kadın."},
        {"title": "Yalnız Seyahat Rehberi", "slug": "yalniz-seyahat-etmek"},
        str(tmp_path / "deposit_1_yo.webp"),
    )

    assert candidates[0] == "yalniz-seyahat-sokak"


def test_named_app_heading_gets_short_product_filename(tmp_path):
    from src.core.media_publish import build_publish_slug_candidates

    candidates = build_publish_slug_candidates(
        {"heading": "1. Airbnb", "alt": "Airbnb web sitesi açık dizüstü bilgisayar."},
        {"title": "10 Seyahat Uygulaması", "slug": ""},
        str(tmp_path / "deposit_1_yo.webp"),
    )

    assert candidates[0] == "airbnb-uygulama"


def test_numbered_heading_slug_excludes_editorial_suffix(tmp_path):
    from src.core.media_publish import build_publish_slug_candidates

    candidates = build_publish_slug_candidates(
        {"heading": "3. Antik Tiyatro - Tarihin sahnesine adım atın"},
        {"title": "Ohrid Gezi Rehberi", "slug": ""},
        str(tmp_path / "deposit_1_yo.webp"),
    )

    assert candidates[0] == "antik-tiyatro"
    assert "sahnesine" not in candidates[0]


def test_controlled_retry_reuses_stable_publish_filename(tmp_path, monkeypatch):
    """A stale work artifact must not add generic `-detay` on a retry."""
    from src.pictova.engine import attach

    processed = tmp_path / "processed.webp"
    processed.write_bytes(b"fresh-image")
    stale = tmp_path / "yalniz-seyahat-sokak.webp"
    stale.write_bytes(b"old-image")
    monkeypatch.setattr(attach, "embed_metadata", lambda *_args, **_kwargs: False)

    files, metadata, _details = attach.finalize_publish_assets(
        processed_images=[str(processed)],
        metadata_dict={
            str(processed): {
                "heading": "Yalnız Seyahat Etmek Gerçekten Nasıl Bir Deneyim?",
                "alt": "Dar bir sokakta yukarı bakan genç kadın.",
            }
        },
        processed_details={str(processed): {"input": str(tmp_path / "deposit_1.jpg")}},
        post_context={
            "title": "Yalnız Seyahat Rehberi",
            "slug": "yalniz-seyahat-etmek",
        },
        work_dir=str(tmp_path),
    )

    assert Path(files[0]).name == "yalniz-seyahat-sokak.webp"
    assert Path(files[0]).read_bytes() == b"fresh-image"
    assert metadata[files[0]]["final_slug"] == "yalniz-seyahat-sokak"



# ── _enrich_from_cache: Scene İngilizce → Türkçe çeviri ──────────────────────

def test_enrich_from_cache_translates_english_scene_to_turkish():
    """DB'den 'coast' geldiğinde title/alt Türkçe 'kıyı' içermeli."""
    from src.pictova.engine.metadata import _enrich_from_cache

    cached = {
        "keywords": ["bodrum", "koy"],
        "scene": "coast",
        "activity": "travel",
        "summary": "",
    }
    post_ctx = {"title": "Gümüşlük Gezilecek Yerler"}
    result = _enrich_from_cache(cached, post_ctx)

    assert "coast" not in result["title"].lower(), (
        f"title Türkçe olmalı, 'coast' içermemeli: {result['title']}"
    )
    assert "coast" not in result["alt"].lower(), (
        f"alt Türkçe olmalı, 'coast' içermemeli: {result['alt']}"
    )
    assert "kıyı" in result["title"].lower() or "kıyı" in result["alt"].lower(), (
        f"'kıyı' title veya alt'ta bulunmalı: title={result['title']}, alt={result['alt']}"
    )


def test_enrich_from_cache_uses_turkish_summary_directly():
    """Summary Türkçe ise alt'a doğrudan koymalı."""
    from src.pictova.engine.metadata import _enrich_from_cache

    cached = {
        "keywords": ["bodrum"],
        "scene": "bay",
        "activity": "",
        "summary": "Teknelerin sığındığı sakin bir koy manzarası.",
    }
    post_ctx = {"title": "Gümüşlük"}
    result = _enrich_from_cache(cached, post_ctx)

    assert "Tekneler" in result["alt"], (
        f"Türkçe summary alt'a doğrudan gitmeli: {result['alt']}"
    )


def test_enrich_from_cache_skips_generic_scenes():
    """scene='general' generic → title'da yalnızca lokasyon olmalı."""
    from src.pictova.engine.metadata import _enrich_from_cache

    cached = {
        "keywords": ["bodrum"],
        "scene": "general",
        "activity": "",
        "summary": "",
    }
    post_ctx = {"title": "Bodrum"}
    result = _enrich_from_cache(cached, post_ctx)

    assert result["title"] == "Bodrum", (
        f"Generic scene'de title yalnızca lokasyon olmalı: {result['title']}"
    )


def test_editorial_metadata_policy_removes_cliches_and_limits_copy():
    from src.pictova.engine.metadata import apply_editorial_metadata_policy

    result = apply_editorial_metadata_policy(
        {
            "title": "Büyüleyici Sakız Adası Manzarası",
            "alt": "Harika Sakız kıyısında feribot iskelesi",
            "caption": "Sakız Adası'nın harika ve büyüleyici kıyıları sizi keşfe davet ediyor.",
            "description": "Eşsiz bir atmosfer sunan Sakız Adası kıyısındaki feribot iskelesi.",
            "keywords": ["Sakız", "büyüleyici", "feribot"],
        },
        heading_text="Çeşme'den Sakız Adası'na Ulaşım",
        post_context={"title": "Yakın Yunan Adaları"},
    )

    combined = " ".join(str(result[key]).lower() for key in ("title", "alt", "caption", "description"))
    assert not {"harika", "büyüleyici", "eşsiz", "davet"} & set(combined.replace(".", "").split())
    assert len(result["caption"]) <= 101
    assert len(result["description"]) <= 161


def test_editorial_metadata_uses_article_copy_for_caption_and_keeps_alt_factual():
    from src.pictova.engine.metadata import apply_editorial_metadata_policy

    result = apply_editorial_metadata_policy(
        {
            "title": "Yalnız Seyahat Planı",
            "alt": "Yerde oturan kadın dizüstü bilgisayarına bakıyor, yanında harita ve not defteri var.",
            "caption": "Ev konforunda yalnız seyahat planı yapan genç bir kadın, harita, not defteri ve fotoğraf.",
            "description": "Uzun ve editoryal açıklama.",
        },
        heading_text="Yalnız Seyahat",
        post_context={"title": "Yalnız Seyahat"},
        article_caption="İnsan yalnız seyahatten değil, kendi komutasına geçmekten korkuyor.",
    )

    assert result["alt"] == "Yerde oturan kadın dizüstü bilgisayarına bakıyor, yanında harita ve not defteri var."
    assert result["caption"] == "İnsan yalnız seyahatten değil, kendi komutasına geçmekten korkuyor."
    assert result["description"] == "İnsan yalnız seyahatten değil, kendi komutasına geçmekten korkuyor."


def test_article_caption_map_ignores_existing_figure_caption_and_uses_article_sentence():
    from src.pictova.engine.metadata import build_article_caption_map

    captions = build_article_caption_map(
        ["one.webp"],
        post_context={
            "content_raw": (
                "<p>Otobüste yan koltuk boşsa önce sevinirsin, sonra hafifçe alınır gibi olursun.</p>"
                "<figure><figcaption>Dar bir sokakta duran genç bir kadın yukarı bakıyor.</figcaption></figure>"
                "<!-- wp:heading -->Yalnız Seyahat Bir Romantik Film Değil<!-- /wp:heading -->"
                "<p><strong>Yalnız Seyahat Bir Romantik Film Değil</strong></p>"
                "<p>İnsan yalnız seyahatten değil, kendi komutasına geçmekten korkuyor.</p>"
            ),
        },
    )

    assert captions == {
        "one.webp": "İnsan yalnız seyahatten değil, kendi komutasına geçmekten korkuyor.",
    }


def test_article_caption_candidates_strip_legacy_bold_heading_prefix():
    from src.pictova.engine.metadata import _article_caption_candidates

    candidates = _article_caption_candidates(
        {
            "content_raw": (
                "<p><strong>Yalnız Seyahat Bir Romantik Film Değil</strong> "
                "Yalnız seyahat seni bir film karakterine çevirmez.</p>"
            ),
        },
        "",
    )

    assert candidates == ["Yalnız seyahat seni bir film karakterine çevirmez."]


def test_article_caption_map_uses_the_matched_numbered_h3_section():
    from src.pictova.engine.metadata import build_article_caption_map

    captions = build_article_caption_map(
        ["airbnb.webp"],
        assigned_headings={
            "airbnb.webp": {
                "text": "2. Airbnb - Konaklama seçimi",
                "level": 3,
            },
        },
        post_context={
            "content_raw": (
                "<h3>2. Airbnb - Konaklama seçimi</h3>"
                "<p>Airbnb ile konaklama seçerken iptal koşullarını ilk gün kontrol etmek gerekir.</p>"
                "<h3>3. BlaBlaCar</h3>"
                "<p>Yalnız seyahat egoyu törpüler ama Instagram’daki gibi değil.</p>"
            ),
        },
    )

    assert captions == {
        "airbnb.webp": "Airbnb ile konaklama seçerken iptal koşullarını ilk gün kontrol etmek gerekir.",
    }


def test_editorial_metadata_policy_never_uses_visual_caption_without_article_copy():
    from src.pictova.engine.metadata import apply_editorial_metadata_policy

    result = apply_editorial_metadata_policy(
        {
            "title": "Otel Odasında Bavul Hazırlığı",
            "caption": "Bir kadın yerde oturmuş laptop kullanıyor. Yanında harita, kupa, not defteri, şapka ve fotoğraf makinesi var. Uzun bir ek cümle daha burada yer alıyor.",
        },
        heading_text="Yalnız Seyahat",
        post_context={"title": "Yalnız Seyahat"},
    )

    assert result["caption"] == ""


def test_editorial_metadata_policy_removes_generic_article_title_suffixes():
    from src.pictova.engine.metadata import apply_editorial_metadata_policy

    cases = {
        "Dar Sokakta Yukarı Bakan Kadın - Yalnız Seyahat": "Dar Sokakta Yukarı Bakan Kadın",
        "Otel Odasında Bavul Hazırlığı: Yalnız Seyahat İpuçları": "Otel Odasında Bavul Hazırlığı",
        "Hoi An Çatı Manzarası Yalnız Seyahat Rehberi": "Hoi An Çatı Manzarası",
    }
    for raw_title, expected in cases.items():
        result = apply_editorial_metadata_policy(
            {"title": raw_title, "alt": raw_title},
            heading_text="Yalnız Seyahat Rehberi",
            post_context={"title": "Yalnız Seyahat Rehberi"},
        )
        assert result["title"] == expected
