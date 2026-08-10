from __future__ import annotations

from src.pictova.engine.quality import validate_native_metadata
from src.core.media_quality import validate_processed_asset


def test_validate_native_metadata_rejects_context_mismatch():
    metadata = {
        "title": "Dağ Yolu Manzarası",
        "alt": "Dağ eteklerinde taş patika ve uzak tepeler",
        "caption": "Yürüyüş rotasında sakin bir dağ yolu görünümü.",
        "description": "Doğal bir yürüyüş parkurunu gösteren sade bir manzara.",
        "keywords": ["dağ", "patika", "manzara"],
        "heading": "Liman İşlemleri ve Esnek Bilet Kuralları",
    }
    post_context = {
        "title": "Yaz Tatilinde Kaçabileceğiniz 4 Yakın Yunan Adası: Ulaşım ve Geçiş Tavsiyelerim",
        "slug": "en-yakin-yunan-adalari-ulasim-rehberi",
    }

    errors = validate_native_metadata(metadata, post_context)

    assert "metadata does not match heading or post context" in errors


def test_validate_native_metadata_accepts_context_match():
    metadata = {
        "title": "Liman Bilet Kontrolü",
        "alt": "Liman girişinde bilet kontrolü yapılan düzenli feribot akışı",
        "caption": "Liman işlemleri sırasında bilet kontrolü ve feribot geçişi.",
        "description": "Liman ve bilet sürecine dair düzenli bir geçiş karesi.",
        "keywords": ["liman", "bilet", "feribot"],
        "heading": "Liman İşlemleri ve Esnek Bilet Kuralları",
    }
    post_context = {
        "title": "Yaz Tatilinde Kaçabileceğiniz 4 Yakın Yunan Adası: Ulaşım ve Geçiş Tavsiyelerim",
        "slug": "en-yakin-yunan-adalari-ulasim-rehberi",
    }

    errors = validate_native_metadata(metadata, post_context)

    assert "metadata does not match heading or post context" not in errors
    assert "metadata is too loosely connected to the post context" not in errors


def test_validate_native_metadata_requires_explicit_selected_entity():
    metadata = {
        "title": "Seyahat Uygulaması Ekranı",
        "alt": "Akıllı telefonda açık bir seyahat uygulaması ekranı",
        "caption": "Akıllı telefonda seyahat uygulaması ekranı.",
        "description": "Akıllı telefonda açık seyahat uygulaması ekranı görünümü.",
        "keywords": ["uygulama", "telefon", "seyahat"],
        "heading": "2. BlaBlaCar",
        "required_heading_tokens": ["blablacar"],
    }

    errors = validate_native_metadata(metadata, {"title": "Seyahat Uygulamaları", "slug": "seyahat-uygulamalari"})

    assert "metadata is missing an exact assigned-heading entity" in errors


def test_validate_native_metadata_rejects_app_heading_without_visual_brand_evidence():
    metadata = {
        "title": "Tinder Uygulaması",
        "alt": "Sahilde salıncakta sallanan bir kadın.",
        "caption": "Yalnız seyahat kendi komutasına geçmektir.",
        "description": "Sahilde salıncakta sallanan bir kadının görünümü.",
        "keywords": ["sahil", "salıncak", "kadın"],
        "heading": "7. Tinder",
        "required_heading_tokens": ["tinder"],
        "visual_evidence": "Sahilde salıncakta sallanan bir kadın, palmiye ve kum.",
    }

    errors = validate_native_metadata(
        metadata,
        {"title": "Kendinizi Yerli Gibi Hissedeceğiniz 10 Seyahat Uygulaması", "slug": "seyahat-uygulamalari"},
    )

    assert "visual evidence does not confirm exact assigned-heading entity" in errors


def test_validate_native_metadata_accepts_app_heading_when_brand_is_visibly_confirmed():
    metadata = {
        "title": "Tinder Uygulaması",
        "alt": "Akıllı telefonda açık Tinder uygulaması ekranı.",
        "caption": "Yalnız seyahat kendi komutasına geçmektir.",
        "description": "Akıllı telefonda açık Tinder uygulaması ekranı görünümü.",
        "keywords": ["tinder", "telefon", "uygulama"],
        "heading": "7. Tinder",
        "required_heading_tokens": ["tinder"],
        "visual_evidence": "Akıllı telefonda açık Tinder uygulaması ekranı ve Tinder logosu.",
    }

    errors = validate_native_metadata(
        metadata,
        {"title": "Kendinizi Yerli Gibi Hissedeceğiniz 10 Seyahat Uygulaması", "slug": "seyahat-uygulamalari"},
    )

    assert "visual evidence does not confirm exact assigned-heading entity" not in errors


def test_validate_processed_asset_allows_cool_travel_scenes():
    process_info = {
        "final_size": (1200, 750),
        "brightness": 0.52,
        "saturation": 0.38,
        "contrast": 0.22,
        "color_temp": 0.43,
        "file_size_kb": 128,
        "blur_score": 860,
        "original_size": (2400, 1600),
    }

    errors = validate_processed_asset({}, process_info)

    assert "color temperature inconsistent" not in errors


def test_validate_processed_asset_allows_warm_historic_interiors():
    process_info = {
        "final_size": (1200, 750),
        "brightness": 0.44,
        "saturation": 0.54,
        "contrast": 0.20,
        "color_temp": -0.325,
        "file_size_kb": 67,
        "blur_score": 630,
        "original_size": (5983, 3989),
    }

    errors = validate_processed_asset({}, process_info)

    assert "color temperature inconsistent" not in errors


