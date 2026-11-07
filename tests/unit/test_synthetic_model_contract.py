"""Exercise Pictova's existing model boundary with offline OpenAI-compatible replies.

The image pixels and model answers here are *synthetic*. These tests establish
transport, metadata and rejection behavior, not real-world visual recognition.
"""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest
from PIL import Image

from src.pictova.engine import metadata, query_expansion, vision_chain
from src.pictova.engine.quality import quality_gate_native_batch


class SyntheticOpenRouterTransport:
    """In-process OpenAI chat-completion envelope; no socket or credentials."""

    def __init__(self, content, *, finish_reason="stop"):
        self.content = content
        self.finish_reason = finish_reason
        self.requests = []

    def __call__(self, request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        assert url.startswith("http://localhost:1234/v1/"), "Unexpected external network request"
        if url.endswith("/models"):
            return io.BytesIO(json.dumps({"data": [{"id": "qwen2.5-vl-7b-instruct"}]}).encode())
        assert url.endswith("/chat/completions"), url
        self.requests.append(json.loads(request.data.decode()))
        payload = {
            "id": "synthetic-chat-1",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": self.content},
                    "finish_reason": self.finish_reason,
                }
            ],
        }
        return io.BytesIO(json.dumps(payload, ensure_ascii=False).encode())


def _photo(tmp_path):
    path = tmp_path / "offline-visual.jpg"
    Image.new("RGB", (80, 60), (55, 120, 190)).save(path)
    return str(path)


def _quality_inputs():
    return {
        "final_size": (1200, 750),
        "brightness": 0.52,
        "saturation": 0.38,
        "contrast": 0.22,
        "color_temp": 0.10,
        "file_size_kb": 128,
        "blur_score": 860,
        "original_size": (2400, 1600),
    }


def _run_metadata(tmp_path, description):
    path = _photo(tmp_path)
    fake = SyntheticOpenRouterTransport(json.dumps(description, ensure_ascii=False))
    heading = {"text": "2. BlaBlaCar", "level": 3, "required_heading_tokens": ["blablacar"]}
    context = {"title": "Seyahat Uygulamaları", "slug": "seyahat-uygulamalari"}
    with (
        patch("src.pictova.engine.vision_chain.urllib.request.urlopen", side_effect=fake),
        patch("src.pictova.engine.metadata._db_cached_metadata", return_value=None),
        patch("src.pictova.engine.vision_chain._analyze_gemini_flash") as gemini,
        patch("src.pictova.engine.vision_chain._analyze_openai_mini") as openai,
        patch("src.pictova.engine.vision_chain._analyze_codex") as codex,
        patch("src.pictova.engine.vision_chain._analyze_claude_cli") as claude,
    ):
        result, warnings = metadata.build_native_metadata_map(
            [path], assigned_headings={path: heading}, post_context=context,
        )
    for provider in (gemini, openai, codex, claude):
        provider.assert_not_called()
    assert len(fake.requests) == 1
    prompt = fake.requests[0]["messages"][1]["content"][0]["text"]
    assert "BlaBlaCar" not in prompt and "Seyahat Uygulamaları" not in prompt
    image_url = fake.requests[0]["messages"][1]["content"][1]["image_url"]["url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    assert warnings
    approved, approved_meta, _, blocked = quality_gate_native_batch(
        processed_images=[path],
        metadata_dict=result,
        processed_details={path: _quality_inputs()},
        post_context=context,
    )
    return path, result[path], approved, approved_meta, blocked


def test_offline_openrouter_envelope_flows_through_native_metadata_and_quality(tmp_path):
    path, item, approved, metadata_map, blocked = _run_metadata(
        tmp_path,
        {
            "alt": "Akıllı telefonda görünen BlaBlaCar yolculuk paylaşım uygulaması ekranı",
            "title": "BlaBlaCar yolculuk paylaşımı ekranı",
            "description": "Akıllı telefonda BlaBlaCar logosu ve yolculuk paylaşımı ekranı",
            "summary": "BlaBlaCar logosunun görülebildiği akıllı telefon ekranı",
            "visible_text": "BlaBlaCar",
            "keywords": ["BlaBlaCar", "telefon", "yolculuk"],
            "scene": "mobile app screen",
        },
    )
    assert approved == [path], blocked
    assert metadata_map[path]["title"] == "BlaBlaCar"
    assert "blablacar" in item["visual_evidence"].casefold()
    assert blocked == []


def test_offline_model_cannot_turn_unrelated_beach_visual_into_named_app(tmp_path):
    path, item, approved, _, blocked = _run_metadata(
        tmp_path,
        {
            "alt": "Deniz kenarındaki salıncakta oturan kişi ve kumlu sahil görünümü",
            "title": "Sahilde bir salıncak",
            "description": "Kumsal ve palmiye ağaçlarının görüldüğü deniz manzarası",
            "summary": "Kumlu plajda salıncakta bir kişi",
            "visible_text": "",
            "keywords": ["sahil", "salıncak", "deniz"],
            "scene": "beach",
        },
    )
    assert item["title"] == "BlaBlaCar", "Editorial headings may shape publishing titles"
    assert "blablacar" not in item["visual_evidence"].casefold()
    assert approved == []
    assert len(blocked) == 1 and blocked[0]["file"] == path
    assert "visual evidence does not confirm exact assigned-heading entity" in blocked[0]["errors"]


def test_offline_openrouter_query_expansion_is_only_search_suggestion():
    fake = SyntheticOpenRouterTransport('{"queries":["mountain landscape", "stone buildings"]}')
    with patch("src.pictova.engine.vision_chain.urllib.request.urlopen", side_effect=fake):
        result = query_expansion.expand_heading_query(
            "3. Uçhisar Kalesi", {"title": "Kapadokya Gezi Rehberi"}
        )
    assert result == ["mountain landscape", "stone buildings"]
    assert fake.requests[0]["model"] == "local"


@pytest.mark.parametrize(
    "model_content",
    [
        "not json at all",
        '{"alt":"unfinished"',
        "[1,2,3]",
        '{"alt":"x"}' + " " * 70000,
    ],
)
def test_malformed_or_oversize_openrouter_reply_rejected_without_content_echo(tmp_path, model_content):
    fake = SyntheticOpenRouterTransport(model_content)
    with (
        patch("src.pictova.engine.vision_chain.urllib.request.urlopen", side_effect=fake),
        pytest.raises((ValueError, RuntimeError)) as error,
    ):
        vision_chain._analyze_lm_studio(_photo(tmp_path), "private heading", {"title": "private post"})
    assert "private heading" not in str(error.value)
    assert "private post" not in str(error.value)
    assert model_content[:100] not in str(error.value)


def test_truncated_openrouter_completion_is_not_trusted_as_visual_evidence(tmp_path):
    fake = SyntheticOpenRouterTransport('{"alt":"looks valid"}', finish_reason="length")
    with (
        patch("src.pictova.engine.vision_chain.urllib.request.urlopen", side_effect=fake),
        pytest.raises((ValueError, RuntimeError), match="truncat|incomplete|invalid"),
    ):
        vision_chain._analyze_lm_studio(_photo(tmp_path), "", {})
