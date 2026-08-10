"""selector.py unit testleri."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request

import pytest


def test_extract_location_from_slug():
    from src.pictova.engine.selector import _extract_location
    assert _extract_location({"slug": "antalya-kalkan-koyu"}) == "antalya kalkan koyu"


def test_extract_location_from_title():
    from src.pictova.engine.selector import _extract_location
    assert _extract_location({"title": "Sinop Gezisi"}) == "Sinop Gezisi"


def test_extract_location_slug_wins_over_title():
    from src.pictova.engine.selector import _extract_location
    result = _extract_location({"slug": "sinop-kalesi", "title": "Anything"})
    assert result == "sinop kalesi"


def test_primary_post_tokens_preserve_turkish_capital_i_and_drop_generic_words():
    from src.pictova.engine.selector import _primary_post_tokens

    assert _primary_post_tokens({"title": "İstanbul Gezilecek Yerler Rehberi -OK!"}) == {"istanbul"}


def test_primary_post_query_keeps_thematic_pair_not_title_filler():
    from src.pictova.engine.selector import _primary_post_query

    assert _primary_post_query({
        "slug": "yalniz-seyahat-etmek",
        "title": "Yalnız Seyahat Rehberi: Yalnız Seyahat Etmek Gerçekten Nasıl Bir Deneyim?",
    }) == "yalniz seyahat"


def test_numbered_h3_entity_excludes_editorial_suffix():
    from src.pictova.engine.selector import _numbered_entity_text, _numbered_entity_tokens

    heading = {"text": "1. Ohrid Gölü - Balkanların en eski ve derin gölü", "level": 3}

    assert _numbered_entity_text(heading) == "Ohrid Gölü"
    assert _numbered_entity_tokens(heading) == {"ohrid"}


def test_heading_search_query_excludes_plain_hyphen_editorial_suffix():
    from src.pictova.engine.selector import _heading_to_search_query

    # The country is no longer appended: the post supplies its own geography.
    assert _heading_to_search_query("1. Ohrid Gölü - Balkanların en eski gölü") == "Ohrid lake"


def test_heading_provider_tokens_translate_generic_entity_words():
    from src.pictova.engine.selector import _numbered_provider_tokens

    theatre = {"text": "3. Antik Tiyatro - Tarihin sahnesi", "level": 3}

    # Common nouns still translate; the proper noun stays as written.
    assert _numbered_provider_tokens(theatre) == {"ancient", "theater"}
    # "kalesi" is a non-specific geographic word and is dropped; the proper
    # noun is what actually anchors the asset.
    assert _numbered_provider_tokens(
        {"text": "4. Samuil Kalesi - Şehrin koruyucusu", "level": 3}
    ) == {"samuil"}


def test_derive_location_query_skips_generic_slug_tokens():
    from src.pictova.engine.attach import derive_location_query

    result = derive_location_query({
        "slug": "en-yakin-yunan-adalari-ulasim-rehberi",
        "title": "Yaz Tatilinde Kaçabileceğiniz 4 Yakın Yunan Adası",
    })

    assert result == "yunan"


def test_heading_to_semantic_query_prefers_destination_token():
    from src.pictova.engine.selector import _heading_to_semantic_query

    assert _heading_to_semantic_query("2. Bodrum’dan Kos’a Kaçış") == "Kos"


@pytest.mark.xfail(reason="Adım 2 (semantik katman) bekliyor: destinasyon/çapraz-dil sözlükleri kaldırıldı, yerine öğrenilmiş eşleşme gelecek", strict=True)
def test_resolve_source_images_semantic_uses_heading_queries():
    from src.pictova.engine.selector import resolve_source_images

    def fake_search(*, location_query, count, content_filter, post_context, include_icloud=False):
        mapping = {
            "Kos": ["/kos.jpg"],
            "Samos": ["/samos.jpg"],
            "Chios": ["/chios.jpg"],
            "yunan": ["/generic.jpg"],
        }
        return mapping.get(location_query, [])

    rows = {
        "/kos.jpg": {
            "title": "Kos Harbour",
            "location": "Kos",
            "city": "Kos",
            "state_province": "",
            "country": "Greece",
            "scene": "harbor",
            "activity": "sightseeing",
            "summary": "Kos Harbour",
            "description": "Kos Harbour",
            "ai_keywords_json": "[\"kos\", \"harbor\"]",
            "apple_labels_json": "[\"harbor\", \"boat\"]",
        },
        "/samos.jpg": {
            "title": "Samos Bay",
            "location": "Samos",
            "city": "Samos",
            "state_province": "",
            "country": "Greece",
            "scene": "bay",
            "activity": "sightseeing",
            "summary": "Samos Bay",
            "description": "Samos Bay",
            "ai_keywords_json": "[\"samos\", \"bay\"]",
            "apple_labels_json": "[\"bay\", \"sea\"]",
        },
        "/chios.jpg": {
            "title": "Chios Island",
            "location": "Chios",
            "city": "Chios",
            "state_province": "",
            "country": "Greece",
            "scene": "island",
            "activity": "sightseeing",
            "summary": "Chios Island",
            "description": "Chios Island",
            "ai_keywords_json": "[\"chios\", \"island\"]",
            "apple_labels_json": "[\"island\", \"sea\"]",
        },
    }

    post_context = {
        "available_headings": [
            {"text": "2. Bodrum’dan Kos’a Kaçış", "level": 2},
            {"text": "3. Kuşadası’ndan Samos’a Kaçış", "level": 2},
            {"text": "4. Çeşme’den Sakız Adası’na Kaçış", "level": 2},
        ]
    }

    with patch("src.pictova.engine.selector.search_semantic_assets", side_effect=fake_search), \
         patch("src.pictova.engine.selector._candidate_metadata_row", side_effect=lambda candidate: rows[candidate]):
        result = resolve_source_images(
            source="semantic",
            count=3,
            name=None,
            query=None,
            location_query="yunan",
            content_filter=None,
            post_context=post_context,
        )

    assert result["files"] == ["/kos.jpg", "/samos.jpg", "/chios.jpg"]
    assert result["heading_assignments"]["/kos.jpg"]["text"] == "2. Bodrum’dan Kos’a Kaçış"


def test_auto_selection_returns_exact_heading_assignments(monkeypatch):
    from src.pictova.engine import selector

    headings = [
        {"text": "1. Airbnb", "level": 3},
        {"text": "2. BlaBlaCar", "level": 3},
    ]
    monkeypatch.setattr(
        selector,
        "_heading_specific_selection",
        lambda **_kwargs: (
            ["/airbnb.jpg", "/blablacar.jpg"],
            {"/airbnb.jpg": headings[0], "/blablacar.jpg": headings[1]},
        ),
    )

    result = selector.resolve_source_images(
        source="auto",
        count=2,
        name=None,
        query=None,
        location_query=None,
        content_filter=None,
        post_context={"title": "Uygulamalar", "available_headings": headings},
    )

    assert result["files"] == ["/airbnb.jpg", "/blablacar.jpg"]
    assert result["heading_assignments"]["/airbnb.jpg"]["text"] == "1. Airbnb"


def test_heading_selection_skips_sections_that_already_have_an_image(monkeypatch):
    from src.pictova.engine import selector

    searched = []
    monkeypatch.setattr(selector, "search_semantic_assets", lambda **_kwargs: [])
    monkeypatch.setattr(
        selector,
        "_deposit_search_download",
        lambda *, query, **_kwargs: searched.append(query) or [f"/{query}.jpg"],
    )

    files, assignments = selector._heading_specific_selection(
        post_context={
            "title": "Seyahat Uygulamaları",
            "available_headings": [
                {"text": "1. Airbnb", "level": 3},
                {"text": "2. BlaBlaCar", "level": 3},
            ],
            "occupied_headings": [{"text": "1. Airbnb", "level": 3}],
        },
        content_filter=None,
        limit=2,
        allow_external=True,
        plan_only=True,
    )

    assert files == ["/BlaBlaCar.jpg"]
    assert assignments[files[0]]["text"] == "2. BlaBlaCar"
    assert searched == ["BlaBlaCar"]


def test_heading_selection_downloads_exact_external_assets_when_not_planning(monkeypatch):
    from src.pictova.engine import selector

    calls = []
    headings = [
        {"text": "1. Ohrid Gölü", "level": 3},
        {"text": "2. Samuil Kalesi", "level": 3},
    ]

    monkeypatch.setattr(selector, "search_semantic_assets", lambda **_kwargs: [])

    def fake_download(**kwargs):
        calls.append(kwargs)
        return [f"/cache/{kwargs['query'].replace(' ', '-')}.jpg"]

    monkeypatch.setattr(selector, "_deposit_search_download", fake_download)

    files, assignments = selector._heading_specific_selection(
        post_context={
            "title": "Ohrid Gezi Rehberi",
            "available_headings": headings,
        },
        content_filter=None,
        limit=2,
        allow_external=True,
        plan_only=False,
    )

    assert len(files) == 2
    assert [call["plan_only"] for call in calls] == [False, False]
    assert [assignments[file]["text"] for file in files] == [heading["text"] for heading in headings]


def test_auto_selection_surfaces_exact_provider_failure_without_generic_fallback(monkeypatch):
    from src.pictova.engine import selector

    monkeypatch.setattr(selector, "search_semantic_assets", lambda **_kwargs: [])

    def failed_download(**_kwargs):
        raise TimeoutError("simulated CDN stall")

    monkeypatch.setattr(selector, "_deposit_search_download", failed_download)

    result = selector.resolve_source_images(
        source="auto",
        count=1,
        name=None,
        query=None,
        location_query=None,
        content_filter=None,
        post_context={
            "title": "Ohrid Gezi Rehberi",
            "available_headings": [{"text": "1. Ohrid Gölü", "level": 3}],
        },
        plan_only=False,
    )

    assert result["files"] == []
    assert result["warnings"] == [
        "DepositPhotos exact retrieval failed for '1. Ohrid Gölü' "
        "(TimeoutError); no generic fallback was used"
    ]


def test_numbered_h3_list_skips_introductory_h2_for_exact_selection(monkeypatch):
    from src.pictova.engine import selector

    searched = []
    monkeypatch.setattr(selector, "search_semantic_assets", lambda **_kwargs: [])
    monkeypatch.setattr(
        selector,
        "_deposit_search_download",
        lambda *, query, **_kwargs: searched.append(query) or [f"/{query}.jpg"],
    )

    files, assignments = selector._heading_specific_selection(
        post_context={
            "title": "Seyahat Uygulamaları",
            "available_headings": [
                {"text": "Seyahat Uygulamaları", "level": 2},
                {"text": "1. Airbnb", "level": 3},
                {"text": "2. BlaBlaCar", "level": 3},
            ],
        },
        content_filter=None,
        limit=2,
        allow_external=True,
        plan_only=True,
    )

    assert len(files) == 2
    assert all("Seyahat Uygulamaları" not in query for query in searched)
    assert [assignments[file]["text"] for file in files] == ["1. Airbnb", "2. BlaBlaCar"]


def test_numbered_h3_entity_rejects_incidental_local_token_match(monkeypatch):
    from src.pictova.engine import selector

    monkeypatch.setattr(
        selector,
        "_candidate_metadata_row",
        lambda _candidate: {
            "title": "Sivas yayla yolu",
            "summary": "Mor kır çiçekleri arasındaki yol",
            "apple_labels_json": "[\"Field\", \"Road\"]",
        },
    )

    assert not selector._candidate_matches_heading(
        "/sivas-field.jpg",
        "4. Field Trip",
        post_context={"title": "Seyahat Uygulamaları"},
        required_tokens={"field", "trip"},
    )


def test_resolve_source_images_semantic_skips_generic_first_match():
    from src.pictova.engine.selector import resolve_source_images

    generic = "/generic-waterfall.jpg"
    specific = "/kapuzbasi-waterfall.jpg"

    def fake_search(*, location_query, count, content_filter, post_context, include_icloud=False):
        return [generic, specific]

    rows = {
        generic: {
            "title": "Waterfall landscape",
            "location": "Unknown",
            "city": "",
            "state_province": "",
            "country": "",
            "scene": "nature",
            "activity": "sightseeing",
            "summary": "A scenic waterfall view",
            "description": "A scenic waterfall view",
            "ai_keywords_json": "[\"waterfall\", \"nature\"]",
            "apple_labels_json": "[\"waterfall\", \"landscape\"]",
        },
        specific: {
            "title": "Kapuzbaşı Şelaleleri",
            "location": "Kapuzbaşı",
            "city": "Kayseri",
            "state_province": "",
            "country": "Turkey",
            "scene": "waterfall",
            "activity": "sightseeing",
            "summary": "Kapuzbaşı şelaleleri",
            "description": "Kapuzbaşı şelaleleri ve çevresi",
            "ai_keywords_json": "[\"kapuzbasi\", \"waterfall\"]",
            "apple_labels_json": "[\"waterfall\", \"nature\"]",
        },
    }

    post_context = {
        "title": "Kapuzbaşı Şelaleleri Rehberi",
        "slug": "kapuzbasi-selaleleri-rehberi",
        "available_headings": [
            {"text": "Kapuzbaşı Şelaleleri", "level": 2},
        ],
    }

    with patch("src.pictova.engine.selector.search_semantic_assets", side_effect=fake_search), \
         patch("src.pictova.engine.selector._candidate_metadata_row", side_effect=lambda candidate: rows[candidate]):
        result = resolve_source_images(
            source="semantic",
            count=1,
            name=None,
            query=None,
            location_query="kapuzbaşı",
            content_filter=None,
            post_context=post_context,
        )

    assert result["files"] == [specific]


def test_deposit_search_download_filters_non_matching_results():
    from src.pictova.engine.selector import _deposit_search_download

    results = [
        {
            "id": "0",
            "title": "Panorama of snowy mountains",
            "tags": ["kapuzbasi", "aladaglar"],
            "preview_url": "https://example.test/tag-only.jpg",
        },
        {
            "id": "1",
            "title": "Waterfall landscape",
            "tags": ["waterfall", "nature"],
            "preview_url": "https://example.test/generic.jpg",
        },
        {
            "id": "2",
            "title": "Kapuzbaşı Şelaleleri",
            "tags": ["kapuzbasi", "waterfall"],
            "preview_url": "https://example.test/kapuzbasi.jpg",
        },
    ]

    with patch("src.pictova.providers.deposit.search", return_value=results), \
         patch("src.pictova.providers.deposit._login", return_value="session-1"), \
         patch("src.pictova.providers.deposit.download", side_effect=lambda asset_id, session_id, dest_dir=None: f"/tmp/{asset_id}.jpg"):
        downloaded = _deposit_search_download(
            query="Kapuzbaşı",
            count=1,
            plan_only=False,
            strict_tokens={"kapuzbasi"},
        )

    assert downloaded == ["/tmp/2.jpg"]


def test_deposit_search_download_skips_stalled_exact_asset():
    from src.pictova.engine.selector import _deposit_search_download

    results = [
        {"id": "1", "title": "Sultanahmet Square Istanbul", "preview_url": "https://example.test/1.jpg"},
        {"id": "2", "title": "Istanbul Sultanahmet Square", "preview_url": "https://example.test/2.jpg"},
    ]

    def download(asset_id, session_id):
        if asset_id == "1":
            raise TimeoutError("read timed out")
        return f"/tmp/{asset_id}.jpg"

    with patch("src.pictova.providers.deposit.search", return_value=results), \
         patch("src.pictova.providers.deposit._login", return_value="session-1"), \
         patch("src.pictova.providers.deposit.download", side_effect=download):
        downloaded = _deposit_search_download(
            query="Sultanahmet Square Istanbul",
            count=1,
            plan_only=False,
            strict_tokens={"sultanahmet", "square", "istanbul"},
        )

    assert downloaded == ["/tmp/2.jpg"]


def test_deposit_search_download_reports_when_all_exact_transfers_fail(monkeypatch):
    from src.pictova.engine import selector

    selector._DEPOSIT_DISCOVERY_CACHE.clear()
    monkeypatch.setattr(selector, "_load_deposit_discovery", lambda _key: None)
    monkeypatch.setattr(selector, "_save_deposit_discovery", lambda _key, _results: None)
    results = [
        {"id": "1", "title": "Sultanahmet Square Istanbul", "preview_url": "https://example.test/1.jpg"},
        {"id": "2", "title": "Istanbul Sultanahmet Square", "preview_url": "https://example.test/2.jpg"},
    ]

    with patch("src.pictova.providers.deposit.search", return_value=results), \
         patch("src.pictova.providers.deposit._login", return_value="session-1"), \
         patch("src.pictova.providers.deposit.download", side_effect=TimeoutError("read timed out")):
        with pytest.raises(RuntimeError, match="exact download incomplete"):
            selector._deposit_search_download(
                query="Sultanahmet Square Istanbul",
                count=1,
                plan_only=False,
                strict_tokens={"sultanahmet", "square", "istanbul"},
            )


def test_deposit_paid_phase_reuses_discovery_search_results(tmp_path, monkeypatch):
    from src.pictova.engine.selector import _DEPOSIT_DISCOVERY_CACHE, _deposit_search_download

    _DEPOSIT_DISCOVERY_CACHE.clear()
    monkeypatch.setattr(
        "src.pictova.engine.selector._DEPOSIT_DISCOVERY_CACHE_DIR",
        tmp_path / "discovery",
    )
    results = [{
        "id": "1",
        "title": "Topkapi Palace Istanbul",
        "preview_url": "https://example.test/1.jpg",
    }]
    with patch("src.pictova.providers.deposit.search", return_value=results) as search, \
         patch("src.pictova.providers.deposit._login", return_value="session-1"), \
         patch("src.pictova.providers.deposit.download", return_value="/tmp/1.jpg"):
        preview = _deposit_search_download(
            "Topkapi Palace Istanbul", 1, True,
            strict_tokens={"topkapi", "palace", "istanbul"},
        )
        downloaded = _deposit_search_download(
            "Topkapi Palace Istanbul", 1, False,
            strict_tokens={"topkapi", "palace", "istanbul"},
        )

    assert preview == ["https://example.test/1.jpg"]
    assert downloaded == ["/tmp/1.jpg"]
    search.assert_called_once()


def test_deposit_discovery_disk_cache_replays_plan_without_new_search(tmp_path, monkeypatch):
    from src.pictova.engine import selector

    selector._DEPOSIT_DISCOVERY_CACHE.clear()
    monkeypatch.setattr(selector, "_DEPOSIT_DISCOVERY_CACHE_DIR", tmp_path / "discovery")
    result = [{
        "id": "1",
        "title": "Ohrid Lake North Macedonia",
        "preview_url": "https://example.test/ohrid.jpg",
    }]
    with patch("src.pictova.providers.deposit.search", return_value=result) as search:
        first = selector._deposit_search_download("Ohrid Lake", 1, True, strict_tokens={"ohrid"})
    selector._DEPOSIT_DISCOVERY_CACHE.clear()
    with patch("src.pictova.providers.deposit.search", side_effect=AssertionError("network search must be reused")):
        second = selector._deposit_search_download("Ohrid Lake", 1, True, strict_tokens={"ohrid"})

    assert first == second == ["https://example.test/ohrid.jpg"]
    search.assert_called_once()


def test_wikimedia_requires_location_token_in_file_title():
    from src.pictova.engine.selector import resolve_source_images

    results = [
        {"id": "1", "title": "Generic cave.jpg", "url": "https://example.test/generic.jpg"},
        {"id": "2", "title": "Dupnisa Cave.jpg", "url": "https://example.test/dupnisa.jpg"},
    ]
    with patch("src.pictova.providers.wikimedia.search", return_value=results), \
         patch("src.pictova.providers.wikimedia.download", return_value="/tmp/dupnisa.jpg"):
        selected = resolve_source_images(
            source="wikimedia", count=1, name=None, query="Dupnisa Cave",
            location_query=None, content_filter=None,
            post_context={"title": "Dupnisa Mağarası"},
        )

    assert selected["files"] == ["/tmp/dupnisa.jpg"]


@pytest.mark.xfail(reason="Adım 2 (semantik katman) bekliyor: destinasyon/çapraz-dil sözlükleri kaldırıldı, yerine öğrenilmiş eşleşme gelecek", strict=True)
def test_deposit_title_matching_accepts_only_specific_entity_tokens():
    from src.pictova.engine.selector import _deposit_result_tokens, _matches_anchor_tokens

    assert not _matches_anchor_tokens(
        _deposit_result_tokens({"title": "Mountain landscape in Turkey", "tags": ["aladaglar"]}),
        {"aladaglar", "turkey"},
    )
    assert _matches_anchor_tokens(
        _deposit_result_tokens({"title": "Aladag National Park in Turkey", "tags": []}),
        {"aladaglar"},
    )


@pytest.mark.xfail(reason="Adım 2 (semantik katman) bekliyor: destinasyon/çapraz-dil sözlükleri kaldırıldı, yerine öğrenilmiş eşleşme gelecek", strict=True)
def test_deposit_title_matching_supports_cross_language_topic_tokens():
    from src.pictova.engine.selector import _deposit_result_tokens, _matches_anchor_tokens

    assert _matches_anchor_tokens(
        _deposit_result_tokens({"title": "Damaged suitcase at airport", "tags": []}),
        {"kirilan", "valiz", "ucakta"},
    )
    assert _matches_anchor_tokens(
        _deposit_result_tokens({"title": "Digital nomad visa application", "tags": []}),
        {"dijital", "gocebe", "vizesi"},
    )


@pytest.mark.xfail(reason="Adım 2 (semantik katman) bekliyor: destinasyon/çapraz-dil sözlükleri kaldırıldı, yerine öğrenilmiş eşleşme gelecek", strict=True)
def test_deposit_search_requires_two_meaningful_query_title_matches():
    from src.pictova.engine.selector import _deposit_search_download

    results = [
        {"id": "1", "title": "Suitcase on white background", "preview_url": "https://example.test/generic.jpg"},
        {"id": "2", "title": "Damaged suitcase at airline baggage claim", "preview_url": "https://example.test/exact.jpg"},
    ]
    with patch("src.pictova.providers.deposit.search", return_value=results):
        planned = _deposit_search_download(
            query="damaged suitcase airline baggage claim",
            count=1,
            plan_only=True,
            strict_tokens={"kirilan", "valiz", "tazminat"},
        )

    assert planned == ["https://example.test/exact.jpg"]


def test_deposit_transport_retries_transient_gateway_error():
    from src.pictova.providers.deposit import _urlopen_with_retry

    request = urllib.request.Request("https://example.test")
    response = object()
    gateway_timeout = urllib.error.HTTPError(
        request.full_url, 504, "Gateway Time-out", hdrs=None, fp=None,
    )

    with patch("src.pictova.providers.deposit.urllib.request.urlopen", side_effect=[gateway_timeout, response]), \
         patch("src.pictova.providers.deposit.time.sleep") as sleep:
        assert _urlopen_with_retry(request, timeout=1) is response

    sleep.assert_called_once_with(0.5)


def test_deposit_download_recovers_existing_licensed_temp_file(tmp_path):
    from src.pictova.providers.deposit import download

    recovered_dir = tmp_path / "pictova_dep_interrupted"
    recovered_dir.mkdir()
    recovered = recovered_dir / "deposit_123.jpg"
    recovered.write_bytes(b"licensed-image")
    cache_dir = tmp_path / "cache"

    with patch("src.pictova.providers.deposit.tempfile.gettempdir", return_value=str(tmp_path)), \
         patch("src.pictova.providers.deposit._post") as post:
        cached = download("123", "session", dest_dir=str(cache_dir))

    assert cached == str(cache_dir / "deposit_123.jpg")
    assert (cache_dir / "deposit_123.jpg").read_bytes() == b"licensed-image"
    post.assert_not_called()


def test_deposit_download_retries_file_read_without_requesting_license_again(tmp_path):
    from src.pictova.providers.deposit import download

    timed_out = MagicMock()
    timed_out.__enter__.return_value.read.side_effect = TimeoutError("read timed out")
    completed = MagicMock()
    completed.__enter__.return_value.read.side_effect = [b"licensed-image", b""]
    license_response = {"type": "success", "downloadLink": "https://download.test/123"}

    with patch("src.pictova.providers.deposit._post", return_value=license_response) as post, \
         patch("src.pictova.providers.deposit._urlopen_with_retry", side_effect=[timed_out, completed]), \
         patch("src.pictova.providers.deposit.time.sleep") as sleep:
        cached = download("123", "session", dest_dir=str(tmp_path / "cache"))

    assert (tmp_path / "cache" / "deposit_123.jpg").read_bytes() == b"licensed-image"
    assert cached.endswith("deposit_123.jpg")
    post.assert_called_once()
    sleep.assert_called_once_with(0.5)


def test_deposit_download_resumes_partial_file_with_range_without_relicensing(tmp_path):
    from src.pictova.providers.deposit import download

    first = MagicMock()
    first.__enter__.return_value.read.side_effect = [b"first-", TimeoutError("read timed out")]
    resumed = MagicMock()
    resumed.__enter__.return_value.status = 206
    resumed.__enter__.return_value.read.side_effect = [b"second", b""]
    license_response = {"type": "success", "downloadLink": "https://download.test/123"}

    with patch("src.pictova.providers.deposit._post", return_value=license_response) as post, \
         patch("src.pictova.providers.deposit._urlopen_with_retry", side_effect=[first, resumed]) as open_url, \
         patch("src.pictova.providers.deposit.time.sleep"):
        cached = download("123", "session", dest_dir=str(tmp_path / "cache"))

    assert Path(cached).read_bytes() == b"first-second"
    assert open_url.call_args_list[1].args[0].get_header("Range") == "bytes=6-"
    post.assert_called_once()


def test_deposit_download_reuses_saved_link_after_interrupted_process(tmp_path):
    from src.pictova.providers.deposit import download

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    partial = cache_dir / "deposit_123.jpg.part"
    partial.write_bytes(b"first-")
    state = cache_dir / "deposit_123.jpg.part.json"
    state.write_text('{"download_link": "https://download.test/123"}', encoding="utf-8")
    resumed = MagicMock()
    resumed.__enter__.return_value.status = 206
    resumed.__enter__.return_value.read.side_effect = [b"second", b""]

    with patch("src.pictova.providers.deposit._post") as post, \
         patch("src.pictova.providers.deposit._urlopen_with_retry", return_value=resumed) as open_url:
        cached = download("123", "session", dest_dir=str(cache_dir))

    assert Path(cached).read_bytes() == b"first-second"
    assert open_url.call_args.args[0].get_header("Range") == "bytes=6-"
    post.assert_not_called()
    assert not state.exists()


@pytest.mark.xfail(reason="Adım 2 (semantik katman) bekliyor: destinasyon/çapraz-dil sözlükleri kaldırıldı, yerine öğrenilmiş eşleşme gelecek", strict=True)
def test_resolve_deposit_never_uses_body_link_as_title_alias():
    from src.pictova.engine.selector import resolve_source_images

    post_context = {
        "title": "Kapuzbaşı Şelaleleri Rehberi",
        "slug": "kapuzbasi-selaleleri-rehberi",
        "content_raw": (
            '<p><a href="/kayseri-gezi-rehberi">Kayseri</a> içinde '
            '<a href="/aladaglar-milli-parki">Aladağlar Milli Parkı</a>.</p>'
        ),
    }
    calls = []

    def fake_download(query, count, plan_only=False, *, strict_tokens=None):
        calls.append((query, strict_tokens))
        return []

    with patch("src.pictova.engine.selector._deposit_search_download", side_effect=fake_download):
        result = resolve_source_images(
            source="deposit",
            count=4,
            name=None,
            query=None,
            location_query=None,
            content_filter=None,
            post_context=post_context,
            plan_only=True,
        )

    assert result["files"] == []
    assert result["query"] == ""
    assert len(calls) == 1
    assert calls[0][0].startswith("kapuzbasi Turkey")
    assert calls[0][1] == {"kapuzbasi"}


@pytest.mark.xfail(reason="Adım 2 (semantik katman) bekliyor: destinasyon/çapraz-dil sözlükleri kaldırıldı, yerine öğrenilmiş eşleşme gelecek", strict=True)
def test_explicit_deposit_query_cannot_override_post_title_entity():
    from src.pictova.engine.selector import resolve_source_images

    seen = {}

    def fake_download(query, count, plan_only=False, *, strict_tokens=None):
        seen["query"] = query
        seen["strict_tokens"] = strict_tokens
        return []

    with patch("src.pictova.engine.selector._deposit_search_download", side_effect=fake_download):
        result = resolve_source_images(
            source="deposit",
            count=4,
            name=None,
            query="Aladaglar",
            location_query=None,
            content_filter=None,
            post_context={
                "title": "Kapuzbaşı Şelaleleri Rehberi",
                "slug": "kapuzbasi-selaleleri-rehberi",
            },
            plan_only=True,
        )

    assert result["files"] == []
    assert seen["query"].startswith("Aladaglar Turkey")
    assert seen["strict_tokens"] == {"kapuzbasi"}


@pytest.mark.xfail(reason="Adım 2 (semantik katman) bekliyor: destinasyon/çapraz-dil sözlükleri kaldırıldı, yerine öğrenilmiş eşleşme gelecek", strict=True)
def test_deposit_numbered_places_require_each_heading_entity():
    from src.pictova.engine.selector import resolve_source_images

    calls = []

    def fake_download(query, count, plan_only=False, *, strict_tokens=None):
        calls.append((query, strict_tokens))
        return [f"https://example.test/{next(iter(strict_tokens))}.jpg"]

    with patch("src.pictova.engine.selector._deposit_search_download", side_effect=fake_download):
        result = resolve_source_images(
            source="deposit",
            count=2,
            name=None,
            query=None,
            location_query=None,
            content_filter=None,
            post_context={
                "title": "Yakın Yunan Adaları",
                "slug": "yakin-yunan-adalari",
                "available_headings": [
                    {"text": "1. Fethiye’den Rodos’a Kaçış", "level": 3},
                    {"text": "2. Bodrum’dan Kos’a Kaçış", "level": 3},
                ],
            },
            plan_only=True,
        )

    assert len(result["files"]) == 2
    assert calls[0][1] == {"rhodes"}
    assert calls[1][1] == {"kos"}


def test_deposit_numbered_places_skip_missing_heading_before_download():
    from src.pictova.engine.selector import resolve_source_images

    calls = []

    def fake_download(query, count, plan_only=False, *, strict_tokens=None):
        calls.append((query, plan_only, strict_tokens))
        if "Missing" in query:
            return []
        return [f"https://example.test/{query.replace(' ', '-')}.jpg"]

    with patch("src.pictova.engine.selector._heading_to_search_query", side_effect=lambda text: text.split('. ', 1)[-1]), patch(
        "src.pictova.engine.selector._deposit_search_download", side_effect=fake_download
    ):
        result = resolve_source_images(
            source="deposit", count=2, name=None, query=None, location_query=None,
            content_filter=None, plan_only=True,
            post_context={
                "title": "City Places", "slug": "city-places",
                "available_headings": [
                    {"text": "1. First Place", "level": 3},
                    {"text": "2. Missing Place", "level": 3},
                    {"text": "3. Third Place", "level": 3},
                ],
            },
        )

    assert len(result["files"]) == 2
    assert [call[0] for call in calls] == ["First Place", "Missing Place", "Third Place"]
    assert all(call[1] is True for call in calls)


def test_deposit_numbered_places_discover_all_before_paid_download():
    from src.pictova.engine.selector import resolve_source_images

    calls = []

    def fake_download(query, count, plan_only=False, *, strict_tokens=None):
        calls.append((query, plan_only))
        suffix = "preview" if plan_only else "local"
        return [f"/{suffix}/{query.replace(' ', '-')}.jpg"]

    with patch("src.pictova.engine.selector._heading_to_search_query", side_effect=lambda text: text.split('. ', 1)[-1]), patch(
        "src.pictova.engine.selector._deposit_search_download", side_effect=fake_download
    ):
        result = resolve_source_images(
            source="deposit", count=2, name=None, query=None, location_query=None,
            content_filter=None, plan_only=False,
            post_context={
                "title": "City Places", "slug": "city-places",
                "available_headings": [
                    {"text": "1. First Place", "level": 3},
                    {"text": "2. Second Place", "level": 3},
                ],
            },
        )

    assert result["files"] == ["/local/First-Place.jpg", "/local/Second-Place.jpg"]
    assert calls == [
        ("First Place", True), ("Second Place", True),
        ("First Place", False), ("Second Place", False),
    ]


def test_extract_available_headings_prefers_h3_children_of_places_list():
    from src.services.wordpress import _extract_available_headings

    content = """
