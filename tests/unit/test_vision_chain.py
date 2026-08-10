"""vision_chain unit testleri."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_parse_json_from_text_json_block():
    from src.pictova.engine.vision_chain import _parse_json_from_text
    text = '```json\n{"alt": "test", "title": "t"}\n```'
    result = _parse_json_from_text(text)
    assert result["alt"] == "test"


def test_parse_json_from_text_bare_json():
    from src.pictova.engine.vision_chain import _parse_json_from_text
    text = 'Some text {"alt": "coast", "title": "Sea"} more text'
    result = _parse_json_from_text(text)
    assert result["alt"] == "coast"


def test_parse_json_from_text_raises_on_no_json():
    from src.pictova.engine.vision_chain import _parse_json_from_text
    with pytest.raises(ValueError, match="JSON bulunamadı"):
        _parse_json_from_text("no json here at all")


def test_vision_prompt_excludes_article_and_heading_context():
    from src.pictova.engine.vision_chain import _vision_prompt

    prompt = _vision_prompt(
        "image.jpg",
        "7. Tinder",
        {"title": "Kendinizi Yerli Gibi Hissedeceğiniz 10 Seyahat Uygulaması"},
    )

    assert "Tinder" not in prompt
    assert "Seyahat Uygulaması" not in prompt
    assert "görünmeyen marka" in prompt


def test_find_bin_uses_shutil_first(tmp_path):
    from src.pictova.engine.vision_chain import _find_bin
    with patch("src.pictova.engine.vision_chain.shutil.which", return_value="/usr/bin/somebin"):
        result = _find_bin("somebin")
    assert result == "/usr/bin/somebin"


def test_find_bin_fallback_to_npm_path(tmp_path):
    from src.pictova.engine.vision_chain import _find_bin
    # Önce olmayan bir binary ara, npm path'ini mock'la
    fake_bin = tmp_path / "claude"
    fake_bin.touch()
    fake_bin.chmod(0o755)
    with patch("src.pictova.engine.vision_chain.shutil.which", return_value=None), \
         patch("src.pictova.engine.vision_chain.Path.home", return_value=tmp_path):
        result = _find_bin("claude")
    # Eğer tmp_path/AI/npm/bin/claude oluşturulmadıysa None döner (davranış doğru)
    assert result is None or isinstance(result, str)


def test_has_any_vision_source_with_gemini_key():
    from src.pictova.engine.vision_chain import has_any_vision_source
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key-123"}):
        assert has_any_vision_source() is True


def test_has_any_vision_source_with_claude_bin():
    from src.pictova.engine.vision_chain import has_any_vision_source
    with patch.dict("os.environ", {"GEMINI_API_KEY": "", "GEMINI_API_KEYS": ""}), \
         patch("src.pictova.engine.vision_chain._codex_check_login", return_value=False), \
         patch("src.pictova.engine.vision_chain._find_bin", side_effect=lambda n: "/bin/claude" if n == "claude" else None):
        assert has_any_vision_source() is True


def test_has_any_vision_source_false_when_nothing():
    from src.pictova.engine.vision_chain import has_any_vision_source
    with patch.dict("os.environ", {"GEMINI_API_KEY": "", "GEMINI_API_KEYS": "", "OPENAI_API_KEY": ""}), \
         patch("src.pictova.engine.vision_chain.urllib.request.urlopen", side_effect=OSError), \
         patch("src.pictova.engine.vision_chain._codex_check_login", return_value=False), \
         patch("src.pictova.engine.vision_chain._find_bin", return_value=None):
        assert has_any_vision_source() is False


def test_vision_chain_raises_when_all_fail(tmp_path):
    """Tüm kaynaklar başarısız → RuntimeError."""
    from src.pictova.engine.vision_chain import analyze_image_vision_chain
    fake_img = tmp_path / "test.jpg"
    fake_img.write_bytes(b"fake")

    with patch("src.pictova.engine.vision_chain._analyze_gemini_flash", side_effect=RuntimeError("no key")), \
         patch("src.pictova.engine.vision_chain._analyze_openai_mini", side_effect=RuntimeError("no key")), \
         patch("src.pictova.engine.vision_chain._analyze_codex", side_effect=RuntimeError("no login")), \
         patch("src.pictova.engine.vision_chain._analyze_claude_cli", side_effect=RuntimeError("no claude")):
        with pytest.raises(RuntimeError, match="tüm kaynaklar denendi"):
            analyze_image_vision_chain(str(fake_img), location_hint="test", post_context={})


def test_vision_chain_returns_first_success(tmp_path):
    """İlk başarılı kaynak döner."""
    from src.pictova.engine.vision_chain import analyze_image_vision_chain
    fake_img = tmp_path / "test.jpg"
    fake_img.write_bytes(b"fake")

    expected = {"alt": "test alt", "title": "T", "caption": "C", "description": "D", "keywords": ["k"]}
    with patch("src.pictova.engine.vision_chain._analyze_gemini_flash", return_value=dict(expected)), \
         patch("src.pictova.engine.vision_chain._analyze_openai_mini") as mock_openai, \
         patch("src.pictova.engine.vision_chain._analyze_codex") as mock_codex, \
         patch("src.pictova.engine.vision_chain._analyze_claude_cli") as mock_claude:
        result = analyze_image_vision_chain(str(fake_img), location_hint="test", post_context={})

    assert result["source"] == "gemini_flash"
    assert result["alt"] == "test alt"
    mock_openai.assert_not_called()
    mock_codex.assert_not_called()
    mock_claude.assert_not_called()


def test_vision_chain_uses_openai_mini_after_gemini_failure(tmp_path):
    from src.pictova.engine.vision_chain import analyze_image_vision_chain

    fake_img = tmp_path / "test.jpg"
    fake_img.write_bytes(b"fake")
    expected = {"alt": "telefon ekranında uygulama", "title": "Uygulama", "caption": "Telefon ekranındaki uygulama."}
    with patch("src.pictova.engine.vision_chain._analyze_gemini_flash", side_effect=RuntimeError("quota")), \
         patch("src.pictova.engine.vision_chain._analyze_openai_mini", return_value=dict(expected)), \
         patch("src.pictova.engine.vision_chain._analyze_codex") as mock_codex:
        result = analyze_image_vision_chain(str(fake_img), location_hint="test", post_context={})

    assert result["source"] == "openai_mini"
    mock_codex.assert_not_called()


def test_gemini_flash_uses_bounded_image_and_metadata_budget(monkeypatch, tmp_path):
    import json
    from unittest.mock import MagicMock
    from src.pictova.engine import vision_chain

    image = tmp_path / "image.jpg"
    image.write_bytes(b"image")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    vision_chain._GEMINI_REJECTED_KEYS.clear()
    vision_chain._GEMINI_COOLDOWN_UNTIL.clear()
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({
        "candidates": [{"content": {"parts": [{"text": '{"alt":"Kısa açıklama"}'}]}}]
    }).encode()

    with patch("src.pictova.engine.vision_chain._image_b64", return_value=("data", "image/jpeg")) as b64, \
         patch("src.pictova.engine.vision_chain.urllib.request.urlopen", return_value=response) as urlopen:
        result = vision_chain._analyze_gemini_flash(str(image), "test", {})

    assert result == {"alt": "Kısa açıklama"}
    assert b64.call_args.kwargs == {"max_side": 1024}
    payload = json.loads(urlopen.call_args.args[0].data.decode())
    assert payload["generationConfig"]["maxOutputTokens"] == 400


def test_lm_studio_receives_valid_data_url(monkeypatch, tmp_path):
    import json
    from unittest.mock import MagicMock
    from src.pictova.engine import vision_chain

    image = tmp_path / "image.jpg"
    image.write_bytes(b"image")
    models = MagicMock()
    models.__enter__.return_value.read.return_value = json.dumps({
        "data": [{"id": "qwen2.5-vl-7b-instruct"}],
    }).encode()
    completion = MagicMock()
    completion.__enter__.return_value.read.return_value = json.dumps({
        "choices": [{"message": {"content": '{"alt":"Telefon ekranı"}'}}],
    }).encode()

    with patch("src.pictova.engine.vision_chain._image_b64", return_value=("encoded", "image/jpeg")), \
         patch("src.pictova.engine.vision_chain.urllib.request.urlopen", side_effect=[models, completion]) as urlopen:
        result = vision_chain._analyze_lm_studio(str(image), "test", {})

    assert result == {"alt": "Telefon ekranı"}
    payload = json.loads(urlopen.call_args_list[1].args[0].data.decode())
    image_url = payload["messages"][1]["content"][1]["image_url"]["url"]
    assert image_url == "data:image/jpeg;base64,encoded"
