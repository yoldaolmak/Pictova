"""Semantic asset search over the visual-memory index.

This lived inside `src/main.py`, the legacy orchestrator, so the canonical
engine had to import from the pipeline it replaced. Search is a capability of
the engine, not of one pipeline; both callers now depend on this module and the
dependency runs in a single direction.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from src.core.database import VisualMemoryComponent, VisualMemoryConfig
from src.utils.config import get_vil_dir, get_visual_memory_db_path


# ── Semantic arama yardımcıları ──────────────────────────────────────────────

def _ascii_normalize(text: str) -> str:
    """Türkçe harfleri ASCII'ye çevir, küçük harf yap — path LIKE araması için."""
    result = str(text or "")
    for src, dst in [
        ("İ","I"),("Ş","S"),("Ç","C"),("Ğ","G"),("Ü","U"),("Ö","O"),
        ("ş","s"),("ç","c"),("ğ","g"),("ü","u"),("ö","o"),("ı","i"),
    ]:
        result = result.replace(src, dst)
    return result.lower()


# İçerik filtresi → SQL WHERE parçası (OR mantığıyla, GCV sonrası otomatik zenginleşir)
CONTENT_FILTER_SQL: dict[str, str] = {
    "insan":    "(activity IN ('walking','sightseeing','portrait','swimming')"
                " OR vision_labels_json LIKE '%person%'"
                " OR vision_labels_json LIKE '%people%'"
                " OR vision_labels_json LIKE '%face%'"
                " OR vision_labels_json LIKE '%crowd%')",
    "portrait": "(activity='portrait' OR vision_labels_json LIKE '%portrait%')",
    "sokak":    "(scene='street'"
                " OR vision_labels_json LIKE '%street%'"
                " OR vision_labels_json LIKE '%alley%'"
                " OR vision_labels_json LIKE '%road%')",
    "mimari":   "(scene='landmark'"
                " OR vision_labels_json LIKE '%building%'"
                " OR vision_labels_json LIKE '%architecture%'"
                " OR vision_labels_json LIKE '%church%'"
                " OR vision_labels_json LIKE '%mosque%')",
    "doga":     "(scene IN ('nature','landscape')"
                " OR vision_labels_json LIKE '%nature%'"
                " OR vision_labels_json LIKE '%forest%'"
                " OR vision_labels_json LIKE '%mountain%')",
    "deniz":    "(scene IN ('sahil','kiyi')"
                " OR vision_labels_json LIKE '%sea%'"
                " OR vision_labels_json LIKE '%ocean%'"
                " OR vision_labels_json LIKE '%beach%'"
                " OR vision_labels_json LIKE '%coast%')",
    "gece":     "(vision_labels_json LIKE '%night%' OR vision_labels_json LIKE '%dark%')",
    "pazar":    "(scene='market'"
                " OR vision_labels_json LIKE '%market%'"
                " OR vision_labels_json LIKE '%bazaar%')",
    "tapinak":  "(scene='landmark'"
                " OR vision_labels_json LIKE '%temple%'"
                " OR vision_labels_json LIKE '%mosque%'"
                " OR vision_labels_json LIKE '%pagoda%')",
    "yiyecek":  "(vision_labels_json LIKE '%food%' OR vision_labels_json LIKE '%dish%')",
    "tekne":    "(vision_labels_json LIKE '%boat%' OR vision_labels_json LIKE '%ship%'"
                " OR vision_labels_json LIKE '%vessel%')",
}

