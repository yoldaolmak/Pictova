"""Metadata generation — via vision chain + DB cache."""

from __future__ import annotations

import json
import html
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.core.metadata_generator import build_basic_metadata
from src.pictova.engine.vision_chain import analyze_image_vision_chain, has_any_vision_source


# These are editorial judgments, not image facts.  They make media fields
# sound like generic travel-blog copy and are deliberately stripped regardless
# of whether metadata came from Gemini, cache, or a paid fallback.
_EDITORIAL_CLICHE_RE = re.compile(
    r"\b(?:harika|büyüleyici|benzersiz|eşsiz|muhteşem|nefes kesen|"
    r"masalsı|unutulmaz|keyifli|gizemli|büyülü|etkileyici|göz alıcı|"
    r"sıra dışı|saklı cennet)\b",
    flags=re.IGNORECASE,
)
_EDITORIAL_FILLER_RE = re.compile(
    r"\b(?:öne çıkıyor|davet ediyor|ruhunu|seyahat ruhu|keşif|huzur|keyfini|"
    r"keşfetmeye değer|keşfedin|kendine hayran bırakıyor|akıllarda kalıyor)\b[^.?!]*",
    flags=re.IGNORECASE,
)
# Generic Turkish publishing labels — the kind of word an article tail is made
# of. These name a document type, never a place or a particular article.
_PUBLISHING_LABEL_WORDS = {
    "rehber", "rehberi", "ipuçları", "ipuclari", "notları", "notlari",
    "tavsiyeleri", "tavsiyesi", "listesi", "yazısı", "yazisi",
}


def _fold_word(value: str) -> str:
    """Case-fold a Turkish word without leaving a combining dot behind.

    "İpuçları".casefold() keeps a combining dot above, so it never equals the
    plain "ipuçları" it is meant to match.
    """
    return value.replace("İ", "I").replace("ı", "i").casefold().strip(" -:–—")


def _strip_article_title_echo(title: str, post_context: Dict[str, Any]) -> str:
    """Drop the article's own title when it trails a media title.

    A media title should name what is pictured. The words to remove come from
    the post itself plus a short list of document-type labels, so a new article
    never needs a new pattern here.
    """
    post_words = {
        _fold_word(word)
        for word in re.split(r"\s+", str(post_context.get("title") or ""))
        if word.strip()
    }
    removable = (post_words | {_fold_word(w) for w in _PUBLISHING_LABEL_WORDS}) - {""}
    if not removable:
        return title

    words = re.split(r"\s+", title.strip())
    cut = len(words)
    while cut > 0 and _fold_word(words[cut - 1]) in removable:
        cut -= 1
    # Never strip the whole title: an empty result is worse than a redundant one.
    if cut == 0:
        return title
    return " ".join(words[:cut]).strip(" -:–—") or title


def _clean_editorial_text(value: object, *, limit: int) -> str:
    """Keep metadata factual, compact and safe to publish verbatim."""
    text = str(value or "").strip()
    text = _EDITORIAL_CLICHE_RE.sub("", text)
    text = _EDITORIAL_FILLER_RE.sub("", text)
    text = re.sub(r"\b(?:bu )?(?:fotoğrafta|görselde|resimde)\b[:,]?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*([,;:])\s*", r"\1 ", text).strip(" ,;:-")
    if len(text) > limit:
        clipped = text[:limit]
        sentence_end = max(clipped.rfind("."), clipped.rfind("!"), clipped.rfind("?"))
        if sentence_end >= 24:
            text = clipped[: sentence_end + 1].rstrip(" ,;:-")
        else:
            text = clipped.rsplit(" ", 1)[0].rstrip(" ,;:-")
    text = re.sub(r"\b(?:ve|veya|ile|and|or)$", "", text, flags=re.IGNORECASE).rstrip(" ,;:-")
    return text


def _ensure_sentence(value: str) -> str:
    if value and not value.endswith((".", "!", "?")):
        return f"{value}."
    return value


def _heading_subject(value: str) -> str:
    """Remove a list number and editorial suffix from a factual media label."""
    subject = re.sub(r"^\s*\d{1,3}\s*[.\-):]\s*", "", str(value or "")).strip()
    return re.split(r"\s+(?:[-—–:])\s+", subject, maxsplit=1)[0].strip()


