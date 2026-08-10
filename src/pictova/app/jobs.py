"""Job wrappers around the canonical engine."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Dict

from src.pictova.engine.attach import (
    execute_legacy_attach,
    execute_native_attach,
    prepare_attach_request,
    validate_attach_request,
)
from src.utils.config import env_str


def _operation_receipt_dir() -> Path:
    configured = env_str("PICTOVA_OPERATION_RECEIPT_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[3] / "data" / "operation_receipts"


def _write_attach_receipt(result: Dict[str, Any]) -> str:
    """Persist a compact, secret-free terminal receipt for each attach run."""
    receipt_dir = _operation_receipt_dir()
    receipt_dir.mkdir(parents=True, exist_ok=True)
    site = str(result.get("site") or "site").casefold()
    post_id = str(result.get("post_id") or "post")
    safe_site = "".join(char if char.isalnum() or char in "_-" else "-" for char in site).strip("-") or "site"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = receipt_dir / f"attach-{safe_site}-{post_id}-{stamp}.json"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=receipt_dir,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, default=str)
        handle.write("\n")
        temporary = handle.name
    os.replace(temporary, path)
    os.chmod(path, 0o600)
    return str(path)


def _finish_attach_job(result: Dict[str, Any]) -> Dict[str, Any]:
    completed = dict(result)
    try:
        completed["receipt_path"] = _write_attach_receipt(completed)
    except OSError as exc:
        completed.setdefault("warnings", []).append(f"Operation receipt could not be written: {exc}")
    return completed


def run_attach_job(**kwargs: Any) -> Dict[str, Any]:
    request, post_context, constraints = prepare_attach_request(**kwargs)
    site = request.get("site", "auto")
    failed = validate_attach_request(
        site=site,
        request=request,
        post_context=post_context,
        constraints=constraints,
    )
    if failed:
        return _finish_attach_job(failed)
    engine = str(kwargs.get("engine", "legacy")).strip().lower()
    try:
        if engine == "native":
            result = execute_native_attach(
                site=site,
                request=request,
                post_context=post_context,
                constraints=constraints,
            )
        else:
            result = execute_legacy_attach(
                site=site,
                request=request,
                post_context=post_context,
                constraints=constraints,
            )
    except Exception as exc:
        result = {
            "command": "attach",
            "site": site,
            "post_id": request.get("post_id"),
            "status": "failed",
            "warnings": [str(exc)],
        }
    return _finish_attach_job(result)