# Takma adlar
_FILTER_ALIASES: dict[str, str] = {
    "insan": "insan", "insanlar": "insan", "kisi": "insan", "kisiler": "insan",
    "people": "insan", "person": "insan", "adam": "insan", "kadin": "insan",
    "portrait": "portrait", "portre": "portrait",
    "sokak": "sokak", "cadde": "sokak", "street": "sokak",
    "mimari": "mimari", "bina": "mimari", "yapi": "mimari", "architecture": "mimari",
    "doga": "doga", "nature": "doga", "orman": "doga", "dag": "doga",
    "deniz": "deniz", "sahil": "deniz", "beach": "deniz", "sea": "deniz",
    "gece": "gece", "night": "gece",
    "pazar": "pazar", "market": "pazar", "bazaar": "pazar", "carsi": "pazar",
    "tapinak": "tapinak", "cami": "tapinak", "mosque": "tapinak", "kilise": "tapinak",
    "yemek": "yiyecek", "food": "yiyecek", "yiyecek": "yiyecek",
    "tekne": "tekne", "boat": "tekne", "gemi": "tekne",
}


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    """Read sqlite3.Row and dict values through one safe interface."""
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        getter = getattr(row, "get", None)
        value = getter(key, default) if getter else default
    return default if value is None else value


def _capture_time(row: Any) -> datetime | None:
    raw = str(_row_value(row, "created_at", "") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _distance_meters(left: Any, right: Any) -> float | None:
    try:
        lat1 = float(_row_value(left, "latitude"))
        lon1 = float(_row_value(left, "longitude"))
        lat2 = float(_row_value(right, "latitude"))
        lon2 = float(_row_value(right, "longitude"))
    except (TypeError, ValueError):
        return None
    mean_lat = math.radians((lat1 + lat2) / 2)
    x = math.radians(lon2 - lon1) * math.cos(mean_lat)
    y = math.radians(lat2 - lat1)
    return 6_371_000 * math.sqrt(x * x + y * y)


def _same_capture_burst(left: Any, right: Any) -> bool:
    """Treat near-simultaneous shots from the same position as one candidate."""
    left_time = _capture_time(left)
    right_time = _capture_time(right)
    if left_time is None or right_time is None:
        return False
    try:
        seconds = abs((left_time - right_time).total_seconds())
    except TypeError:
        return False
    distance = _distance_meters(left, right)
    return seconds <= 120 and distance is not None and distance <= 250


def _perceptual_hash(path: str, hash_size: int = 8) -> int | None:
    """Return a small dHash for inexpensive visual near-duplicate filtering."""
    if not path:
        return None
    try:
        from PIL import Image, ImageOps

        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image).convert("L")
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            pixels = list(image.resize((hash_size + 1, hash_size), resampling).getdata())
    except Exception:
        return None

    value = 0
    width = hash_size + 1
    for row in range(hash_size):
        offset = row * width
        for column in range(hash_size):
            value = (value << 1) | int(pixels[offset + column] > pixels[offset + column + 1])
    return value