<!-- wp:heading --><h2>İstanbul Gezilecek Yerler</h2><!-- /wp:heading -->
<!-- wp:heading {"level":3} --><h3>1. Ayasofya</h3><!-- /wp:heading -->
<!-- wp:paragraph --><p>Metin</p><!-- /wp:paragraph -->
<!-- wp:heading {"level":3} --><h3>2. Topkapı Sarayı</h3><!-- /wp:heading -->
<!-- wp:heading --><h2>İstanbul'da Ulaşım</h2><!-- /wp:heading -->
"""

    assert _extract_available_headings(content) == [
        {"text": "1. Ayasofya", "level": 3},
        {"text": "2. Topkapı Sarayı", "level": 3},
    ]


def test_extract_available_headings_treats_gorulmesi_gereken_as_places_list():
    from src.services.wordpress import _extract_available_headings

    content = """
<!-- wp:heading --><h2>Aladağlar’da Görülmesi Gereken Yerler</h2><!-- /wp:heading -->
<!-- wp:heading {"level":3} --><h3>Demirkazık Tepesi</h3><!-- /wp:heading -->
<!-- wp:paragraph --><p>Birinci paragraf</p><!-- /wp:paragraph -->
<!-- wp:paragraph --><p>İkinci paragraf</p><!-- /wp:paragraph -->
<!-- wp:image {"id":9} --><figure><img class="wp-image-9"/></figure><!-- /wp:image -->
<!-- wp:heading {"level":3} --><h3>Yedi Göller</h3><!-- /wp:heading -->
<!-- wp:heading --><h2>Ulaşım</h2><!-- /wp:heading -->
"""

    assert _extract_available_headings(content) == [
        {"text": "Demirkazık Tepesi", "level": 3},
    ]


def test_extract_available_headings_uses_only_numbered_h2_place_items():
    from src.services.wordpress import _extract_available_headings

    content = """