def _plain_article_text(value: object) -> str:
    """Extract readable article text without turning markup into caption copy."""
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _remove_article_headings(content: str) -> str:
    """Exclude structural headings from the reader-facing caption pool."""
    content = re.sub(
        r"<!--\s*wp:heading\b.*?-->.*?<!--\s*/wp:heading\s*-->",
        " ",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    content = re.sub(
        r"<h[2-6]\b[^>]*>.*?</h[2-6]>",
        " ",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # Some older drafts use a standalone bold paragraph as a section heading
    # instead of an H tag. It must not merge into the following sentence.
    def remove_bold_heading(match: re.Match) -> str:
        text = _plain_article_text(match.group(1))
        if text and len(text) <= 100 and not re.search(r"[.!?]", text):
            return " "
        return match.group(0)

    return re.sub(
        r"<p\b[^>]*>\s*<(?:strong|b)\b[^>]*>(.*?)</(?:strong|b)>\s*</p>",
        remove_bold_heading,
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )


def _caption_section_text(post_context: Dict[str, Any], heading_text: str) -> str:
    """Return article prose for a heading, excluding existing figure captions."""
    content = str(post_context.get("content_raw") or post_context.get("content") or "")
    if not content:
        return ""

    # Existing Gutenberg captions are precisely the text this repair must not
    # recycle. Keep user paragraphs, but remove every figure caption first.
    content = re.sub(
        r"<figcaption\b[^>]*>.*?</figcaption>",
        " ",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    subject = _plain_article_text(_heading_subject(heading_text)).casefold()
    if subject:
        heading_pattern = re.compile(r"<h([2-6])\b[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
        for match in heading_pattern.finditer(content):
            if _heading_subject(_plain_article_text(match.group(2))).casefold() != subject:
                continue
            following = content[match.end():]
            next_heading = heading_pattern.search(following)
            section = following[:next_heading.start()] if next_heading else following
            return _plain_article_text(_remove_article_headings(section))
    return _plain_article_text(_remove_article_headings(content))


def _strip_leading_heading_prefix(sentence: str) -> str:
    """Recover prose when an older draft stores an H-like bold label in a P."""
    for match in re.finditer(
        r"\b[A-ZÇĞİÖŞÜ][a-zçğıöşü]+\s+[a-zçğıöşü]{2,}\b",
        sentence,
    ):
        if match.start() == 0:
            continue
        prefix = sentence[:match.start()].strip()
        words = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]+", prefix)
        if (
            len(words) >= 3
            and not re.search(r"[.!?]", prefix)
            and sum(word[0].isupper() for word in words) >= len(words) - 1
        ):
            return sentence[match.start():].strip()
    return sentence


def _article_caption_candidates(post_context: Dict[str, Any], heading_text: str) -> list[str]:
    """Choose publishable sentences that already exist in the article.

    A figure caption is reader-facing copy, not an alt-text echo. Returning an
    empty list is intentional when the article has no suitable sentence.
    """
    text = _caption_section_text(post_context, heading_text)
    if not text:
        return []

    visual_description = re.compile(
        r"\b(?:fotoğraf|görsel|resim|image|photo)\b|"
        r"\b(?:duran|oturan|bakan|sallanan|giyen|yürüyen|poz veren)\b.*"
        r"\b(?:kadın|adam|kişi|çocuk)\b",
        flags=re.IGNORECASE,
    )
    discarded = re.compile(
        r"\b(?:bu yazıda|bu rehberde|tıklayın|detaylı bilgi|kaynak:)\b|https?://|www\.",
        flags=re.IGNORECASE,
    )
    scored: list[tuple[int, int, str]] = []
    for index, raw_sentence in enumerate(re.split(r"(?<=[.!?])\s+", text)):
        sentence = _strip_leading_heading_prefix(re.sub(r"\s+", " ", raw_sentence).strip())
        if len(sentence) < 28 or len(sentence) > 160:
            continue
        if discarded.search(sentence) or visual_description.search(sentence):
            continue
        lower = sentence.casefold()
        score = 0
        if 48 <= len(sentence) <= 140:
            score += 2
        if re.search(r"\b(?:ama|fakat|değil|çünkü|aslında|bazen|tam olarak)\b", lower):
            score += 3
        if re.search(r"\b(?:insan|sen|ben|biz)\b", lower):
            score += 1
        scored.append((-score, index, sentence))
    return [sentence for _score, _index, sentence in sorted(scored)]


def build_article_caption_map(
    image_files: List[str],
    *,
    assigned_headings: Dict[str, Dict[str, Any]] | None = None,
    post_context: Dict[str, Any] | None = None,
) -> Dict[str, str]:
    """Map each new image to a distinct, verbatim article sentence when possible."""
    assigned_headings = assigned_headings or {}
    post_context = post_context or {}
    used: set[str] = set()
    captions: Dict[str, str] = {}
    for image_file in image_files:
        heading_text = str(assigned_headings.get(image_file, {}).get("text") or "")
        for candidate in _article_caption_candidates(post_context, heading_text):
            identity = candidate.casefold()
            if identity in used:
                continue
            captions[image_file] = candidate
            used.add(identity)
            break
    return captions


def _visual_evidence(metadata: Dict[str, Any]) -> str:
    """Keep unconditioned visual-model output separate from publishing copy."""
    values: list[str] = []
    for key in ("alt", "title", "caption", "description", "summary", "visible_text", "scene", "activity"):
        value = metadata.get(key)
        if value:
            values.append(str(value))
    keywords = metadata.get("keywords", [])
    if isinstance(keywords, str):
        values.append(keywords)
    elif isinstance(keywords, list):
        values.extend(str(item) for item in keywords if str(item).strip())
    return re.sub(r"\s+", " ", " ".join(values)).strip()


def _apply_heading_contract(metadata: Dict[str, Any], heading_info: Dict[str, Any]) -> Dict[str, Any]:
    """Carry the exact selection entity into the metadata quality gate."""
    if not heading_info:
        return metadata
    metadata["heading"] = heading_info.get("text")
    metadata["heading_level"] = heading_info.get("level")
    required = heading_info.get("required_heading_tokens")
    if isinstance(required, (list, tuple, set)):
        metadata["required_heading_tokens"] = [str(token) for token in required if str(token).strip()]
    return metadata


def apply_editorial_metadata_policy(
    metadata: Dict[str, Any],
    *,
    heading_text: str,
    post_context: Dict[str, Any],
    article_caption: str = "",
) -> Dict[str, Any]:
    """Apply one strict publishing contract to every metadata provider.

    The vision model can describe the image, but it cannot be trusted with the
    site's editorial voice.  This policy prevents a model/prompt change from
    reintroducing long, promotional attachment text.
    """
    result = dict(metadata)
    context = _clean_editorial_text(heading_text or post_context.get("title", ""), limit=60)
    title = _clean_editorial_text(result.get("title", ""), limit=60)
    title = _strip_article_title_echo(title, post_context).strip(" -:–—") or context
    heading_subject = _heading_subject(heading_text)
    # A numbered H3 is the article's explicit visual entity. Its concise
    # subject is more reliable than a model's embellished title and produces
    # stable SEO media titles such as "Antik Tiyatro".
    if re.match(r"^\s*\d{1,3}\s*[.\-):]", heading_text or "") and heading_subject:
        title = _clean_editorial_text(heading_subject, limit=60)
    source_alt = _clean_editorial_text(result.get("alt", ""), limit=125)
    alt = source_alt or title
    # Alt text belongs to screen readers. A visible figure caption must be a
    # real article sentence, never the model's literal description of pixels.
    # With no appropriate article sentence, leave the caption empty rather
    # than publishing filler or a redundant visual inventory.
    caption = re.sub(r"\s+", " ", str(article_caption or "")).strip()
    if len(caption) > 160:
        caption = ""
    description = caption or source_alt

    result["title"] = title
    result["alt"] = alt
    result["caption"] = _ensure_sentence(caption)
    result["description"] = _ensure_sentence(description)
    keywords = result.get("keywords", [])
    if isinstance(keywords, str):
        keywords = [part.strip() for part in keywords.split(",")]
    if isinstance(keywords, list):
        result["keywords"] = [
            cleaned for item in keywords
            if (cleaned := _clean_editorial_text(item, limit=40))
        ][:5]
    return result


def _db_cached_metadata(image_path: str) -> Optional[Dict[str, Any]]:
    """Check if previously scanned metadata exists in the visual memory DB. Returns it if found."""
    try:
        from src.pictova.config import get_visual_memory_db_path
        db_path = str(get_visual_memory_db_path())
        con = sqlite3.connect(db_path)
        row = con.execute("""
            SELECT ai_keywords_json, scene, activity, summary
            FROM asset_index
            WHERE source_path = ? AND vision_scan_status = 'done'
            LIMIT 1
        """, [image_path]).fetchone()
        con.close()
        if not row:
            return None
        kws = json.loads(row[0] or "[]")
        if not kws:
            return None
        return {
            "keywords": kws,
            "scene": row[1] or "",
            "activity": row[2] or "",
            "summary": row[3] or "",
        }
    except Exception:
        return None


def _is_turkish(text: str) -> bool:
    """Quickly estimate whether the text is Turkish."""
    tr_chars = set("çğıöşüÇĞİÖŞÜ")
    tr_words = {"ve", "bir", "bu", "da", "de", "ile", "için", "olan", "gibi", "ise"}
    if any(c in tr_chars for c in text):
        return True
    words = set(text.lower().split())
    return len(words & tr_words) >= 2


def _kemal_voice_caption(summary: str, scene: str, location: str, keywords: list) -> str:
    """Return a short factual caption; never write travel-blog prose."""
    if summary and len(summary) > 20:
        s = _clean_editorial_text(summary, limit=100)
        # Remove AI patterns
        for pat in (
            r"^(Bu (fotoğrafta|görselde|resimde)|Fotoğrafta|Görselde|Resimde)[,\s]*",
            r"^(The (image|photo|picture) (shows|depicts|features|captures))[,\s]*",
            r"^(This (image|photo|picture) (shows|depicts|features|captures))[,\s]*",
        ):
            s = re.sub(pat, "", s, flags=re.IGNORECASE).strip()
        # Patterns can also appear mid-sentence; prefix cleanup alone is not enough.
        s = re.sub(
            r"\b(?:bu\s+)?(?:fotoğrafta|görselde|resimde)\b[:,]?\s*",
            "",
            s,
            flags=re.IGNORECASE,
        )
        s = re.sub(r"\bçekilmiş\b", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s+", " ", s).replace(" ,", ",").strip(" ,")
        if s and s[0].islower():
            s = s[0].upper() + s[1:]
        if s and not s.endswith((".", "!", "?")):
            s += "."
        # Use if Turkish; fall through if English
        if _is_turkish(s):
            return _ensure_sentence(s)

    # If no summary or English: Turkish location-based fallback
    _skip = {"general", "other", "unknown", "various", "misc"}
    scene_tr_map = {
        "coast": "kıyı", "mountain": "dağ", "city": "şehir", "village": "köy",
        "forest": "orman", "lake": "göl", "valley": "vadi", "beach": "plaj",
        "castle": "kale", "ruins": "harabe", "market": "çarşı", "nature": "doğa",
        "landscape": "manzara", "harbor": "liman", "port": "liman",
    }
    # Try to use important keywords in Turkish, skip the rest
    kw_clean = [k for k in keywords[:4]
                if k.lower() not in _skip
                and k.lower() not in (location or "").lower()
                and k.lower() not in (scene or "").lower()]

    scene_tr = scene_tr_map.get(scene.lower(), "") if (scene and scene.lower() not in _skip) else ""
    
    if location and scene_tr:
        caption = f"{location} {scene_tr}"
    elif location:
        if kw_clean:
            caption = f"{location}: {kw_clean[0]}"
        else:
            caption = location
    elif scene_tr:
        caption = scene_tr.capitalize()
    else:
        if kw_clean:
            caption = kw_clean[0]
        else:
            caption = "Seyahat görseli"

    return _ensure_sentence(_clean_editorial_text(caption, limit=100))


def _enrich_from_cache(cached: Dict, post_context: Dict) -> Dict:
    """Build full metadata format from the DB cache."""
    kws = cached.get("keywords", [])
    summary = cached.get("summary", "")
    scene = cached.get("scene", "")
    activity = cached.get("activity", "")
    location = str(post_context.get("title") or "").strip()
    kw_str = ", ".join(kws[:5]) if kws else location

    # Translate English scene terms to Turkish
    _scene_tr: dict[str, str] = {
        "coast": "kıyı", "coastal": "kıyı", "shore": "kıyı",
        "beach": "plaj", "bay": "koy", "harbor": "liman", "harbour": "liman",
        "port": "liman", "sea": "deniz", "ocean": "deniz",
        "island": "ada", "peninsula": "yarımada",
        "mountain": "dağ", "hill": "tepe", "cliff": "uçurum",
        "valley": "vadi", "plateau": "yayla", "cave": "mağara",
        "waterfall": "şelale", "lake": "göl", "river": "nehir",
        "forest": "orman", "nature": "doğa", "landscape": "manzara",
        "village": "köy", "town": "kasaba", "city": "şehir",
        "street": "sokak", "market": "çarşı", "square": "meydan",
        "castle": "kale", "fortress": "kale", "ruins": "harabe",
        "mosque": "cami", "church": "kilise", "temple": "tapınak",
        "bridge": "köprü", "lighthouse": "deniz feneri",
        "garden": "bahçe", "park": "park",
        "food": "yemek", "restaurant": "restoran",
        "sunset": "gün batımı", "sunrise": "gün doğumu", "night": "gece",
    }
    scene_tr = _scene_tr.get(scene.lower(), scene) if scene else ""

    # alt: plain, descriptive for screen readers
    # Use summary directly if Turkish; combine location+scene if English
    if summary and _is_turkish(summary):
        alt = summary
    elif scene_tr and location:
        alt = f"{location} {scene_tr}"
    elif location:
        alt = location
    else:
        alt = kw_str

    # title: SEO, location + scene (Turkish, skip generic scene words)
    _skip_scenes = {"general", "other", "unknown", "various", "misc"}
    meaningful_scene = scene_tr if scene and scene.lower() not in _skip_scenes else ""
    if meaningful_scene and location:
        title = f"{location} — {meaningful_scene.title()}"
    elif location:
        title = location
    elif meaningful_scene:
        title = meaningful_scene.title()
    else:
        # Generate from the first keyword
        title = kws[0].title() if kws else kw_str

    caption = _kemal_voice_caption(summary, scene, location, kws)

    # description: location + content context (prefer Turkish scene)
    activity_or_scene = _scene_tr.get(activity.lower(), activity) if activity else scene_tr
    desc_parts = [p for p in [location, activity_or_scene, kw_str] if p]
    description = ". ".join(dict.fromkeys(desc_parts))

    return {
        "alt": alt[:125],
        "title": title[:60],
        "caption": caption,
        "description": description[:300],
        "keywords": kws,
        "source": "db_cache",
    }


def build_basic_metadata_map(
    image_files: List[str],
    *,
    assigned_headings: Dict[str, Dict[str, Any]] | None = None,
    post_context: Dict[str, Any] | None = None,
) -> Dict[str, Dict[str, Any]]:
    post_context = post_context or {}
    assigned_headings = assigned_headings or {}
    metadata_dict: Dict[str, Dict[str, Any]] = {}
    for image_file in image_files:
        h_info = assigned_headings.get(image_file, {})
        heading_text = str(h_info.get("text", "")).strip() or str(post_context.get("title", "")).strip()
        metadata = build_basic_metadata(
            image_path=image_file,
            location_hint=heading_text,
            post_context=post_context,
        )
        _apply_heading_contract(metadata, h_info)
        metadata_dict[image_file] = metadata
    return metadata_dict


def build_native_metadata_map(
    image_files: List[str],
    *,
    assigned_headings: Dict[str, Dict[str, Any]] | None = None,
    post_context: Dict[str, Any] | None = None,
    mode: str = "auto",
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """Generate metadata via vision chain. Checks DB cache first.

    Priority:
      0. DB cache (vision_scan_status='done' — instant, free)
      1. Gemini Flash (GEMINI_API_KEY)
      2. Codex CLI web login
      3. Claude CLI web login
    NO basic fallback — RuntimeError if none work.
    """
    post_context = post_context or {}
    assigned_headings = assigned_headings or {}
    article_captions = build_article_caption_map(
        image_files,
        assigned_headings=assigned_headings,
        post_context=post_context,
    )
    metadata_dict = build_basic_metadata_map(
        image_files,
        assigned_headings=assigned_headings,
        post_context=post_context,
    )

    normalized_mode = str(mode or "auto").strip().lower()
    if normalized_mode == "basic":
        raise RuntimeError(
            "mode=basic rejected: Pictova does not use basic fallback. "
            "Add GEMINI_API_KEY or open a codex/claude session."
        )

    if normalized_mode not in {"auto", "vision"}:
        raise RuntimeError(f"Unknown metadata mode: {normalized_mode!r}")

    if not has_any_vision_source():
        raise RuntimeError(
            "Hiç vision kaynağı bulunamadı.\n"
            "Seçenekler:\n"
            "  1. GEMINI_API_KEY=... (.env'e ekle — Google AI Studio, ücretsiz)\n"
            "  2. codex login  (terminalde)\n"
            "  3. claude session (zaten açıksa çalışır)\n"
            "  4. LM Studio'da qwen2.5-vl-7b-instruct modelini yükle (lokal, ücretsiz)"
        )

    warnings: List[str] = []
    for image_file in image_files:
        h_info = assigned_headings.get(image_file, {})
        heading_text = str(h_info.get("text", "")).strip() or str(post_context.get("title", "")).strip()

        # 0. DB cache check
        cached = _db_cached_metadata(image_file)
        if cached:
            # Use heading_text as the location_hint
            # _enrich_from_cache uses post_context but pulls location from post_context['title'].
            # We can't pass a custom location to override _enrich_from_cache, so we modify a copy of post_context
            ctx = dict(post_context)
            if heading_text:
                ctx["title"] = heading_text
            enriched = _enrich_from_cache(cached, ctx)
            enriched["visual_evidence"] = _visual_evidence(cached)
            _apply_heading_contract(enriched, h_info)
                
            if "pictova_unsplash" in str(image_file):
                parts = Path(image_file).stem.split("-by-")
                publisher = parts[-1].replace("_", " ") if len(parts) > 1 else "Unknown"
                enriched["caption"] = f"{enriched.get('caption', '').strip()} (Görsel: Unsplash, {publisher})"

            metadata_dict[image_file] = apply_editorial_metadata_policy(
                enriched,
                heading_text=heading_text,
                post_context=post_context,
                article_caption=article_captions.get(image_file, ""),
            )
            warnings.append(f"{Path(image_file).name}: OK (db_cache)")
            continue

        # 1-3. Vision chain
        try:
            analysis = analyze_image_vision_chain(
                image_file,
                # Selection context must never prime visual verification.
                # A model that sees "Tinder" before the pixels can invent it.
                location_hint="",
                post_context={},
            )
            source = analysis.pop("source", "vision_chain")
            # Capture evidence before a heading or editorial policy can write
            # into publishing fields. The quality gate must see only what the
            # vision model actually found in the pixels.
            analysis["visual_evidence"] = _visual_evidence(analysis)
            _apply_heading_contract(analysis, h_info)
                
            metadata_dict[image_file] = apply_editorial_metadata_policy(
                analysis,
                heading_text=heading_text,
                post_context=post_context,
                article_caption=article_captions.get(image_file, ""),
            )
            warnings.append(f"{Path(image_file).name}: OK ({source})")
        except RuntimeError as exc:
            raise RuntimeError(
                f"Image analysis failed: {Path(image_file).name}\n{exc}"
            ) from exc

    return metadata_dict, warnings


__all__ = [
    "build_basic_metadata",
    "build_basic_metadata_map",
    "build_native_metadata_map",
]
