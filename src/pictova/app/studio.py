"""Operator-reviewed Studio workflow over the existing native Pictova engine.

Only plans created from a configured WordPress host can produce publishable
candidates. Browser-supplied paths or heading assignments are never accepted.
"""

from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import re
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Dict
from urllib.parse import unquote, urlsplit

from src.pictova.app.api import plan_attach
from src.pictova.app.jobs import _finish_attach_job
from src.pictova.app.state import job_registry
from src.pictova.engine.attach import (
    execute_native_attach,
    prepare_attach_request,
    validate_attach_request,
)
from src.pictova.providers.wordpress import fetch_post_context
from src.services.wordpress import YOWordPressUploader


_PLAN_LIFETIME_SECONDS = 20 * 60
_MAX_OPEN_PLANS = 32
_MAX_LOCAL_IMAGE_BYTES = 80 * 1024 * 1024
_MAX_PREVIEW_PIXELS = 30_000_000
_SITE_SLUG = re.compile(r"[\w-]{2,160}", re.UNICODE)


class StudioError(ValueError):
    """A safe, operator-facing refusal (no server paths or credentials)."""


def _fingerprint(context: Dict[str, Any]) -> str:
    payload = (str(context.get("modified") or "") + "\n" + str(context.get("content_raw") or "")).encode("utf-8")
    return sha256(payload).hexdigest()


def _file_identity(path: str) -> tuple[int, int, int, int, str]:
    file = Path(path)
    if not file.is_file() or file.is_symlink():
        raise StudioError("Aday görsel yerel ve okunabilir bir dosya değil")
    stat = file.stat()
    if not 0 < stat.st_size <= _MAX_LOCAL_IMAGE_BYTES:
        raise StudioError("Aday görsel boyutu güvenli sınırların dışında")
    hash_value = sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hash_value.update(chunk)
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, hash_value.hexdigest()