<!-- wp:heading --><h2>Rodos Gezilecek Yerler</h2><!-- /wp:heading -->
<!-- wp:heading --><h2>1. Lindos</h2><!-- /wp:heading -->
<!-- wp:heading --><h2>2. Eski Şehir</h2><!-- /wp:heading -->
<!-- wp:heading --><h2>Rodos'ta Konaklama</h2><!-- /wp:heading -->
"""

    assert _extract_available_headings(content) == [
        {"text": "1. Lindos", "level": 2},
        {"text": "2. Eski Şehir", "level": 2},
    ]


def test_reset_removes_only_manifest_owned_media_blocks():
    from src.services.wordpress import YOWordPressUploader

    content = """
<!-- wp:image {"id":100} --><figure><img class="wp-image-100"/></figure><!-- /wp:image -->
<!-- wp:image {"id":200} --><figure><img class="wp-image-200"/></figure><!-- /wp:image -->
"""
    uploader = object.__new__(YOWordPressUploader)

    cleaned, removed = uploader._remove_managed_media_blocks(content, {200})

    assert removed == 1
    assert "wp-image-100" in cleaned
    assert "wp-image-200" not in cleaned


def test_native_metadata_accepts_one_exact_heading_entity():
    from src.pictova.engine.quality import validate_native_metadata

    metadata = {
        "title": "Kapuzbaşı Vadisinde Doğa Görünümü",
        "alt": "Kapuzbaşı çevresindeki kayalık vadi ve doğal bitki örtüsü",
        "caption": "Kapuzbaşı vadisinin çevresindeki doğal görünüm.",
        "description": "Kapuzbaşı çevresindeki kayalık araziyi gösteren geniş açı bir kare.",
        "keywords": ["kapuzbasi", "vadi"],
        "heading": "Kapuzbaşı Nerede 📍",
    }
    post_context = {
        "title": "Kapuzbaşı Şelaleleri Rehberi: Gitmeden Bilmeniz Gerekenler",
        "slug": "kapuzbasi-selaleleri-rehberi",
    }

    errors = validate_native_metadata(metadata, post_context)

    assert "metadata does not match heading or post context" not in errors


def test_destination_index_uuids_match(tmp_path):
    import json
    from src.pictova.engine.selector import _destination_index_uuids
    idx = {"Sinop": ["uuid-1", "uuid-2", "uuid-3"], "Antalya": ["uuid-4"]}
    idx_file = tmp_path / "destination_index.json"
    idx_file.write_text(json.dumps(idx))
    with patch("src.pictova.engine.selector.get_visual_memory_db_path") as mock_db:
        mock_db.return_value = type("P", (), {"parent": tmp_path})()
        result = _destination_index_uuids("sinop", 2)
    assert result == ["icloud://uuid-1", "icloud://uuid-2"]


def test_destination_index_uuids_no_match(tmp_path):
    import json
    from src.pictova.engine.selector import _destination_index_uuids
    idx = {"Sinop": ["uuid-1"]}
    idx_file = tmp_path / "destination_index.json"
    idx_file.write_text(json.dumps(idx))
    with patch("src.pictova.engine.selector.get_visual_memory_db_path") as mock_db:
        mock_db.return_value = type("P", (), {"parent": tmp_path})()
        result = _destination_index_uuids("istanbul", 3)
    assert result == []


def test_resolve_source_images_semantic():
    from src.pictova.engine.selector import resolve_source_images

    rows = {
        "/a.jpg": {
            "title": "Test Bay",
            "location": "Test",
            "city": "Test",
            "state_province": "",
            "country": "",
            "scene": "bay",
            "activity": "sightseeing",
            "summary": "Test Bay",
            "description": "Test Bay",
            "ai_keywords_json": "[\"test\", \"bay\"]",
            "apple_labels_json": "[\"bay\", \"sea\"]",
        },
        "/b.jpg": {
            "title": "Test Beach",
            "location": "Test",
            "city": "Test",
            "state_province": "",
            "country": "",
            "scene": "beach",
            "activity": "sightseeing",
            "summary": "Test Beach",
            "description": "Test Beach",
            "ai_keywords_json": "[\"test\", \"beach\"]",
            "apple_labels_json": "[\"beach\", \"sea\"]",
        },
    }

    with patch("src.pictova.engine.selector.search_semantic_assets", return_value=["/a.jpg", "/b.jpg"]), \
         patch("src.pictova.engine.selector._candidate_metadata_row", side_effect=lambda candidate: rows[candidate]):
        result = resolve_source_images(
            source="semantic", count=2, name=None, query=None,
            location_query="test", content_filter=None, post_context={},
        )
    assert result["source"] == "semantic"
    assert len(result["files"]) == 2


def test_resolve_source_images_unsupported_source():
    from src.pictova.engine.selector import resolve_source_images
    with pytest.raises(ValueError, match="Unsupported source"):
        resolve_source_images(
            source="nonexistent", count=1, name=None, query=None,
            location_query=None, content_filter=None, post_context={},
        )


def test_auto_source_keeps_only_heading_exact_matches_when_short(monkeypatch):
    from src.pictova.engine import selector

    seen = {}

    def heading_selection(**kwargs):
        seen.update(kwargs)
        return ["/exact-one.jpg"], {"/exact-one.jpg": {"text": "Yalnız Seyahatin Avantajları", "level": 2}}

    monkeypatch.setattr(selector, "_heading_specific_selection", heading_selection)
    monkeypatch.setattr(
        selector,
        "search_semantic_assets",
        lambda **kwargs: pytest.fail("generic fallback must not fill heading-based requests"),
    )

    result = selector.resolve_source_images(
        source="auto",
        count=4,
        name=None,
        query=None,
        location_query=None,
        content_filter=None,
        post_context={
            "title": "Yalnız Seyahat Rehberi",
            "slug": "yalniz-seyahat-etmek",
            "available_headings": [{"text": "Yalnız Seyahatin Avantajları", "level": 2}],
        },
        plan_only=True,
    )

    assert seen["allow_external"] is True
    assert seen["plan_only"] is True
    assert result["query"] == "yalniz seyahat"
    assert result["files"] == ["/exact-one.jpg"]


def test_heading_selection_prefers_exact_local_before_deposit(monkeypatch):
    from src.pictova.engine import selector

    monkeypatch.setattr(selector, "search_semantic_assets", lambda **kwargs: ["/local.jpg"])
    monkeypatch.setattr(selector, "_candidate_matches_heading", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        selector,
        "_deposit_search_download",
        lambda **kwargs: pytest.fail("DepositPhotos should only be used after local exact matching fails"),
    )

    result = selector._heading_specific_files(
        post_context={"available_headings": [{"text": "Ohrid Gölü", "level": 3}]},
        content_filter=None,
        limit=1,
        allow_external=True,
        plan_only=True,
    )

    assert result == ["/local.jpg"]


def test_compute_assigned_headings_prefers_earliest_main_headings():
    from src.pictova.engine.attach import _compute_assigned_headings

    processed_images = ["img-1", "img-2", "img-3", "img-4"]
    post_context = {
        "available_headings": [
            {"text": "1. Fethiye’den Rodos’a Kaçış", "level": 2},
            {"text": "2. Bodrum’dan Kos’a Kaçış", "level": 2},
            {"text": "3. Kuşadası’ndan Samos’a Kaçış", "level": 2},
            {"text": "4. Çeşme’den Sakız Adası’na Kaçış", "level": 2},
            {"text": "Liman İşlemleri ve Esnek Bilet Kuralları", "level": 2},
            {"text": "Kapıda Vizeyle Kolay Geçiş Yöntemi", "level": 2},
        ]
    }

    assigned = _compute_assigned_headings(processed_images, {}, post_context)

    assert [assigned[img]["text"] for img in processed_images] == [
        "1. Fethiye’den Rodos’a Kaçış",
        "2. Bodrum’dan Kos’a Kaçış",
        "3. Kuşadası’ndan Samos’a Kaçış",
        "4. Çeşme’den Sakız Adası’na Kaçış",
    ]


@pytest.mark.xfail(reason="Adım 2 (semantik katman) bekliyor: destinasyon/çapraz-dil sözlükleri kaldırıldı, yerine öğrenilmiş eşleşme gelecek", strict=True)
def test_compute_assigned_headings_filters_unrelated_headings_for_explicit_query():
    from src.pictova.engine.attach import _compute_assigned_headings

    images = ["a", "b", "c"]
    context = {"available_headings": [
        {"text": "Sınır Polisinin Asıl Amacı Nedir?", "level": 3},
        {"text": "Dönüş Bileti", "level": 3},
        {"text": "Pasaport Kontrolünde Sorulan Sorular", "level": 2},
        {"text": "Kara Sınır Kapılarındaki Farklılıklar", "level": 2},
    ]}
    assigned = _compute_assigned_headings(
        images,
        {"location_query": "border police passport control"},
        context,
    )
    headings = [assigned[image]["text"] for image in images]
    assert "Dönüş Bileti" not in headings
    assert headings == [
        "Sınır Polisinin Asıl Amacı Nedir?",
        "Pasaport Kontrolünde Sorulan Sorular",
        "Kara Sınır Kapılarındaki Farklılıklar",
    ]


def test_english_product_query_does_not_gain_country_suffix():
    from src.pictova.engine.selector import _turkify_to_english_query

    assert _turkify_to_english_query("cabin baggage suitcase") == "cabin baggage suitcase"


@pytest.mark.xfail(reason="Adım 2 (semantik katman) bekliyor: destinasyon/çapraz-dil sözlükleri kaldırıldı, yerine öğrenilmiş eşleşme gelecek", strict=True)
@pytest.mark.parametrize(("heading", "expected"), [
    ("1. Sultanahmet Meydanı", "Sultanahmet Square Istanbul"),
    ("3. Sultanahmet Camii", "Blue Mosque Istanbul"),
    ("4. Topkapı Sarayı", "Topkapi Palace Istanbul"),
    ("6. Beyazıt ve Kapalıçarşı", "Grand Bazaar Istanbul"),
    ("7. Eminönü ve Mısır Çarşısı", "Egyptian Bazaar Istanbul"),
    ("10. Beşiktaş ve Boğaziçi Hattı", "Besiktas Bosphorus Istanbul"),
])
def test_heading_search_query_uses_indexed_istanbul_landmark_name(heading, expected):
    from src.pictova.engine.selector import _heading_to_search_query

    assert _heading_to_search_query(heading) == expected


def test_semantic_gallery_policy_only_groups_portraits_in_a_large_run():
    from src.pictova.engine.attach import apply_semantic_gallery_policy

    result = apply_semantic_gallery_policy(
        {
            "a": {"heading": "Koy", "heading_level": 3},
            "b": {"heading": "Koy", "heading_level": 3},
            "c": {"heading": "Liman", "heading_level": 3},
        },
        {"a": {"aspect_ratio": 0.7}, "b": {"aspect_ratio": 0.8}, "c": {"aspect_ratio": 1.5}},
        {"title": "Datça Gezi Rehberi"},
        requested_count=5,
    )

    assert result["a"]["gallery"] is True
    assert result["b"]["gallery"] is True
    assert result["c"]["gallery"] is False


def test_semantic_gallery_policy_uses_h3_pairs_for_long_places_lists():
    from src.pictova.engine.attach import apply_semantic_gallery_policy

    result = apply_semantic_gallery_policy(
        {
            "a": {"heading": "1. Antik Kent", "heading_level": 3},
            "b": {"heading": "1. Antik Kent", "heading_level": 3},
            "c": {"heading": "2. Kale", "heading_level": 3},
        },
        {"a": {"aspect_ratio": 1.5}, "b": {"aspect_ratio": 1.4}, "c": {"aspect_ratio": 1.5}},
        {
            "title": "Datça Gezilecek Yerler",
            "available_headings": [
                {"text": "1. Antik Kent", "level": 3},
                {"text": "2. Kale", "level": 3},
                {"text": "3. Liman", "level": 3},
            ],
        },
        requested_count=6,
    )

    assert result["a"]["gallery"] is True
    assert result["b"]["gallery"] is True
    assert result["c"]["gallery"] is False


def test_gallery_policy_follows_published_grouping():
    """A pair under one heading is a gallery; a lone image is not.

    Measured on 300 published posts: single block 66%, two-image gallery 28%.
    The requested count and the aspect ratio play no part in that record.
    """
    from src.pictova.engine.attach import apply_semantic_gallery_policy

    result = apply_semantic_gallery_policy(
        {
            "a": {"heading": "Koy", "heading_level": 3},
            "b": {"heading": "Koy", "heading_level": 3},
            "c": {"heading": "Kale", "heading_level": 3},
        },
        # Landscape pair — the old rule required portraits and refused to group.
        {"a": {"aspect_ratio": 1.6}, "b": {"aspect_ratio": 1.6}, "c": {"aspect_ratio": 1.6}},
        {"title": "Datça Gezi Rehberi"},
        requested_count=3,
    )

    assert result["a"]["gallery"] is True
    assert result["b"]["gallery"] is True
    assert result["c"]["gallery"] is False