def _contains_people(row: Any) -> bool:
    try:
        people = json.loads(str(_row_value(row, "people_json", "[]") or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        people = []
    if isinstance(people, list) and people:
        return True
    try:
        labels = json.loads(str(_row_value(row, "apple_labels_json", "[]") or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        labels = []
    return any(str(label).lower() in {"person", "people", "face", "portrait"} for label in labels)


def _select_diverse_rows(
    rows: list[Any],
    count: int,
    *,
    include_icloud: bool = False,
    allow_people: bool = False,
) -> list[Any]:
    """Keep quality order while suppressing burst and perceptual duplicates."""
    selected: list[Any] = []
    selected_hashes: list[int] = []
    seen_assets: set[str] = set()

    for row in rows:
        source_path = str(_row_value(row, "source_path", "") or "")
        source_id = str(_row_value(row, "source_id", "") or "")
        asset_key = source_path or (f"icloud://{source_id}" if include_icloud and source_id else "")
        if not asset_key or asset_key in seen_assets:
            continue
        if not allow_people and _contains_people(row):
            continue
        if any(_same_capture_burst(row, previous) for previous in selected):
            continue

        image_hash = _perceptual_hash(source_path) if source_path and Path(source_path).exists() else None
        if image_hash is not None and any(bin(image_hash ^ previous).count("1") <= 8 for previous in selected_hashes):
            continue

        selected.append(row)
        seen_assets.add(asset_key)
        if image_hash is not None:
            selected_hashes.append(image_hash)
        if len(selected) >= count:
            break

    return selected


def _expand_trip_candidates(conn: Any, seed_rows: list[Any], count: int, *, include_icloud: bool) -> list[Any]:
    """Expand sparse text matches with nearby assets captured on the same trip days."""
    coordinates = []
    dates = set()
    for row in seed_rows:
        created_at = str(_row_value(row, "created_at", "") or "")
        if len(created_at) >= 10:
            dates.add(created_at[:10])
        try:
            coordinates.append((float(_row_value(row, "latitude")), float(_row_value(row, "longitude"))))
        except (TypeError, ValueError):
            continue

    if not coordinates or not dates:
        return []

    min_lat = min(lat for lat, _ in coordinates) - 0.03
    max_lat = max(lat for lat, _ in coordinates) + 0.03
    min_lon = min(lon for _, lon in coordinates) - 0.04
    max_lon = max(lon for _, lon in coordinates) + 0.04
    trip_dates = sorted(dates)[:7]
    date_placeholders = ",".join("?" for _ in trip_dates)
    local_clause = "" if include_icloud else "AND source_path != ''"
    sql = f"""
        SELECT source_path, filename, quality_score, selection_score,
               activity, scene, location, city, state_province,
               country, title, description, summary, orientation,
               ai_keywords_json, source_id, created_at, latitude, longitude,
               vision_scan_status, people_json, apple_labels_json
        FROM asset_index
        WHERE is_personal = 0
          {local_clause}
          AND latitude BETWEEN ? AND ?
          AND longitude BETWEEN ? AND ?
          AND substr(created_at, 1, 10) IN ({date_placeholders})
        ORDER BY
          (CASE WHEN vision_scan_status = 'done' THEN 1 ELSE 0 END) DESC,
          selection_score DESC, quality_score DESC, created_at ASC
        LIMIT ?
    """
    params = [min_lat, max_lat, min_lon, max_lon, *trip_dates, max(count * 20, 100)]
    try:
        return conn.execute(sql, params).fetchall()
    except Exception:
        return []


def search_semantic_assets(
    location_query: str,
    count: int,
    content_filter: str | None = None,
    post_context: Dict | None = None,
    include_icloud: bool = False,
) -> list[str]:
    """
    Lokasyon sorgusu + içerik filtresiyle HDD'den fotoğraf bul.

    location_query: "madura adası", "alaçatı", "roma trastevere" vb.
    content_filter: "insan", "sokak", "mimari" vb. — None = filtre yok
    Döndürür: mevcut dosya path'lerinin listesi
    """
    import sqlite3

    db_path = get_visual_memory_db_path()
    if not db_path.exists():
        return []

    # Coğrafi alias genişletme
    try:
        from src.pictova.engine.geo_aliases import expand_query
        expanded_terms = expand_query(location_query)
    except Exception:
        expanded_terms = [location_query]

    # Sorguyu normalize et — Türkçe karakterleri koru, FTS unicode61 halleder
    # Tüm expanded terimleri birleştir
    combined_query = " ".join(expanded_terms[:4])  # ilk 4 terim
    query_clean = re.sub(r'[^\w\s]', ' ', combined_query, flags=re.UNICODE).strip()
    tokens = [t for t in re.split(r"\s+", query_clean) if len(t) >= 3]
    if not tokens:
        return []

    filter_keys = {
        _FILTER_ALIASES.get(_ascii_normalize(item.strip()), "")
        for item in str(content_filter or "").split(",")
        if item.strip()
    }
    allow_people = bool(filter_keys & {"insan", "portrait"})

    # FTS5 MATCH sorgusu — her token AND mantığıyla, prefix match için *
    fts_query = " ".join(f'"{t}"*' for t in tokens)

    # İçerik filtresi SQL (Dinamik)
    content_sql_parts = []
    content_sql_params = []
    
    if content_filter:
        for raw_item in str(content_filter).split(','):
            item = raw_item.strip().lower()
            if not item:
                continue
                
            norm_item = _ascii_normalize(item)
            
            if norm_item == "dikey":
                content_sql_parts.append("a.orientation = 'portrait'")
            elif norm_item == "yatay":
                content_sql_parts.append("a.orientation = 'landscape'")
            else:
                canonical_cf = _FILTER_ALIASES.get(norm_item)
                if canonical_cf and canonical_cf in CONTENT_FILTER_SQL:
                    content_sql_parts.append(CONTENT_FILTER_SQL[canonical_cf])
                else:
                    # Serbest metin -> keyword / people / description araması
                    content_sql_parts.append("(a.ai_keywords_json LIKE ? OR a.description LIKE ? OR a.people_json LIKE ?)")
                    like_val = f"%{item}%"
                    content_sql_params.extend([like_val, like_val, like_val])
                    
    content_filter_clause = f"AND ({' AND '.join(content_sql_parts)})" if content_sql_parts else ""

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        # FTS ile eşleşen source_id'leri bul, asset_index ile JOIN et
        sql = f"""
            SELECT a.source_path, a.filename, a.quality_score, a.selection_score,
                   a.activity, a.scene, a.location, a.city, a.state_province,
                   a.country, a.title, a.description, a.summary, a.orientation,
                   a.ai_keywords_json, a.source_id, a.created_at, a.latitude,
                   a.longitude, a.vision_scan_status, a.people_json,
                   a.apple_labels_json
            FROM asset_search s
            JOIN asset_index a ON a.source_id = s.source_id
            WHERE s.document MATCH ?
              AND a.is_personal = 0
              {"" if include_icloud else "AND a.source_path != ''"}
              {content_filter_clause}
            ORDER BY
              (CASE WHEN a.vision_scan_status = 'done' THEN 1 ELSE 0 END) DESC,
              a.selection_score DESC, a.quality_score DESC
            LIMIT ?
        """
        try:
            params = [fts_query] + content_sql_params + [max(count * 4, 30)]
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error:
            # FTS MATCH hatası (özel karakter vb.) → LIKE fallback.
            # Yalnızca sqlite hatası yutulur; programlama hatası yukarı çıkar.
            rows = []

        # FTS sonuç yetersizse LIKE fallback (tek token, city/state_province)
        if len(rows) < count and tokens:
            like_clauses = " OR ".join(
                f"LOWER(COALESCE(city,'')) LIKE ? OR LOWER(COALESCE(state_province,'')) LIKE ?"
                for _ in tokens
            )
            like_params = [f"%{t.lower()}%" for t in tokens for _ in range(2)]
            
            # LIKE fallback için content filter alanlarındaki a. öneklerini kaldır
            fallback_content_clause = content_filter_clause.replace('a.', '') if content_filter_clause else ''
            
            fb_sql = f"""
                SELECT source_path, filename, quality_score, selection_score,
                       activity, scene, location, city, state_province,
                       country, title, description, summary, orientation,
                       ai_keywords_json, source_id, created_at, latitude,
                       longitude, vision_scan_status, people_json,
                       apple_labels_json
                FROM asset_index
                WHERE ({like_clauses}) AND is_personal = 0
                  {fallback_content_clause}
                ORDER BY selection_score DESC, quality_score DESC
                LIMIT ?
            """
            seen = {r["source_path"] for r in rows}
            fb_params = like_params + content_sql_params + [max(count * 4, 30)]
            try:
                fb_rows = conn.execute(fb_sql, fb_params).fetchall()
            except sqlite3.Error:
                # The FTS branch above degrades to this fallback; the fallback
                # itself had no guard, so a schema mismatch took down the whole
                # search instead of returning no candidates.
                fb_rows = []
            rows = list(rows) + [r for r in fb_rows if r["source_path"] not in seen]

        if not content_filter and len(_select_diverse_rows(
            list(rows), count, include_icloud=include_icloud, allow_people=allow_people
        )) < count:
            seen_ids = {str(_row_value(row, "source_id", "")) for row in rows}
            trip_rows = _expand_trip_candidates(conn, list(rows), count, include_icloud=include_icloud)
            rows = list(rows) + [
                row for row in trip_rows
                if str(_row_value(row, "source_id", "")) not in seen_ids
            ]
    finally:
        conn.close()

    # Post context varsa hero scoring ile yeniden sırala
    if post_context and rows:
        rows = sorted(rows, key=lambda r: _hero_score(r, post_context), reverse=True)

    paths: list[str] = []
    for row in _select_diverse_rows(
        list(rows), count, include_icloud=include_icloud, allow_people=allow_people
    ):
        src = str(_row_value(row, "source_path", "") or "")
        if not src:
            if include_icloud:
                # iCloud source_id (UUID) döndür — üst katman indirir
                paths.append(f"icloud://{_row_value(row, 'source_id', '')}")
            continue
        paths.append(src)
    return paths


def load_vil_images_from_index(count: int | None = None, name: str | None = None) -> List[str]:
    return load_vil_images_from_index_for_post(count=count, name=name, post_context={})


def _tokenize_focus(text: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-zA-Z0-9çğıöşüÇĞİÖŞÜ]+", str(text or "").lower())
        if len(token) >= 3
    ]


def _hero_score(row: Dict, post_context: Dict) -> float:
    score = float(_row_value(row, "quality_score", 0) or 0)
    title_tokens = _tokenize_focus(post_context.get("title", ""))
    slug_tokens = _tokenize_focus(str(post_context.get("slug", "")).replace("-", " "))
    focus_tokens = title_tokens[:6] + [token for token in slug_tokens if token not in title_tokens][:4]
    try:
        import json as _json
        ai_kws = " ".join(_json.loads(_row_value(row, "ai_keywords_json", "[]") or "[]"))
    except Exception:
        ai_kws = ""
    haystack = " ".join(
        [
            str(_row_value(row, "filename", "") or "").lower(),
            str(_row_value(row, "title", "") or "").lower(),
            str(_row_value(row, "description", "") or "").lower(),
            str(_row_value(row, "location", "") or "").lower(),
            str(_row_value(row, "activity", "") or "").lower(),
            str(_row_value(row, "summary", "") or "").lower(),
            ai_kws.lower(),
        ]
    )
    overlap = sum(1 for token in focus_tokens if token in haystack)
    score += overlap * 1.5
    # vision scan tamamlanmış fotoğraflara bonus
    if ai_kws:
        score += 0.3
    if _row_value(row, "orientation", "") == "landscape":
        score += 0.75
    if _row_value(row, "scene", "") in {"landmark", "street", "nature"}:
        score += 0.5
    if _row_value(row, "activity", "") in {"unknown", "portrait"}:
        score -= 0.25
    return score


def load_vil_images_from_index_for_post(
    *,
    count: int | None = None,
    name: str | None = None,
    post_context: Dict | None = None,
) -> List[str]:
    vil_dir = get_vil_dir()
    component = VisualMemoryComponent(
        VisualMemoryConfig(
            database_path=get_visual_memory_db_path(),
            external_roots=[vil_dir],
            scan_photos_library=False,
        )
    )
    rows = component.list_assets(
        limit=max(count or 20, 20),
        source_root=vil_dir,
        filename_query=name,
        source_types=("external_hdd",),
    )
    if post_context:
        rows = sorted(rows, key=lambda row: _hero_score(row, post_context), reverse=True)
    paths: list[str] = []
    for row in rows:
        path = Path(row["source_path"])
        if path.exists():
            paths.append(str(path))
    return paths[: count or len(paths)]


