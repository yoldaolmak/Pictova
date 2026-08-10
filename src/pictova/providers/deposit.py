"""DepositPhotos provider — arama + lisanslı indirme."""

from __future__ import annotations

import json
import os
import shutil
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.config import env_str


_API_URL = "https://api.depositphotos.com/"

# Başlıkta bu kelimeler varsa reddet
_BLOCKED_TITLE_FRAGMENTS = (
    "hotel", "resort", "spa ", "waterpark", "water park",
    "bikini", "young woman", "woman smiling", "man smiling",
    "tourists posing", "couple", "selfie",
    "logo", "icon", "illustration", "vector", "clipart",
    "map of", "infographic", "banner", "poster", "flyer",
    "3d render", "3d model", "rendering",
)

# Minimum kalite eşiği
_MIN_WIDTH = 3000      # piksel — küçük stok fotoğrafları elenir
_MIN_DOWNLOADS = 2     # neredeyse hiç indirilmemiş = düşük kalite sinyali
_MIN_SCORE = 2         # toplam puan eşiği
_TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}
_RETRY_DELAYS_SECONDS = (0.5, 1.5)
_DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "deposit_cache"
# Mobil erişim noktasında 1 MiB tek bir read() çağrısı 20 saniyelik soket
# zaman aşımını geçebiliyordu. Küçük parça, aynı toplam kaliteyi korurken
# aktarımın düzenli ilerlemesini ve kaldığı yerden sürmesini sağlar.
_DOWNLOAD_CHUNK_BYTES = 128 * 1024
_DOWNLOAD_DEADLINE_SECONDS = 120
_SESSION_ID: Optional[str] = None


def _ssl_ctx() -> ssl.SSLContext:
    """Doğrulanmış TLS bağlamı.

    `login` çağrısı API anahtarını ve hesap parolasını taşıdığı için sertifika
    doğrulaması kapatılamaz. LibreSSL ile derlenmiş Python'da sistem kök
    deposu eksik kalabildiğinden, varsa certifi paketi tercih edilir.
    """
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


def _urlopen_with_retry(req: urllib.request.Request, *, timeout: int):
    attempts = len(_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(attempts):
        try:
            return urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx())
        except urllib.error.HTTPError as exc:
            if exc.code not in _TRANSIENT_HTTP_CODES or attempt == attempts - 1:
                raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == attempts - 1:
                raise
        time.sleep(_RETRY_DELAYS_SECONDS[attempt])
    raise RuntimeError("DepositPhotos request retry exhausted")


