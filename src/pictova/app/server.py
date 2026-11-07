"""Minimal HTTP server for the VIL application surface."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from typing import Any, Callable, Dict, Tuple

from src.pictova.app.api import (
    attach_images,
    gallery_query,
    guard_post,
    health_status,
    plan_attach,
    process_attach,
    review_post,
    search_photos,
    stats_summary,
)
from src.pictova.app.state import job_registry
from src.pictova.config import load_project_env


RouteHandler = Callable[[Dict[str, Any]], Dict[str, Any]]
MAX_BODY_BYTES = 1024 * 1024


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    if status == HTTPStatus.UNAUTHORIZED:
        handler.send_header("WWW-Authenticate", "Bearer")
    handler.end_headers()
    handler.wfile.write(body)


def _load_json_body(handler: BaseHTTPRequestHandler) -> Tuple[Dict[str, Any] | None, str | None]:
    # Require a non-simple browser content type; cross-origin form posts must
    # not be able to trigger /attach, /guard or /jobs/attach.
    content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        return None, "content-type must be application/json"
    if handler.headers.get("Transfer-Encoding"):
        return None, "transfer-encoding is not supported"

    raw_length = handler.headers.get("Content-Length", "0").strip() or "0"
    try:
        length = int(raw_length)
    except ValueError:
        return None, "invalid content-length"
    if length < 0:
        return None, "invalid content-length"
    if length > MAX_BODY_BYTES:
        return None, "request body too large"

    raw = handler.rfile.read(length) if length > 0 else b"{}"
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "invalid json body"
    if not isinstance(payload, dict):
        return None, "json body must be an object"
    return payload, None


def build_handler(*, token: str) -> type[BaseHTTPRequestHandler]:
    if not token or len(token) < 32 or not token.isascii():
        raise ValueError("PICTOVA_HTTP_TOKEN must be at least 32 ASCII characters")
    expected_authorization = ("Bearer " + token).encode("ascii")

    routes: Dict[Tuple[str, str], RouteHandler] = {
        ("GET", "/health"): lambda _payload: health_status(),
        ("GET", "/stats"): lambda _payload: stats_summary(),
        ("POST", "/attach"): attach_images,
        ("POST", "/plan"): plan_attach,
        ("POST", "/process"): process_attach,
        ("POST", "/review"): review_post,
        ("POST", "/guard"): guard_post,
        ("POST", "/search"): search_photos,
        ("POST", "/gallery"): gallery_query,
    }

    class VILRequestHandler(BaseHTTPRequestHandler):
        server_version = "PictovaHTTP/0.1"

        def _authorized(self) -> bool:
            provided = self.headers.get("Authorization", "").encode("utf-8")
            if hmac.compare_digest(provided, expected_authorization):
                return True
            _json_response(
                self,
                HTTPStatus.UNAUTHORIZED,
                {
                    "status": "failed",
                    "warning": "authentication required",
                },
            )
            return False

        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            if not self._authorized():
                return
            if self.path == "/":
                _json_response(
                    self,
                    HTTPStatus.OK,
                    {
                        "service": "pictova",
                        "status": "ok",
                        "routes": [
                            {"method": "GET", "path": "/health"},
                            {"method": "POST", "path": "/attach"},
                            {"method": "POST", "path": "/plan"},
                            {"method": "POST", "path": "/process"},
                            {"method": "POST", "path": "/review"},
                            {"method": "POST", "path": "/guard"},
                            {"method": "GET", "path": "/jobs"},
                            {"method": "GET", "path": "/jobs/{job_id}"},
                            {"method": "POST", "path": "/jobs/attach"},
                        ],
                    },
                )
                return

            if self.path == "/jobs":
                _json_response(
                    self,
                    HTTPStatus.OK,
                    {"status": "ok", "jobs": job_registry.list_jobs()},
                )
                return

            if self.path.startswith("/jobs/"):
                job_id = self.path[len("/jobs/") :].strip()
                try:
                    job = job_registry.get_job(job_id)
                except KeyError:
                    _json_response(self, HTTPStatus.NOT_FOUND, {"status": "failed", "warning": "job not found"})
                    return
                _json_response(self, HTTPStatus.OK, {"status": "ok", "job": job})
                return

            route = routes.get(("GET", self.path))
            if route is None:
                _json_response(self, HTTPStatus.NOT_FOUND, {"status": "failed", "warning": "route not found"})
                return

            result = route({})
            code = HTTPStatus.OK if result.get("status") in {"ok", "success", "local"} else HTTPStatus.BAD_REQUEST
            _json_response(self, code, result)

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                return
            if self.headers.get("Origin"):
                _json_response(
                    self,
                    HTTPStatus.FORBIDDEN,
                    {
                        "status": "failed",
                        "warning": "browser-origin requests are not supported",
                    },
                )
                return
            if self.path == "/jobs/attach":
                payload, error = _load_json_body(self)
                if error:
                    _json_response(
                        self,
                        (
                            HTTPStatus.REQUEST_ENTITY_TOO_LARGE
                            if error == "request body too large"
                            else HTTPStatus.BAD_REQUEST
                        ),
                        {"status": "failed", "warning": error},
                    )
                    return
                job = job_registry.create_job(
                    kind="attach",
                    payload=payload or {},
                    runner=attach_images,
                )
                _json_response(self, HTTPStatus.ACCEPTED, {"status": "accepted", "job": job})
                return

            route = routes.get(("POST", self.path))
            if route is None:
                _json_response(self, HTTPStatus.NOT_FOUND, {"status": "failed", "warning": "route not found"})
                return

            payload, error = _load_json_body(self)
            if error:
                _json_response(
                    self,
                    (
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE
                        if error == "request body too large"
                        else HTTPStatus.BAD_REQUEST
                    ),
                    {"status": "failed", "warning": error},
                )
                return

            try:
                result = route(payload or {})
            except Exception as exc:
                _json_response(
                    self,
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"status": "failed", "warning": str(exc), "path": self.path},
                )
                return

            code = HTTPStatus.OK if result.get("status") in {"ok", "success", "local"} else HTTPStatus.BAD_REQUEST
            _json_response(self, code, result)

    return VILRequestHandler


def serve(*, host: str = "127.0.0.1", port: int = 8040) -> ThreadingHTTPServer:
    # There is no HTTPS termination here; never expose the bearer token or
    # powerful WordPress write endpoints on a network interface.
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Pictova HTTP server is restricted to loopback; use the CLI for remote workflows")
    load_project_env()
    token = os.environ.get("PICTOVA_HTTP_TOKEN", "")
    return ThreadingHTTPServer((host, port), build_handler(token=token))


__all__ = ["build_handler", "serve"]
