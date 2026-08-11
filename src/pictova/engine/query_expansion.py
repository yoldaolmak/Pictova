"""Understand a heading well enough to search for it a second time.

The exact contract comes first: a heading names a place or a product, and an
asset whose title carries that name is the only certain match. Small places
simply do not exist in a stock library, so that first pass returns nothing and
the section stays empty.

A human editor does not stop there. Reading "3. Kozbeyli, Foça" inside a guide
to İzmir villages, they know to look for a stone-house Aegean village even
without a photo labelled Kozbeyli. This module asks the model already used for
vision to make that same leap — and nothing else. It never names a destination,
holds no table, and returns queries rather than decisions.

Two rules keep this from becoming the guessing engine the dictionaries were:

  * The expansion is only consulted after the exact pass fails.
  * Its result is a *query*, still subject to the same candidate verification.
    A broadened search that matches nothing keeps the section empty.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from src.pictova.engine.vision_chain import _parse_json_from_text


_MAX_QUERIES = 3
_MAX_WORDS = 6


def _prompt(heading_text: str, post_title: str) -> str:
    return (
        "Bir seyahat yazısına görsel seçiyorsun. Aşağıdaki bölüm başlığı için "
        "stok fotoğraf aramasında kullanılacak İngilizce sorgular üret.\n\n"
        f"Yazının başlığı: {post_title}\n"
        f"Bölüm başlığı: {heading_text}\n\n"
        "Kurallar:\n"
        "- Bu yerin adıyla arama zaten yapıldı ve sonuç vermedi. Bu yüzden "
        "sorguda YER ADI KULLANMA; yerin nasıl GÖRÜNDÜĞÜNÜ tarif et "
        "(mimari, coğrafya, bitki örtüsü, atmosfer).\n"
        "- Bilmediğin bir yeri tahmin etme; emin değilsen bölgenin genel "
        "görsel karakterini yaz.\n"
        "- Her sorgu en fazla 6 kelime, İngilizce, somut ve aranabilir.\n"
        f"- En fazla {_MAX_QUERIES} sorgu.\n\n"
        "Örnek biçim (içeriği kopyalama):\n"
        '{"queries": ["stone house hillside village", "olive grove terraced slope"]}'
    )


def _clean(query: object) -> str:
    text = re.sub(r"[^\w\s-]", " ", str(query or ""), flags=re.UNICODE)
    return " ".join(text.split()[:_MAX_WORDS]).strip()


def expand_heading_query(
    heading_text: str,
    post_context: Dict[str, Any] | None = None,
    *,
    analyzer: Any = None,
) -> List[str]:
    """Return broader visual queries for a heading, or an empty list.

    An empty list is a normal outcome — no vision source configured, the model
    refused, or the reply was unusable. The caller then keeps whatever the exact
    pass produced, which is the fail-closed behaviour.
    """
    heading_text = str(heading_text or "").strip()
    if not heading_text:
        return []
    post_title = str((post_context or {}).get("title") or "").strip()

    ask = analyzer or _default_analyzer
    try:
        reply = ask(_prompt(heading_text, post_title))
    except Exception:
        return []
    if not reply:
        return []

    try:
        payload = reply if isinstance(reply, dict) else _parse_json_from_text(str(reply))
    except (ValueError, json.JSONDecodeError):
        return []

    raw = payload.get("queries") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    # Case-insensitive de-duplication: the model often restates a suggestion
    # with different capitalisation, and sending the same search twice spends a
    # provider round-trip for nothing.
    seen: set[str] = set()
    queries: List[str] = []
    for item in raw:
        cleaned = _clean(item)
        if not cleaned or cleaned.casefold() in seen:
            continue
        seen.add(cleaned.casefold())
        queries.append(cleaned)
        if len(queries) == _MAX_QUERIES:
            break
    return queries


def _default_analyzer(prompt: str) -> str:
    """Send a text-only prompt through the configured model, cheapest first."""
    from src.pictova.engine import vision_chain

    for send in (_ask_lm_studio, _ask_gemini):
        try:
            answer = send(prompt, vision_chain)
        except Exception:
            continue
        if answer:
            return answer
    return ""


def _ask_lm_studio(prompt: str, vision_chain: Any) -> str:
    import urllib.request

    if not vision_chain._lm_studio_has_vision_model():
        return ""
    body = json.dumps({
        "model": "local",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 400,
    }).encode()
    request = urllib.request.Request(
        "http://localhost:1234/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("choices", [{}])[0].get("message", {}).get("content", "")


def _ask_gemini(prompt: str, vision_chain: Any) -> str:
    import urllib.request

    from src.utils.config import env_str

    keys = [k for k in vision_chain._gemini_api_keys() if vision_chain._gemini_key_available(k)]
    if not keys:
        return ""
    model = env_str("GEMINI_VISION_MODEL") or "gemini-2.5-flash"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 800, "temperature": 0},
    }).encode()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={keys[0]}"
    )
    request = urllib.request.Request(
        url, data=body, method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read())
    return payload["candidates"][0]["content"]["parts"][0]["text"]


__all__ = ["expand_heading_query"]
