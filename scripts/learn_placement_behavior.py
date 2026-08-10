#!/usr/bin/env python3
"""Learn image-placement behaviour from already published posts.

Pictova's placement rules were written by hand. The site already contains the
answer: hundreds of posts where a human decided which heading deserves an
image, how many, and when a pair becomes a gallery. This script reads that
evidence instead of guessing at it.

It only reads. Nothing is published, edited, or downloaded.

    python3 scripts/learn_placement_behavior.py --count 300 --out data/placement_behavior.json
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterator, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.post_media_guard import manifest_path  # noqa: E402
from src.services.wordpress import YOWordPressUploader  # noqa: E402


# A block-level scan: headings and media in document order. Galleries are
# matched before images so a nested wp:image is not counted twice.
_BLOCK_RE = re.compile(
    r"(?P<gallery><!--\s*wp:gallery\b.*?<!--\s*/wp:gallery\s*-->)"
    r"|(?P<image><!--\s*wp:image\b.*?<!--\s*/wp:image\s*-->)"
    r"|(?P<heading><!--\s*wp:heading\b.*?<h(?P<level>[2-6])\b[^>]*>(?P<text>.*?)</h(?P=level)>.*?<!--\s*/wp:heading\s*-->)",
    flags=re.IGNORECASE | re.DOTALL,
)
_NUMBERED_RE = re.compile(r"^\s*\d{1,3}\s*[.\-):]")
_GUIDE_RE = re.compile(
    r"gezilecek\s+yer|görülecek\s+yer|görülmesi\s+gereken|"
    r"nerede|nasıl\s+gidilir|gezi\s+rehberi|rehberi?$|rotas[ıi]",
    flags=re.IGNORECASE,
)


def _plain(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value or "")).strip()


def fetch_posts(uploader: YOWordPressUploader, count: int) -> Iterator[Dict[str, Any]]:
    """Yield published posts newest-first, with raw content."""
    fetched = 0
    page = 1
    while fetched < count:
        response = uploader.session.get(
            f"{uploader.base_url}/wp-json/wp/v2/posts",
            params={
                "per_page": min(100, count - fetched),
                "page": page,
                "status": "publish",
                "context": "edit",
                "orderby": "date",
                "order": "desc",
            },
            timeout=60,
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            return
        for post in batch:
            yield post
            fetched += 1
        page += 1


def analyse_post(post: Dict[str, Any], site: str) -> Dict[str, Any]:
    """Describe one post's heading/image layout as observed evidence."""
    content = (post.get("content") or {}).get("raw") or ""
    title = _plain((post.get("title") or {}).get("raw") or (post.get("title") or {}).get("rendered") or "")

    headings: List[Dict[str, Any]] = []
    # Media that appears before any heading belongs to the intro.
    current = {"text": "", "level": 0, "numbered": False, "media": [], "position": -1}
    sequence: List[Dict[str, Any]] = [current]

    for match in _BLOCK_RE.finditer(content):
        if match.group("heading"):
            text = _plain(match.group("text"))
            current = {
                "text": text,
                "level": int(match.group("level")),
                "numbered": bool(_NUMBERED_RE.match(text)),
                "media": [],
                "position": len(headings),
            }
            headings.append(current)
            sequence.append(current)
            continue

        block = match.group("gallery") or match.group("image") or ""
        # One image repeats its id in the block comment, the <figure> class and
        # the <img> class. Counting occurrences turned a single photo into a
        # phantom "3-image block"; only distinct ids are real images.
        image_count = len(set(re.findall(r"wp-image-(\d+)", block))) or (1 if match.group("image") else 0)
        current["media"].append({
            "kind": "gallery" if match.group("gallery") else "image",
            "images": image_count,
        })

    total_images = sum(item["images"] for section in sequence for item in section["media"])
    manifest_exists = manifest_path(site, int(post.get("id") or 0)).exists()

    return {
        "id": post.get("id"),
        "slug": post.get("slug"),
        "title": title,
        "is_guide": bool(_GUIDE_RE.search(title)),
        "pictova_managed": manifest_exists,
        "heading_count": len(headings),
        "numbered_heading_count": sum(1 for h in headings if h["numbered"]),
        "total_images": total_images,
        "intro_images": sum(item["images"] for item in sequence[0]["media"]),
        "sections": [
            {
                "text": h["text"],
                "level": h["level"],
                "numbered": h["numbered"],
                "position": h["position"],
                "media": h["media"],
                "images": sum(item["images"] for item in h["media"]),
            }
            for h in headings
        ],
    }


def summarise(posts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Turn per-post observations into the rules Pictova should follow."""
    guides = [p for p in posts if p["is_guide"] and p["heading_count"] > 0]
    with_images = [p for p in guides if p["total_images"] > 0]

    section_rows = [s for p in with_images for s in p["sections"]]
    filled = [s for s in section_rows if s["images"] > 0]

    # How often does a heading of each kind actually receive an image?
    by_kind: Dict[str, Counter] = defaultdict(Counter)
    for section in section_rows:
        kind = f"h{section['level']}{'-numbered' if section['numbered'] else ''}"
        by_kind[kind]["total"] += 1
        if section["images"] > 0:
            by_kind[kind]["filled"] += 1

    block_shapes = Counter()
    for section in filled:
        for item in section["media"]:
            block_shapes[f"{item['kind']}-{item['images']}"] += 1

    images_per_filled = [s["images"] for s in filled]
    coverage = [
        len([s for s in p["sections"] if s["images"] > 0]) / max(p["heading_count"], 1)
        for p in with_images
    ]
    # Where in the article does the first image land?
    first_positions = [
        min((s["position"] for s in p["sections"] if s["images"] > 0), default=-1)
        for p in with_images
    ]

    return {
        "sampled_posts": len(posts),
        "guide_posts": len(guides),
        "guide_posts_with_images": len(with_images),
        "pictova_managed": sum(1 for p in guides if p["pictova_managed"]),
        "images_per_post": {
            "median": statistics.median([p["total_images"] for p in with_images]) if with_images else 0,
            "mean": round(statistics.fmean([p["total_images"] for p in with_images]), 2) if with_images else 0,
            "distribution": dict(Counter(p["total_images"] for p in with_images).most_common()),
        },
        "heading_fill_rate": {
            kind: {
                "total": counts["total"],
                "filled": counts["filled"],
                "rate": round(counts["filled"] / counts["total"], 3) if counts["total"] else 0,
            }
            for kind, counts in sorted(by_kind.items())
        },
        "section_coverage": {
            "median_share_of_headings_with_image": round(statistics.median(coverage), 3) if coverage else 0,
        },
        "images_per_filled_section": dict(Counter(images_per_filled).most_common()),
        "block_shapes": dict(block_shapes.most_common()),
        "first_image_heading_index": dict(Counter(first_positions).most_common(10)),
        "intro_image_posts": sum(1 for p in with_images if p["intro_images"] > 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="yoldaolmak")
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--out", default="data/placement_behavior.json")
    args = parser.parse_args()

    uploader = YOWordPressUploader(site=args.site)
    posts = []
    for post in fetch_posts(uploader, args.count):
        posts.append(analyse_post(post, args.site))
        if len(posts) % 50 == 0:
            print(f"  … {len(posts)} post okundu", file=sys.stderr)

    summary = summarise(posts)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"summary": summary, "posts": posts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nAyrıntı: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