def test_validate_processed_asset_allows_warm_verified_cave_interior_only():
    process_info = {
        "final_size": (1200, 750), "brightness": 0.35, "saturation": 0.64,
        "contrast": 0.23, "color_temp": -0.42, "file_size_kb": 70,
        "blur_score": 350, "original_size": (1600, 1200),
    }

    assert "color temperature inconsistent" not in validate_processed_asset(
        {"title": "Dupnisa Mağarası iç galerileri"}, process_info,
    )
    assert "color temperature inconsistent" in validate_processed_asset(
        {"title": "Sahil manzarası"}, process_info,
    )


def test_validate_native_metadata_rejects_promotional_signs():
    metadata = {
        "title": "Samos Büfe Fiyatları ve Menüsü",
        "alt": "Büfe yemekleri ve fiyatlarını gösteren reklam panosu.",
        "caption": "Samos Adası'nda uygun fiyatlı büfe reklam tabelası.",
        "description": "Samos'ta bir restoranın menü ve fiyatlarını gösteren pano.",
        "summary": "Samos Adası'nda uygun fiyatlı büfe reklam tabelası.",
        "scene": "Street in a town",
        "activity": "Dining promotion",
        "keywords": ["reklam", "tabela", "fiyat"],
        "heading": "3. Kuşadası’ndan Samos’a Kaçış",
    }
    post_context = {
        "title": "Yaz Tatilinde Kaçabileceğiniz 4 Yakın Yunan Adası: Ulaşım ve Geçiş Tavsiyelerim",
        "slug": "en-yakin-yunan-adalari-ulasim-rehberi",
    }

    errors = validate_native_metadata(metadata, post_context)

    assert "metadata looks promotional or editorially noisy" in errors


def test_validate_native_metadata_allows_contextual_signage():
    metadata = {
        "title": "Sınır Kapısında Pasaport Kontrolü",
        "alt": "Sınır kapısındaki yön tabelası ve pasaport kontrol noktası",
        "caption": "Sınır kapısında pasaport kontrolüne yönlendiren tabela.",
        "description": "Pasaport kontrol alanını ve sınır kapısındaki yön tabelasını gösteren kare.",
        "keywords": ["sınır", "pasaport", "kontrol", "tabela"],
        "heading": "Sınır Kapısında Pasaport Kontrolü",
    }
    errors = validate_native_metadata(
        metadata,
        {"title": "Sınır Kapısında Pasaport Kontrolü", "slug": "sinir-kapisi"},
    )
    assert "metadata looks promotional or editorially noisy" not in errors


def test_validate_processed_asset_accepts_compact_house_style_webp():
    process_info = {
        "final_size": (1200, 750),
        "brightness": 0.60,
        "saturation": 0.11,
        "contrast": 0.15,
        "color_temp": 0.01,
        "file_size_kb": 22,
        "blur_score": 300,
        "original_size": (2400, 1600),
    }
    errors = validate_processed_asset({}, process_info)
    assert "saturation out of editorial range" not in errors
    assert "file too compressed" not in errors


def test_validate_native_metadata_accepts_cross_language_luggage_match():
    metadata = {
        "title": "Kabin Valizi Seçimi",
        "alt": "Uçuş için hazırlanmış kabin boy valiz",
        "caption": "Kabin valizi ve seyahat eşyaları.",
        "description": "Uçakta taşınmaya uygun kabin boy valizin görünümü.",
        "keywords": ["valiz", "kabin", "uçuş"],
        "heading": "Giyilebilir Bagaj (Wearable Luggage)",
    }
    errors = validate_native_metadata(metadata, {"title": "Kabin Bagajı Kuralları", "slug": "kabin-bagaji"})
    assert "metadata does not match heading or post context" not in errors


def test_native_metadata_allows_price_word_in_price_article():
    metadata = {
        "title": "Valiz Modelleri ve Fiyat Karşılaştırması",
        "alt": "Mağazada farklı boyutlarda valiz modelleri",
        "caption": "Farklı valiz modellerinin fiyat ve boyut karşılaştırması.",
        "description": "Mağazada satışta bulunan farklı boyut ve renklerde valizler.",
        "keywords": ["valiz", "fiyat", "model"],
        "heading": "Valiz Markaları ve Fiyatları",
    }
    errors = validate_native_metadata(metadata, {"title": "En İyi Valiz Markaları ve Fiyatları", "slug": "valiz-fiyatlari"})
    assert "metadata looks promotional or editorially noisy" not in errors


def test_native_metadata_may_match_post_when_heading_is_abstract():
    metadata = {
        "title": "Amsterdam Red Light District Gece Sokağı",
        "alt": "Amsterdam Red Light District bölgesinde kırmızı neonlu gece sokağı",
        "caption": "De Wallen bölgesindeki kırmızı ışıklı gece sokağı.",
        "description": "Amsterdam Red Light District içinde gece aydınlatılan tarihi sokak.",
        "keywords": ["Amsterdam", "Red Light District", "De Wallen"],
        "heading": "İlk Kez Gidenler Ne Hisseder?",
    }
    errors = validate_native_metadata(metadata, {"title": "Red Light District Amsterdam Rehberi", "slug": "red-light-district-amsterdam"})
    assert "metadata does not match heading or post context" not in errors
