"""Pictova Vision Chain — image analysis priority chain.

Priority (no basic fallback ever), matching ``analyze_image_vision_chain``:
  1. LM Studio local vision model (free, keeps API quota unspent)
  2. Gemini Flash REST (GEMINI_API_KEYS or GEMINI_API_KEY — Google AI Studio)
  3. OpenAI mini vision API (cheap bounded fallback)
  4. Codex CLI web login  (codex exec --yolo, ~/.codex/auth.json)
  5. Claude CLI web login (claude --print --allowedTools Read)

Any one succeeds → returns.
All fail → RuntimeError (NO basic fallback).
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

from src.utils.config import env_str


# A 401 means the key itself is rejected, so it stays disabled. A 429/503 is a
# transient quota or capacity signal: disabling such a key for the lifetime of
# the `serve` process used to silence a key that recovers within minutes.
_GEMINI_REJECTED_KEYS: set[str] = set()
_GEMINI_COOLDOWN_UNTIL: dict[str, float] = {}
_GEMINI_COOLDOWN_SECONDS = 15 * 60


def _gemini_key_available(api_key: str) -> bool:
    if api_key in _GEMINI_REJECTED_KEYS:
        return False
    until = _GEMINI_COOLDOWN_UNTIL.get(api_key)
    if until is None:
        return True
    if time.monotonic() >= until:
        del _GEMINI_COOLDOWN_UNTIL[api_key]
        return True
    return False


def _gemini_api_keys() -> list[str]:
    """Return the configured Gemini keys, plural variable first."""
    raw = env_str("GEMINI_API_KEYS") or env_str("GEMINI_API_KEY") or ""
    return list(dict.fromkeys(key.strip() for key in raw.split(",") if key.strip()))


# ── Common helpers ────────────────────────────────────────────────────────

def _image_b64(image_path: str, max_side: int = 0) -> tuple[str, str]:
    """(base64_str, mime_type). If max_side>0, creates a thumbnail via PIL."""
    import io
    p = Path(image_path)
    mime = "image/jpeg"
    if max_side > 0:
        try:
            from PIL import Image as _PIL
            img = _PIL.open(str(p)).convert("RGB")
            img.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=70)
            return base64.b64encode(buf.getvalue()).decode(), mime
        except Exception:
            pass
    ext = p.suffix.lower()
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode(), mime


def _strip_ansi(text: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*m|\x1b\[?[0-9;]*[a-zA-Z]', '', text)


def _parse_json_from_text(text: str) -> Dict:
    """Extract a JSON block from text."""
    text = text.strip()
    # ```json ... ``` block
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        return json.loads(m.group(1))
    # First { ... }
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"JSON bulunamadı: {text[:200]}")


def _vision_prompt(image_path: str, location_hint: str, post_context: Dict) -> str:
    # This prompt deliberately receives no article title, heading, location,
    # or photo-library labels. Those are selection hints, not pixel evidence;
    # showing them to vision lets a model invent a brand or landmark to match
    # the requested section (for example, calling any beach portrait "Tinder").
    del image_path, location_hint, post_context
    return (
        f"Görseli yalnızca görünen piksellere dayanarak analiz et ve SADECE JSON döndür.\n"
        f"Başlık, lokasyon veya yazı bağlamı verilmemiştir: görünmeyen marka, uygulama, kişi, yer veya olayı tahmin etme.\n\n"
        f"Kurallar:\n"
        f"- alt: Ekran okuyucu ve erişilebilirlik için sade görsel tanımı (Türkçe, maks 120 kr)\n"
        f"- title: Yalnızca görünür konu veya okunabilen işaret/markadan oluşan kısa başlık (Türkçe, maks 60 kr)\n"
        f"- visible_text: Ekran, tabela veya logoda gerçekten okunabilen metin; yoksa boş string\n"
        f"- caption/description: Kısa görsel bilgisi; editoryal cümle veya hikâye yazma\n"
        f"- summary: Tek cümle özet (Türkçe, maks 120 kr)\n"
        f"- keywords: 3-5 adet anahtar kelime (Türkçe)\n"
        f"- scene/activity: Kategori ve aktivite (İngilizce)\n"
        f"- story_score: Seyahat değeri (0.0 - 1.0)\n\n"
        f"{{\"alt\":\"...\",\"title\":\"...\",\"visible_text\":\"...\",\"caption\":\"...\",\"description\":\"...\",\"summary\":\"...\",\"keywords\":[],\"people\":[],\"scene\":\"...\",\"activity\":\"...\",\"story_score\":0.8}}"
    )


# ── 1. Gemini Flash REST API ─────────────────────────────────────────────────

def _analyze_gemini_flash(
    image_path: str,
    location_hint: str,
    post_context: Dict,
) -> Dict[str, Any]:
    keys_list = _gemini_api_keys()
    available_keys = [key for key in keys_list if _gemini_key_available(key)]
    if not available_keys:
        raise RuntimeError("No usable Gemini key remains right now")

    # Gemini quota is useful only if its request stays small enough for a
    # tethered connection. Metadata does not need the original multi-megabyte
    # source; the same bounded 1024px evidence used by the paid mini fallback
    # preserves semantic inspection while avoiding a needless upload.
    b64, mime = _image_b64(image_path, max_side=1024)
    prompt = _vision_prompt(image_path, location_hint, post_context)
    model = env_str("GEMINI_VISION_MODEL") or "gemini-2.5-flash"

    body = json.dumps({
        "contents": [{
            "parts": [
                {"inline_data": {"mime_type": mime, "data": b64}},
                {"text": prompt},
            ]
        }],
        "generationConfig": {"maxOutputTokens": 400, "temperature": 0.2},
    }).encode()

    data = None
    last_error = None
    for api_key in available_keys:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        try:
            req = urllib.request.Request(url, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            break
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code in (401, 429, 503):
                if e.code == 401:
                    _GEMINI_REJECTED_KEYS.add(api_key)
                    scope = "rejected, key disabled"
                else:
                    _GEMINI_COOLDOWN_UNTIL[api_key] = time.monotonic() + _GEMINI_COOLDOWN_SECONDS
                    scope = f"throttled, key paused for {_GEMINI_COOLDOWN_SECONDS // 60}m"
                print(f"  [!] Gemini {e.code} (key ...{api_key[-5:]}), {scope}", file=sys.stderr)
                continue
            raise

    if data is None:
        raise RuntimeError(f"Gemini keys exhausted: {last_error}")

    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return _parse_json_from_text(text)


def _analyze_openai_mini(
    image_path: str,
    location_hint: str,
    post_context: Dict,
) -> Dict[str, Any]:
    """Use the configured low-cost OpenAI vision fallback after Gemini."""
    if not env_str("OPENAI_API_KEY"):
        raise RuntimeError("OpenAI vision key is not configured")

    from src.core.metadata_generator import YOMetadataGenerator

    # A 1024px JPEG preserves enough visual evidence for metadata while
    # avoiding an unnecessary multi-megabyte API upload on a mobile hotspot.
    image_data, media_type = _image_b64(image_path, max_side=1024)
    result = YOMetadataGenerator(use_gpt=True)._analyze_gpt(
        image_data,
        media_type,
        _vision_prompt(image_path, location_hint, post_context),
    )
    analysis = result.get("analysis") if isinstance(result, dict) else None
    if not isinstance(analysis, dict):
        raise RuntimeError("OpenAI vision returned no metadata object")
    return analysis


# ── 2. Codex CLI web login ───────────────────────────────────────────────────

def _codex_check_login() -> bool:
    auth = Path.home() / ".codex" / "auth.json"
    if not auth.exists():
        return False
    try:
        d = json.loads(auth.read_text())
        t = d.get("tokens", {})
        return bool(t.get("access_token") or t.get("id_token"))
    except Exception:
        return False


def _find_bin(name: str) -> str | None:
    """shutil.which + known npm prefix locations."""
    found = shutil.which(name)
    if found:
        return found
    candidates = [
        Path.home() / "AI" / "npm" / "bin" / name,
        Path("/usr/local/bin") / name,
        Path("/opt/homebrew/bin") / name,
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


def _analyze_codex(
    image_path: str,
    location_hint: str,
    post_context: Dict,
) -> Dict[str, Any]:
    if not _codex_check_login():
        raise RuntimeError("No Codex session — run: codex login")

    codex_bin = _find_bin("codex")
    if not codex_bin:
        raise RuntimeError("codex CLI not found")

    prompt_text = _vision_prompt(image_path, location_hint, post_context)
    full_prompt = (
        f"Analyze the image file at path: {image_path}\n\n"
        f"{prompt_text}"
    )

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as of:
        out_path = of.name

    try:
        result = subprocess.run(
            [codex_bin, "exec", "--yolo", "--skip-git-repo-check", "-o", out_path, "-"],
            input=full_prompt,
            text=True, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Codex rc={result.returncode}: {(result.stderr or '')[-500:]}")
        answer = Path(out_path).read_text(encoding="utf-8").strip()
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass

    if not answer:
        raise RuntimeError("Codex returned an empty response")
    return _parse_json_from_text(answer)


# ── 3. Claude CLI web login ──────────────────────────────────────────────────

def _prepare_image_for_cli(image_path: str, max_side: int = 512) -> str:
    """Convert HEIC or large files to a small JPEG thumbnail. Returns the path."""
    p = Path(image_path)
    ext = p.suffix.lower()
    # A fixed /tmp name is both a collision between concurrent runs on the same
    # stem and a world-writable path another user can pre-create.
    thumb_dir = Path(tempfile.mkdtemp(prefix="pictova_thumb_"))
    tmp = thumb_dir / f"{p.stem}.jpg"

    # 1. Conversion via PIL (best quality)
    try:
        from PIL import Image as _PIL, ImageOps as _IO
        img = _IO.exif_transpose(_PIL.open(str(p))).convert("RGB")
        img.thumbnail((max_side, max_side))
        img.save(str(tmp), "JPEG", quality=75)
        if tmp.exists() and tmp.stat().st_size > 0:
            return str(tmp)
    except Exception:
        pass

    # 2. sips fallback — for all formats including HEIC
    sips_bin = shutil.which("sips")
    if sips_bin:
        r = subprocess.run(
            [sips_bin, "-s", "format", "jpeg", "-Z", str(max_side), str(p), "--out", str(tmp)],
            capture_output=True, timeout=30,
        )
        if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            return str(tmp)

    # 3. ImageMagick convert (optional)
    convert_bin = shutil.which("convert")
    if convert_bin:
        r = subprocess.run(
            [convert_bin, f"{p}[0]", "-resize", f"{max_side}x{max_side}>", "-quality", "75", str(tmp)],
            capture_output=True, timeout=30,
        )
        if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 0:
            return str(tmp)

    # Could not convert — return the original
    return image_path


def _analyze_claude_cli(
    image_path: str,
    location_hint: str,
    post_context: Dict,
) -> Dict[str, Any]:
    claude_bin = _find_bin("claude")
    if not claude_bin:
        raise RuntimeError("claude CLI not found")

    # Convert HEIC and large files to small JPEG (Claude Read tool 256KB limit)
    ready_path = _prepare_image_for_cli(image_path)

    prompt = (
        f"Read the image at: {ready_path}\n\n"
        + _vision_prompt(image_path, location_hint, post_context)
    )

    result = subprocess.run(
        [claude_bin, "--print", "--allowedTools", "Read", "--dangerously-skip-permissions",
         "--model", "claude-haiku-4-5-20251001"],
        input=prompt, text=True, check=False,
        capture_output=True, timeout=120,
    )
    output = _strip_ansi((result.stdout or "").strip())
    stderr = _strip_ansi((result.stderr or "").strip())
    if result.returncode != 0 or not output:
        detail = stderr[-300:] if stderr else "(stderr empty)"
        raise RuntimeError(f"Claude CLI rc={result.returncode}: {detail}")
    return _parse_json_from_text(output)


def _pick_lm_studio_vision_model(models: list) -> str:
    """Pick the highest-priority vision-capable model from the LM Studio model list.

    Scans by priority so that a higher-priority match anywhere in the list wins
    over a lower-priority match earlier in the list.
    """
    checks = [
        lambda mid: "vl" in mid and "qwen" in mid,
        lambda mid: "vl" in mid,
        lambda mid: "vision" in mid,
        lambda mid: "instruct" in mid and "coder" not in mid,
    ]
    for check in checks:
        for model in models:
            if check(model["id"].lower()):
                return model["id"]
    raise RuntimeError(
        "LM Studio'da gorsel analiz destekleyen model bulunamadi. "
        "qwen2.5-vl-7b-instruct modelini yukleyin."
    )


def _lm_studio_has_vision_model() -> bool:
    """Return True only if LM Studio is running AND has a vision-capable model loaded."""
    try:
        with urllib.request.urlopen("http://localhost:1234/v1/models", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for model in data.get("data", []):
                mid = model["id"].lower()
                if "vl" in mid or "vision" in mid:
                    return True
    except Exception:
        pass
    return False


def _analyze_lm_studio(
    image_path: str,
    location_hint: str,
    post_context: Dict,
) -> Dict[str, Any]:
    url_models = "http://localhost:1234/v1/models"
    url_chat = "http://localhost:1234/v1/chat/completions"

    try:
        req_models = urllib.request.Request(url_models)
        with urllib.request.urlopen(req_models, timeout=2) as resp:
            models_data = json.loads(resp.read().decode("utf-8"))
            models = models_data.get("data", [])
            if not models:
                raise RuntimeError("LM Studio'da yuklu model bulunamadi")
            model_id = _pick_lm_studio_vision_model(models)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"LM Studio cevap vermiyor: {e}")

    # Prepare image
    # _image_b64 sırasıyla (veri, MIME) döndürür. Bunlar ters atandığında
    # LM Studio'ya `data:<base64>;base64,image/jpeg` gönderiliyor ve görsel
    # model isteği daha analiz aşamasına gelmeden reddediliyordu.
    b64_data, b64_mime = _image_b64(image_path, max_side=1024)
    prompt = _vision_prompt(image_path, location_hint, post_context)

    system_msg = (
        "Sen bir seyahat fotoğrafı analiz asistanısın. Görselleri nesnel, sade ve doğal bir dille analiz edersin. "
        "Hiçbir açıklama eklemeden, sadece düz JSON formatında yanıt verirsin."
    )

    payload = {
        "model": model_id,
        "messages": [
            {
                "role": "system",
                "content": system_msg
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{b64_mime};base64,{b64_data}"
                        }
                    }
                ]
            }
        ],
        "temperature": 0.3,
        "max_tokens": 800
    }

    req = urllib.request.Request(
        url_chat,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8')
        # If model doesn't support images, skip gracefully
        if "does not support image" in err_body or e.code == 400:
            raise RuntimeError(f"LM Studio model does not support images: {err_body[:200]}")
        raise RuntimeError(f"LM Studio API Error: {e.code} - {err_body[:200]}")
    except Exception as e:
        raise RuntimeError(f"LM Studio API Connection Error: {e}")
        
    choice = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    output = _strip_ansi(choice.strip())
    if not output:
        raise RuntimeError("LM Studio returned an empty response")
        
    return _parse_json_from_text(output)


# ── Main chain ────────────────────────────────────────────────────────────────

def analyze_image_vision_chain(
    image_path: str,
    *,
    location_hint: str = "",
    post_context: Dict | None = None,
) -> Dict[str, Any]:
    """Image analysis via priority chain. NO basic fallback.

    Returns: {"alt":..., "title":..., "caption":..., "description":..., "keywords":[...], "source":"..."}
    All fail → RuntimeError.
    """
    post_context = post_context or {}
    errors: list[str] = []

    # 1. LM Studio (Local, if running, try first to save API tokens)
    try:
        result = _analyze_lm_studio(image_path, location_hint, post_context)
        result["source"] = "lm_studio"
        return result
    except Exception as exc:
        errors.append(f"lm_studio: {exc}")

    # 2. Gemini Flash
    try:
        result = _analyze_gemini_flash(image_path, location_hint, post_context)
        result["source"] = "gemini_flash"
        return result
    except Exception as exc:
        errors.append(f"gemini_flash: {exc}")

    # 2. Cheap OpenAI vision fallback. Do this before invoking an interactive
    # CLI model, which is slower and consumes substantially more task tokens.
    try:
        result = _analyze_openai_mini(image_path, location_hint, post_context)
        result["source"] = "openai_mini"
        return result
    except Exception as exc:
        errors.append(f"openai_mini: {exc}")

    # 3. Codex CLI
    try:
        result = _analyze_codex(image_path, location_hint, post_context)
        result["source"] = "codex_cli"
        return result
    except Exception as exc:
        errors.append(f"codex_cli: {exc}")

    # 4. Claude CLI
    try:
        result = _analyze_claude_cli(image_path, location_hint, post_context)
        result["source"] = "claude_cli"
        return result
    except Exception as exc:
        errors.append(f"claude_cli: {exc}")

    raise RuntimeError(
        "Görsel analizi başarısız — tüm kaynaklar denendi:\n"
        + "\n".join(f"  • {e}" for e in errors)
    )


def has_any_vision_source() -> bool:
    """Is at least one vision source available?"""
    if _lm_studio_has_vision_model():
        return True
        
    if any(_gemini_key_available(key) for key in _gemini_api_keys()):
        return True
    if env_str("OPENAI_API_KEY"):
        return True
    if _codex_check_login() and _find_bin("codex"):
        return True
    if _find_bin("claude"):
        return True
    return False


def download_icloud_photo(uuid: str, dest_dir: str | None = None) -> str:
    """Download an iCloud photo by UUID, returns the local path.

    Requires python3.11 and osxphotos.
    If dest_dir is not provided, /tmp/pictova_icloud/ is used.
    """
    import subprocess as _sp
    import tempfile as _tmp

    dest = Path(dest_dir) if dest_dir else Path(_tmp.gettempdir()) / "pictova_icloud"
    dest.mkdir(parents=True, exist_ok=True)

    # UUID ve hedef dizin argv üzerinden geçirilir. Kaynak koda gömüldüklerinde
    # tırnak içeren bir değer script'i sessizce bozuyor ve rastgele kod
    # çalıştırılabilir bir yüzey bırakıyordu.
    script = (
        "import osxphotos, sys\n"
        "uuid, dest = sys.argv[1], sys.argv[2]\n"
        "db = osxphotos.PhotosDB()\n"
        "res = db.query(osxphotos.QueryOptions(uuid=[uuid]))\n"
        "if not res: sys.exit(1)\n"
        "exported = res[0].export(dest, use_photos_export=True, overwrite=True, timeout=300)\n"
        "print(exported[0] if exported else '')\n"
    )

    py311 = shutil.which("python3.11") or "python3.11"
    result = _sp.run(
        [py311, "-c", script, str(uuid), str(dest)],
        capture_output=True, text=True, timeout=360,
    )
    path = result.stdout.strip()
    if result.returncode != 0 or not path:
        raise RuntimeError(
            f"iCloud download failed (uuid={uuid}): {result.stderr[-300:]}"
        )
    return path


__all__ = ["analyze_image_vision_chain", "has_any_vision_source", "download_icloud_photo"]
