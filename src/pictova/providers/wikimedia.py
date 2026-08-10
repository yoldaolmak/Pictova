"""Wikimedia Commons provider with local cache and attribution sidecars."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


_API = "https://commons.wikimedia.org/w/api.php"
_CACHE = Path(__file__).resolve().parents[3] / "data" / "wikimedia_cache"
_USER_AGENT = "Pictova/0.1 (contact@yoldaolmak.com)"


def search(query: str, count: int = 8) -> list[dict[str, Any]]:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": 6,
        "gsrlimit": max(count * 3, 12),
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
        "iiurlwidth": 2500,
        "format": "json",
        "formatversion": 2,
    }
    req = urllib.request.Request(
        _API + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": _USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read())

    results = []
    for page in payload.get("query", {}).get("pages", []):
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("thumburl") or info.get("url")
        if not url or int(info.get("width") or 0) < 1200:
            continue
        meta = info.get("extmetadata") or {}
        results.append({
            "id": str(page.get("pageid")),
            "title": str(page.get("title") or "").removeprefix("File:"),
            "url": url,
            "source_url": info.get("descriptionurl") or "",
            "width": int(info.get("width") or 0),
            "height": int(info.get("height") or 0),
            "artist": (meta.get("Artist") or {}).get("value", ""),
            "license": (meta.get("LicenseShortName") or {}).get("value", ""),
        })
    query_tokens = set(re.findall(r"[a-z0-9]+", query.casefold()))
    results.sort(
        key=lambda item: len(
            query_tokens & set(re.findall(r"[a-z0-9]+", item["title"].casefold()))
        ),
        reverse=True,
    )
    return results[:count]


def download(result: dict[str, Any]) -> str:
    _CACHE.mkdir(parents=True, exist_ok=True)
    suffix = Path(urllib.parse.urlparse(result["url"]).path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    slug = re.sub(r"[^a-z0-9]+", "-", result["title"].lower()).strip("-")[:80]
    dest = _CACHE / f"commons_{result['id']}_{slug}{suffix}"
    if not dest.exists() or dest.stat().st_size == 0:
        req = urllib.request.Request(result["url"], headers={"User-Agent": _USER_AGENT})
        temp = dest.with_suffix(dest.suffix + ".part")
        try:
            with urllib.request.urlopen(req, timeout=60) as response, temp.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            temp.replace(dest)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
    sidecar = dest.with_suffix(dest.suffix + ".json")
    sidecar.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return str(dest)


__all__ = ["search", "download"]