def _resolve_wordpress_url(url: str) -> tuple[str, int, Dict[str, Any]]:
    """Resolve a public permalink through ONLY a configured WordPress host."""
    if not isinstance(url, str) or not 0 < len(url) <= 2048:
        raise StudioError("Geçerli bir WordPress yazı URL'si girin")
    try:
        value = urlsplit(url.strip())
        host = (value.hostname or "").lower().removeprefix("www.")
        port = value.port
    except ValueError as exc:
        raise StudioError("Geçersiz URL") from exc
    if value.scheme != "https" or not host or value.username or value.password or port not in (None, 443):
        raise StudioError("Yalnızca yapılandırılmış HTTPS WordPress yazıları desteklenir")

    site = None
    for name, config in YOWordPressUploader.SITE_ENDPOINTS.items():
        configured = urlsplit(str(config.get("url") or ""))
        if configured.scheme == "https" and (configured.hostname or "").lower().removeprefix("www.") == host:
            site = name
            break
    if not site:
        raise StudioError("URL yapılandırılmış WordPress sitelerinden birine ait değil")

    path = unquote(value.path)
    if "//" in path or path.endswith("/wp-admin") or "/wp-json/" in path:
        raise StudioError("Yazı yolu geçersiz")
    part = path.rstrip("/").rsplit("/", 1)[-1]
    slug = part[:-5] if part.lower().endswith(".html") else part
    if not _SITE_SLUG.fullmatch(slug) or slug in {".", ".."}:
        raise StudioError("Yazının URL kimliği çözümlenemedi")

    uploader = YOWordPressUploader(site=site)
    endpoint = uploader.base_url.rstrip("/") + "/wp-json/wp/v2/posts"
    try:
        response = uploader.session.get(
            endpoint,
            params={"slug": slug, "context": "edit", "per_page": 3},
            timeout=20,
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise StudioError("WordPress yazı kimliği okunamadı")
        rows = response.json()
    except StudioError:
        raise
    except Exception as exc:
        raise StudioError("WordPress bağlantısı kurulamadı") from exc
    if not isinstance(rows, list):
        raise StudioError("WordPress beklenmeyen bir yanıt verdi")
    matches = [row for row in rows if isinstance(row, dict) and row.get("slug") == slug]
    if len(matches) != 1:
        raise StudioError("URL tek bir WordPress yazısıyla eşleşmedi")
    try:
        post_id = int(matches[0]["id"])
    except (ValueError, KeyError, TypeError) as exc:
        raise StudioError("WordPress yazı kimliği geçersiz") from exc
    if post_id < 1:
        raise StudioError("WordPress yazı kimliği geçersiz")
    context = fetch_post_context(post_id, site=site)
    if not context or str(context.get("slug") or "") != slug:
        raise StudioError("Yazı içeriği okunamadı veya URL ile eşleşmedi")
    return site, post_id, context


def _deposit_asset(preview: str) -> tuple[str, str] | None:
    """Return the exact licensed ID from the trusted in-process discovery."""
    from src.pictova.engine.selector import _DEPOSIT_DISCOVERY_CACHE

    for results in _DEPOSIT_DISCOVERY_CACHE.values():
        for item in results:
            if item.get("preview_url") != preview:
                continue
            asset_id = str(item.get("id", ""))
            if asset_id.isascii() and asset_id.isdecimal() and 0 < len(asset_id) <= 20:
                return asset_id, str(item.get("title") or "DepositPhotos")
    return None


class StudioPlans:
    """Bounded, expiring in-memory editorial approval sessions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._plans: dict[str, dict[str, Any]] = {}

    def _prune(self) -> None:
        now = time.monotonic()
        for key, plan in list(self._plans.items()):
            if plan.get("status") != "submitting" and (now > plan["expires"] or plan["used"]):
                self._plans.pop(key, None)

    def plan(self, url: str, count: int = 4) -> Dict[str, Any]:
        if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 8:
            raise StudioError("Görsel sayısı 1 ile 8 arasında olmalı")
        site, post_id, context = _resolve_wordpress_url(url)
        result = plan_attach({"site": site, "post_id": post_id, "source": "auto", "count": count, "engine": "native"})
        if result.get("status") != "success":
            raise StudioError("Görsel planı oluşturulamadı")
        selection = result.get("selection") or {}
        assignments = selection.get("heading_assignments") or {}
        valid_headings = {
            (str(h.get("text") or "").strip(), int(h.get("level") or 0))
            for h in context.get("available_headings") or []
        }
        plan_id = secrets.token_urlsafe(18)
        candidates: dict[str, dict[str, Any]] = {}
        visible: list[dict[str, Any]] = []
        for file in selection.get("files") or []:
            if not isinstance(file, str) or not file:
                continue
            heading = assignments.get(file)
            if not isinstance(heading, dict):
                continue
            heading_key = (str(heading.get("text") or "").strip(), int(heading.get("level") or 0))
            if not heading_key[0] or heading_key not in valid_headings:
                continue

            asset_id = secrets.token_urlsafe(12)
            entry: dict[str, Any] = {"path": file, "heading": dict(heading)}
            reason = ""
            preview_url = ""
            kind = ""
            title = ""
            if file.startswith("https://"):
                deposit = _deposit_asset(file)
                if deposit:
                    entry["deposit_id"], title = deposit
                    kind = "deposit"
                    preview_url = file
                else:
                    reason = "Sağlayıcı kimliği doğrulanamadı"
            elif file.startswith("icloud://"):
                reason = "iCloud görselinin önizlemesi için CLI kullanın"
                kind = "icloud"
            else:
                kind = "local"
                title = Path(file).name
                try:
                    entry["identity"] = _file_identity(file)
                    preview_url = f"/studio/preview?plan={plan_id}&candidate={asset_id}"
                except (OSError, StudioError):
                    reason = "Yerel görsel okunamadı"

            entry["enabled"] = not bool(reason) and bool(preview_url)
            candidates[asset_id] = entry
            visible.append(
                {
                    "id": asset_id,
                    "heading": heading_key[0],
                    "level": heading_key[1],
                    "source": kind,
                    "title": title or "Görsel",
                    "preview_url": preview_url if kind == "deposit" else "",
                    "local_preview": kind == "local" and entry["enabled"],
                    "available": entry["enabled"],
                    "reason": reason,
                    "paid": kind == "deposit",
                }
            )

        with self._lock:
            self._prune()
            if len(self._plans) >= _MAX_OPEN_PLANS:
                oldest = next(iter(self._plans))
                self._plans.pop(oldest)
            self._plans[plan_id] = {
                "expires": time.monotonic() + _PLAN_LIFETIME_SECONDS,
                "used": False,
                "status": "available",
                "site": site,
                "post_id": post_id,
                "digest": _fingerprint(context),
                "candidates": candidates,
            }
        return {
            "status": "success",
            "plan_id": plan_id,
            "expires_in_seconds": _PLAN_LIFETIME_SECONDS,
            "post": {"title": context.get("title", ""), "site": site, "post_id": post_id, "slug": context.get("slug")},
            "headings": context.get("available_headings") or [],
            "candidates": visible,
            "warnings": list(result.get("warnings") or []),
        }

    def preview(self, plan_id: str, candidate_id: str) -> bytes:
        with self._lock:
            self._prune()
            plan = self._plans.get(plan_id)
            entry = (plan or {}).get("candidates", {}).get(candidate_id)
            if not entry or not entry.get("enabled") or "identity" not in entry:
                raise StudioError("Önizleme kullanılamıyor")
            path, identity = entry["path"], entry["identity"]
        if _file_identity(path) != identity:
            raise StudioError("Görsel değişti; yeni plan oluşturun")

        from PIL import Image, ImageOps

        try:
            with Image.open(path) as image:
                if image.width * image.height > _MAX_PREVIEW_PIXELS:
                    raise StudioError("Önizleme görseli çok büyük")
                image = ImageOps.exif_transpose(image)
                image.thumbnail((680, 420))
                output = BytesIO()
                image.convert("RGB").save(output, format="JPEG", quality=76)
                return output.getvalue()
        except (OSError, ValueError) as exc:
            raise StudioError("Görsel önizlemesi oluşturulamadı") from exc

    def approve(self, plan_id: str, accepted: list[str], *, confirm_paid: bool = False) -> Dict[str, Any]:
        if not isinstance(accepted, list) or not accepted or any(not isinstance(x, str) for x in accepted):
            raise StudioError("Yayımlanacak en az bir görsel seçilmeli")
        if len(accepted) != len(set(accepted)):
            raise StudioError("Tekrarlanan aday kimlikleri kabul edilmez")
        with self._lock:
            self._prune()
            plan = self._plans.get(plan_id)
            if not plan:
                raise StudioError("Plan süresi doldu veya kullanıldı")
            if plan.get("status") != "available":
                raise StudioError("Plan zaten uygulamaya alınıyor")
            if any(key not in plan["candidates"] or not plan["candidates"][key]["enabled"] for key in accepted):
                raise StudioError("Onay listesi plandaki kullanılabilir görsellerle eşleşmiyor")
            chosen = [dict(plan["candidates"][key]) for key in accepted]
            if any("deposit_id" in item for item in chosen) and confirm_paid is not True:
                raise StudioError("Lisanslı stok indirmesi için ayrıca onay gerekli")
            # Reserve atomically so concurrent approval requests cannot
            # enqueue two paid publishing jobs for the same plan.
            plan["status"] = "submitting"
            work = {
                "site": plan["site"],
                "post_id": plan["post_id"],
                "digest": plan["digest"],
                "chosen": chosen,
            }

        try:
            job = job_registry.create_job(
                kind="studio_attach",
                payload={
                    "site": work["site"],
                    "post_id": work["post_id"],
                    "selected_count": len(chosen),
                },
                runner=lambda _payload: self._execute(work),
            )
        except Exception as exc:
            # JobRegistry guarantees that any create_job error happens
            # before the runner starts. Return this plan to reviewable.
            with self._lock:
                if self._plans.get(plan_id) is plan:
                    plan["status"] = "available"
            raise StudioError("İş kuyruğa alınamadı; plan kullanılmadı") from exc

        with self._lock:
            plan["used"] = True
            plan["status"] = "consumed"
        return {"status": "accepted", "job_id": job["job_id"], "selected_count": len(chosen)}

    @staticmethod
    def _execute(work: Dict[str, Any]) -> Dict[str, Any]:
        site, post_id = work["site"], work["post_id"]
        try:
            request, context, constraints = prepare_attach_request(
                site=site,
                post_id=post_id,
                source="auto",
                count=len(work["chosen"]),
                engine="native",
            )
            failure = validate_attach_request(site=site, request=request, post_context=context, constraints=constraints)
            if failure:
                return failure

            def chosen_selection() -> Dict[str, Any]:
                files = []
                assignments = {}
                session_id = None
                for asset in work["chosen"]:
                    if "identity" in asset:
                        if _file_identity(asset["path"]) != asset["identity"]:
                            raise StudioError("Seçilen yerel görsel değişti; yeni plan gerekli")
                        path = asset["path"]
                    elif "deposit_id" in asset:
                        from src.pictova.providers import deposit

                        if session_id is None:
                            session_id = deposit._login()
                        path = deposit.download(asset["deposit_id"], session_id)
                    else:
                        raise StudioError("Doğrulanmamış kaynak yayımlanamaz")
                    if path in assignments:
                        raise StudioError("Bir görsel iki kez yerleştirilemez")
                    files.append(path)
                    assignments[path] = dict(asset["heading"])
                return {"source": "studio", "files": files, "heading_assignments": assignments, "warnings": []}

            result = execute_native_attach(
                site=site,
                request=request,
                post_context=context,
                constraints=constraints,
                selection_loader=chosen_selection,
                expected_post_digest=work["digest"],
            )
            return _finish_attach_job(result)
        except Exception as exc:
            return {
                "command": "attach",
                "status": "failed",
                "site": site,
                "post_id": post_id,
                "warnings": [f"Studio execution rejected: {type(exc).__name__}"],
            }


studio_plans = StudioPlans()


__all__ = ["StudioError", "StudioPlans", "studio_plans"]
