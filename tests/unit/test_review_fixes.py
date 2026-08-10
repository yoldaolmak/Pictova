"""Regressions for the defects found in the 2026-08 code review.

Each test pins one previously broken behaviour so it cannot silently return.
"""

from __future__ import annotations

import ssl
from unittest.mock import patch

import pytest


# ── Selection: no destination may be named in code ──────────────────────────

def test_query_building_never_invents_a_country():
    """A place the code does not know must not be relocated by a guess.

    "Kosova" used to become the Greek island Kos, and any short query used to
    collect a " Turkey" suffix. Geography now comes only from the post.
    """
    from src.pictova.engine.selector import _heading_to_search_query, _turkify_to_english_query

    kosovo = _heading_to_search_query("Kosova Gezisi")
    assert "Kosova" in kosovo
    assert "Greece" not in kosovo and "Turkey" not in kosovo

    assert "Turkey" not in _turkify_to_english_query("sinop kalesi")
    # An explicit post location is still honoured — it comes from data.
    assert "Sinop" in _heading_to_search_query("Kalesi", post_location="Sinop")


@pytest.mark.parametrize("module_name", [
    "src.pictova.engine.selector",
    "src.pictova.engine.metadata",
    "src.pictova.engine.quality",
    "src.core.media_publish",
    "src.core.media_quality",
])
def test_no_destination_names_remain_in_code(module_name):
    """Guard the principle itself, so a place name cannot creep back in.

    Only executable code and literals count. Comments and docstrings may name
    a destination when they explain which bug the removal fixed.
    """
    import ast
    import importlib
    from pathlib import Path

    module = importlib.import_module(module_name)

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    docstrings = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    literals = " ".join(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node not in docstrings
    ).casefold()

    for place in (
        "cappadocia", "kapadokya", "istanbul", "sultanahmet", "topkapi",
        "rhodes", "mykonos", "santorini", "ohrid", "vietnam", "hanoi",
        "batum", "batumi", "greece", "turkey", "turkiye", "thailand",
    ):
        assert place not in literals, f"destination name in {module_name}: {place}"


# ── Selection: a provider outage degrades, it does not abort ────────────────

def _provider_outage(**_kwargs):
    raise RuntimeError("provider down")


@pytest.mark.parametrize("source", ["auto", "deposit"])
def test_provider_outage_returns_structured_selection(source):
    from src.pictova.engine import selector

    post_context = {
        "title": "Sinop Gezilecek Yerler",
        "slug": "sinop-gezilecek-yerler",
        "available_headings": [],
    }
    with patch.object(selector, "_deposit_search_download", side_effect=_provider_outage), \
         patch.object(selector, "search_semantic_assets", return_value=[]), \
         patch.object(selector, "_destination_index_uuids", return_value=[]):
        result = selector.resolve_source_images(
            source=source,
            count=2,
            name=None,
            query=None,
            location_query="sinop",
            content_filter=None,
            post_context=post_context,
        )

    assert result["files"] == []
    assert any("DepositPhotos exact retrieval failed" in w for w in result["warnings"])


def test_plan_returns_failure_document_instead_of_raising():
    """`plan`/`process` must honour the JSON contract on an unexpected error."""
    from src.pictova.app import api

    with patch.object(api, "prepare_attach_request", side_effect=RuntimeError("boom")):
        result = api.plan_attach({"site": "yoldaolmak", "post_id": 1})

    assert result["status"] == "failed"
    assert result["warnings"] == ["boom"]


# ── Attach: a dropped asset must be explained ───────────────────────────────

def test_icloud_download_failure_reaches_the_caller():
    from src.pictova.engine import attach

    warnings: list[str] = []
    with patch.object(attach, "download_icloud_photo", side_effect=RuntimeError("no session")):
        resolved = attach.resolve_icloud_files(["icloud://ABC12345", "/local/a.jpg"], warnings)

    assert resolved == ["/local/a.jpg"]
    assert warnings and "iCloud download failed" in warnings[0]


# ── Providers: credentials may not travel over an unverified channel ────────

def test_deposit_tls_context_verifies_certificates():
    from src.pictova.providers.deposit import _ssl_ctx

    ctx = _ssl_ctx()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


# ── Vision chain: a transient 429 may not disable a key forever ─────────────

def test_gemini_throttled_key_recovers_after_cooldown():
    from src.pictova.engine import vision_chain

    vision_chain._GEMINI_REJECTED_KEYS.clear()
    vision_chain._GEMINI_COOLDOWN_UNTIL.clear()
    vision_chain._GEMINI_COOLDOWN_UNTIL["k1"] = 0.0  # already elapsed
    assert vision_chain._gemini_key_available("k1") is True

    vision_chain._GEMINI_REJECTED_KEYS.add("k2")
    assert vision_chain._gemini_key_available("k2") is False


def test_gemini_keys_plural_variable_is_recognised(monkeypatch):
    from src.pictova.engine import vision_chain

    monkeypatch.setenv("GEMINI_API_KEYS", "a,b,a")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert vision_chain._gemini_api_keys() == ["a", "b"]


# ── Config: one .env parser, one semantics ──────────────────────────────────

def test_env_values_are_unquoted_and_last_definition_wins(tmp_path, monkeypatch):
    from src.utils import config

    env_file = tmp_path / ".env"
    env_file.write_text(
        '# comment\n'
        'WP_APP_PASSWORD="abcd efgh ijkl"\n'
        'export OPENAI_API_KEY=stale\n'
        'OPENAI_API_KEY=current\n'
        'PLAIN=value # trailing note\n'
    )
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "_ENV_LOADED", False)
    for name in ("WP_APP_PASSWORD", "OPENAI_API_KEY", "PLAIN"):
        monkeypatch.delenv(name, raising=False)

    config.load_project_env()

    assert config.env_str("WP_APP_PASSWORD") == "abcd efgh ijkl"
    assert config.env_str("OPENAI_API_KEY") == "current"
    assert config.env_str("PLAIN") == "value"


# ── WordPress: a failed content update may not leave orphans ────────────────

class _FakeUploader:
    def __init__(self, content_raw: str):
        self.content_raw = content_raw
        self.deleted: list[int] = []

    def fetch_post_context(self, post_id: int):
        return {"content_raw": self.content_raw}

    def delete_media(self, media_id: int):
        self.deleted.append(int(media_id))
        return {"success": True, "media_id": int(media_id)}


def test_failed_content_update_deletes_only_unreferenced_uploads():
    from src.services.wordpress import _rollback_unreferenced_uploads

    uploader = _FakeUploader('<img class="wp-image-11"/>')
    result = _rollback_unreferenced_uploads(
        uploader, 5, [{"media_id": 11}, {"media_id": 12}]
    )

    assert uploader.deleted == [12]
    assert result["deleted_media_ids"] == [12]
    assert result["kept_referenced_media_ids"] == [11]


def test_rollback_is_skipped_when_the_post_cannot_be_reloaded():
    from src.services.wordpress import _rollback_unreferenced_uploads

    class _Unreachable(_FakeUploader):
        def fetch_post_context(self, post_id: int):
            return {}

    uploader = _Unreachable("")
    result = _rollback_unreferenced_uploads(uploader, 5, [{"media_id": 12}])

    assert result["attempted"] is False
    assert uploader.deleted == []