def _post(payload: Dict) -> Dict:
    req = urllib.request.Request(
        _API_URL,
        data=urllib.parse.urlencode(payload).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with _urlopen_with_retry(req, timeout=30) as r:
        return json.loads(r.read())


def _api_key() -> str:
    # env_str loads the project .env itself. Reading os.getenv directly made
    # this provider silently depend on some earlier caller having invoked
    # apply_environment() first.
    key = env_str("DEPOSIT_API_KEY")
    if not key:
        raise RuntimeError("DEPOSIT_API_KEY bulunamadı — .env dosyasını kontrol et")
    return key


def _login() -> str:
    """Return one reusable DepositPhotos session for the current process."""
    global _SESSION_ID
    if _SESSION_ID:
        return _SESSION_ID
    api_key = _api_key()
    user = env_str("DEPOSIT_LOGIN_USER", "yoldaolmak")
    pwd = env_str("DEPOSIT_LOGIN_PASSWORD", "") or ""
    r = _post({"dp_command": "login", "dp_apikey": api_key,
                "dp_login_user": user, "dp_login_password": pwd})
    if r.get("type") != "success":
        raise RuntimeError(f"DepositPhotos login başarısız: {r.get('error', {}).get('errormsg', r)}")
    _SESSION_ID = str(r["sessionid"])
    return _SESSION_ID


def _score(result: Dict, query_words: list[str]) -> int:
    """Fotoğrafı puanla. Yüksek = daha iyi. Negatif = elenir."""
    title = (result.get("title") or "").lower()
    tags = " ".join(result.get("tags") or []).lower()

    # Hard reddetler
    if any(frag in title for frag in _BLOCKED_TITLE_FRAGMENTS):
        return -99
    if result.get("isIllustration") or result.get("nudity"):
        return -99
    width = int(result.get("width") or 0)
    if width < _MIN_WIDTH:
        return -99
    downloads = int(result.get("downloads") or 0)
    if downloads < _MIN_DOWNLOADS:
        return -99  # neredeyse hiç indirilmemiş: _MIN_SCORE zaten elerdi

    score = 0

    # Boyut bonusu
    if width >= 5000:
        score += 2
    elif width >= 4000:
        score += 1

    # Popülerlik
    if downloads >= 100:
        score += 2
    elif downloads >= 30:
        score += 1

    # Query kelimeleri başlık/tag'de geçiyor mu
    for word in query_words:
        if len(word) >= 4:
            if word in title:
                score += 2
            elif word in tags:
                score += 1

    # Editorial fotoğraflar genelde daha otantik
    if result.get("iseditorial") or result.get("is_editorial"):
        score += 1

    return score


def search(query: str, count: int = 8, orientation: str = "horizontal") -> List[Dict[str, Any]]:
    """DepositPhotos'ta arama yapar, puanlar ve sıralar.

    Her sonuç: {id, title, score, preview_url, width, downloads}
    Sadece _MIN_SCORE üzerindeki fotoğraflar döner.
    """
    api_key = _api_key()
    # Fazla çek — filtreleme sonrası count kadar kalsın
    fetch_limit = max(count * 4, 20)
    r = _post({
        "dp_command": "search",
        "dp_apikey": api_key,
        "dp_search_query": query,
        "dp_search_limit": fetch_limit,
        "dp_search_offset": 0,
        "dp_search_orientation": orientation,
        "dp_search_nudity": 0,
    })
    if r.get("type") != "success":
        raise RuntimeError(f"DepositPhotos arama hatası: {r.get('error', {}).get('errormsg', r)}")

    results = r.get("result", [])
    if isinstance(results, dict):
        results = list(results.values())

    query_words = query.lower().split()

    # Puanla ve filtrele
    scored = []
    for v in results:
        s = _score(v, query_words)
        if s >= _MIN_SCORE:
            scored.append((s, v))

    # Skora göre sırala
    scored.sort(key=lambda x: x[0], reverse=True)

    return [
        {
            "id": str(v["id"]),
            "title": v.get("title", ""),
            "tags": list(v.get("tags") or []),
            "score": s,
            "width": int(v.get("width") or 0),
            "downloads": int(v.get("downloads") or 0),
            "preview_url": v.get("url_big") or v.get("thumb_huge") or v.get("thumb380") or "",
        }
        for s, v in scored[:count]
    ]


def _load_download_link(state_path: Path) -> Optional[str]:
    """Yarım kalan lisanslı aktarımın geçici bağlantısını oku."""
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    link = payload.get("download_link") if isinstance(payload, dict) else None
    return link if isinstance(link, str) and link.startswith(("http://", "https://")) else None


def _save_download_link(state_path: Path, download_link: str) -> None:
    """Bağlantıyı yalnızca yerel, sahip-korumalı aktarım durumu olarak sakla."""
    temporary = state_path.with_suffix(state_path.suffix + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"download_link": download_link}, handle)
    os.replace(temporary, state_path)
    os.chmod(state_path, 0o600)


def _request_download_link(asset_id: str, session_id: str) -> str:
    api_key = _api_key()
    response = _post({
        "dp_command": "getMedia",
        "dp_apikey": api_key,
        "dp_session_id": session_id,
        "dp_media_id": asset_id,
        "dp_media_option": "xl",
        "dp_media_license": "standard",
    })
    if response.get("type") != "success":
        err = response.get("error", {})
        raise RuntimeError(f"DepositPhotos indirme hatası ({asset_id}): {err.get('errormsg', err)}")
    return response["downloadLink"]


def _response_status(response: Any) -> Optional[int]:
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    try:
        status = response.getcode()
    except (AttributeError, TypeError):
        return None
    return status if isinstance(status, int) else None


