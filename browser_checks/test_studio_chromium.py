"""Real Chromium UI checks at desktop, tablet and phone widths.

The actual packaged Studio HTML/CSS/JavaScript executes in Chromium. Only API
and image responses are synthetic; this is not live WordPress validation.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import threading

from PIL import Image
from playwright.sync_api import sync_playwright
import pytest


STATIC = Path(__file__).resolve().parents[1] / "src/pictova/app/static"
SCREENSHOTS = Path("browser-artifacts")
TOKEN = "studio-chromium-test-token-1234567890123"
MIME = {"studio.html": "text/html; charset=utf-8", "studio.js": "text/javascript", "studio.css": "text/css"}


def _jpg():
    image = Image.new("RGB", (240, 160), (65, 109, 142))
    output = BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


PREVIEW = _jpg()


class StudioHandler(BaseHTTPRequestHandler):
    approvals = []

    def log_message(self, *_args):
        return

    def _response(self, code, body, mime="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, content):
        self._response(status, json.dumps(content, ensure_ascii=False).encode())

    def do_GET(self):
        routes = {"/studio": "studio.html", "/studio/app.js": "studio.js", "/studio/style.css": "studio.css"}
        path = routes.get(self.path)
        if path:
            return self._response(200, (STATIC / path).read_bytes(), MIME[path])
        if self.path.startswith("/studio/preview?"):
            if self.headers.get("Authorization") != "Bearer " + TOKEN:
                return self._json(401, {"status": "failed"})
            return self._response(200, PREVIEW, "image/jpeg")
        if self.path == "/jobs/job-1":
            return self._json(200, {
                "status": "success", "job": {
                    "status": "success",
                    "result": {"status": "success", "uploaded_media_ids": [345], "inserted_blocks": 1}
                }
            })
        return self._json(404, {"status": "failed"})

    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            return self._json(401, {"status": "failed"})
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        if self.path == "/studio/plan":
            if body.get("count") != 4:
                return self._json(400, {"status": "failed"})
            return self._json(200, {
                "status": "success", "plan_id": "plan-1", "warnings": [],
                "post": {"site": "yoldaolmak", "post_id": 265713, "title": "Kapadokya Gezilecek Yerler"},
                "headings": [
                    {"text": "Uçhisar Kalesi", "level": 2},
                    {"text": "Avanos Çömlekçiliği", "level": 2},
                    {"text": "Göreme Açık Hava Müzesi", "level": 2},
                ],
                "candidates": [
                    {"id": "local-1", "title": "Uçhisar Castle photo",
                     "heading": "Uçhisar Kalesi", "level": 2, "source": "local",
                     "paid": False, "available": True, "local_preview": True, "preview_url": ""},
                    {"id": "stock-2", "title": "Avanos pottery workshop",
                     "heading": "Avanos Çömlekçiliği", "level": 2, "source": "deposit",
                     "paid": True, "available": True, "local_preview": False,
                     "preview_url": "https://preview.example.test/stock-photo.jpg"},
                ],
            })
        if self.path == "/studio/apply":
            StudioHandler.approvals.append(body)
            return self._json(202, {"status": "accepted", "job_id": "job-1"})
        return self._json(404, {"status": "failed"})


@pytest.fixture(scope="module")
def studio_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), StudioHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize("width,height", [(320, 760), (390, 844), (768, 1024), (1440, 900)])
def test_studio_responsive_review_and_approved_publish(studio_server, width, height):
    SCREENSHOTS.mkdir(exist_ok=True)
    StudioHandler.approvals.clear()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(
            "https://preview.example.test/**",
            lambda route: route.fulfill(status=200, content_type="image/jpeg", body=PREVIEW),
        )
        try:
            page.goto(studio_server + "/studio#token=" + TOKEN, wait_until="networkidle")
            assert "#token" not in page.url
            assert page.locator("#auth-panel").is_hidden()
            assert page.locator("#empty-state").is_visible()
            page.locator("#post-url").fill("https://yoldaolmak.com/kapadokya-gezilecek-yerler.html")
            page.locator("#plan-button").click()
            page.locator(".candidate").first.wait_for()
            assert page.locator(".candidate").count() == 2
            assert page.locator("#unmatched").is_visible()
            assert "1 bölüm" in page.locator("#unmatched").inner_text()
            assert page.locator(".candidate-preview img").count() == 2
            page.wait_for_function(
                "() => [...document.querySelectorAll('.candidate-preview img')].every(img => img.complete && img.naturalWidth > 0)"
            )

            layout = page.evaluate("""() => ({
              width: innerWidth,
              documentWidth: document.documentElement.scrollWidth,
              contentWidth: document.body.scrollWidth,
              planButtonWidth: document.querySelector('#plan-button').getBoundingClientRect().width,
              articleWidth: document.querySelector('#candidate-grid').getBoundingClientRect().width
            })""")
            assert layout["documentWidth"] <= width + 1, layout
            assert layout["contentWidth"] <= width + 1, layout
            assert layout["planButtonWidth"] >= 150, layout
            assert layout["articleWidth"] >= 230, layout

            page.screenshot(path=str(SCREENSHOTS / f"studio-{width}-review.png"), full_page=True)
            page.locator(".candidate input[type=checkbox]").nth(1).uncheck()
            assert page.locator("#paid-line").is_hidden()
            page.locator("#confirm").check()
            assert page.locator("#apply-button").is_enabled()
            page.locator("#apply-button").click()
            page.locator("#plan-state").get_by_text("Yayımlandı").wait_for()
            assert StudioHandler.approvals == [{
                "plan_id": "plan-1", "accepted_ids": ["local-1"], "confirm_paid": False
            }]
            page.screenshot(path=str(SCREENSHOTS / f"studio-{width}-done.png"), full_page=True)
            assert not errors, errors
        finally:
            browser.close()


def test_studio_paid_candidate_requires_separate_consent(studio_server):
    StudioHandler.approvals.clear()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        page.route(
            "https://preview.example.test/**",
            lambda route: route.fulfill(status=200, content_type="image/jpeg", body=PREVIEW),
        )
        try:
            page.goto(studio_server + "/studio#token=" + TOKEN)
            page.locator("#post-url").fill("https://yoldaolmak.com/kapadokya-gezilecek-yerler.html")
            page.locator("#plan-button").click()
            page.locator(".candidate").first.wait_for()
            page.locator("#confirm").check()
            assert page.locator("#paid-line").is_visible()
            assert page.locator("#apply-button").is_disabled()
            page.locator("#confirm-paid").check()
            assert page.locator("#apply-button").is_enabled()
            page.locator("#apply-button").click()
            page.locator("#plan-state").get_by_text("Yayımlandı").wait_for()
            assert StudioHandler.approvals == [{
                "plan_id": "plan-1",
                "accepted_ids": ["local-1", "stock-2"],
                "confirm_paid": True,
            }]
        finally:
            browser.close()