def _stream_download(download_link: str, temp_dest: Path) -> None:
    """Dosyayı kaldığı bayttan tamamla; hata halinde kısmi veri korunur."""
    attempts = 2
    for attempt in range(attempts):
        started = time.monotonic()
        resume_at = temp_dest.stat().st_size if temp_dest.exists() else 0
        headers = {"User-Agent": "Mozilla/5.0"}
        if resume_at:
            headers["Range"] = f"bytes={resume_at}-"
        request = urllib.request.Request(download_link, headers=headers)
        try:
            with _urlopen_with_retry(request, timeout=20) as response:
                # HTTP 206 doğrulanırsa mevcut baytların ardına yazılır. Sunucu
                # Range'i yok sayarsa bozuk bir birleştirme üretmemek için baştan yazılır.
                append = resume_at > 0 and _response_status(response) == 206
                with temp_dest.open("ab" if append else "wb") as output:
                    while True:
                        if time.monotonic() - started > _DOWNLOAD_DEADLINE_SECONDS:
                            raise TimeoutError(
                                f"DepositPhotos file transfer exceeded {_DOWNLOAD_DEADLINE_SECONDS}s"
                            )
                        chunk = response.read(_DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        output.write(chunk)
            if temp_dest.stat().st_size == 0:
                raise RuntimeError("DepositPhotos boş dosya döndürdü")
            return
        except urllib.error.HTTPError:
            # Süresi dolmuş bir kaydedilmiş bağlantı üst katmanda tek seferde
            # yenilenir; burada tekrar denemek yalnızca aynı başarısız isteği
            # çoğaltır.
            raise
        except Exception:
            # Kısmi dosya sonraki denemede Range isteğiyle devam eder; silmek
            # hotspot verisini ve olası lisans çağrısını tekrar harcatıyordu.
            if attempt == attempts - 1:
                raise
            time.sleep(_RETRY_DELAYS_SECONDS[attempt])


def download(asset_id: str, session_id: str, dest_dir: Optional[str] = None) -> str:
    """Lisanslı XL dosyayı güvenli biçimde indirir ve yarım aktarımı sürdürür."""
    out_dir = Path(dest_dir) if dest_dir else _DEFAULT_CACHE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"deposit_{asset_id}.jpg"
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)

    # Recover a licensed file left by an interrupted pre-cache run. This keeps
    # retries idempotent and avoids spending another DepositPhotos credit.
    temp_root = Path(tempfile.gettempdir())
    for recovered in temp_root.glob(f"pictova_dep_*/deposit_{asset_id}.jpg"):
        if recovered.is_file() and recovered.stat().st_size > 0:
            shutil.copy2(recovered, dest)
            return str(dest)

    temp_dest = dest.with_suffix(dest.suffix + ".part")
    state_path = temp_dest.with_suffix(temp_dest.suffix + ".json")
    download_link = _load_download_link(state_path)
    reused_link = download_link is not None

    # Geçici bağlantı artık geçersizse yalnızca o durumda yeni lisans bağlantısı
    # istenir. Normal ağ kesintisi hiçbir yeni getMedia çağrısı üretmez.
    for link_attempt in range(2):
        if download_link is None:
            download_link = _request_download_link(asset_id, session_id)
            _save_download_link(state_path, download_link)
        try:
            _stream_download(download_link, temp_dest)
            temp_dest.replace(dest)
            state_path.unlink(missing_ok=True)
            return str(dest)
        except urllib.error.HTTPError as exc:
            if reused_link and exc.code in {401, 403, 404} and link_attempt == 0:
                state_path.unlink(missing_ok=True)
                download_link = None
                reused_link = False
                continue
            raise
        except Exception:
            # _stream_download aynı bağlantıyla iki Range denemesi yapmıştır.
            # Daha fazlası hotspot verisini tüketir; .part ve bağlantı bir
            # sonraki Pictova çalışması için korunur.
            raise

    raise RuntimeError(f"DepositPhotos aktarımı tamamlanamadı ({asset_id})")


def search_and_download(
    query: str,
    count: int = 4,
    dest_dir: Optional[str] = None,
    orientation: str = "horizontal",
) -> List[str]:
    """Arama + indirme birleşik. Yerel dosya path listesi döner."""
    session_id = _login()
    results = search(query, count=count, orientation=orientation)
    if not results:
        raise RuntimeError(f"DepositPhotos'ta sonuç bulunamadı: {query!r}")

    paths = []
    for r in results[:count]:
        try:
            path = download(r["id"], session_id, dest_dir=dest_dir)
            paths.append(path)
        except RuntimeError as e:
            print(f"  ⚠ Atlandı ({r['id']}): {e}")
    return paths


__all__ = ["search", "download", "search_and_download", "_login"]
