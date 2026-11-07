"""HTTP boundary tests: protect local photos and WordPress write routes."""
from __future__ import annotations

import io
import json
import threading
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from src.pictova.app import server as http


TEST_TOKEN = "pictova-unit-test-token-with-at-least-32-characters"


def test_server_refuses_non_loopback_and_missing_or_short_tokens(monkeypatch):
    monkeypatch.setenv("PICTOVA_HTTP_TOKEN", TEST_TOKEN)
    for host in ("0.0.0.0", "192.168.1.20", "::"):
        with pytest.raises(ValueError, match="loopback"):
            http.serve(host=host, port=0)

    monkeypatch.delenv("PICTOVA_HTTP_TOKEN")
    with pytest.raises(ValueError, match="PICTOVA_HTTP_TOKEN"):
        http.serve(port=0)

    monkeypatch.setenv("PICTOVA_HTTP_TOKEN", "short")
    with pytest.raises(ValueError, match="PICTOVA_HTTP_TOKEN"):
        http.serve(port=0)


def test_json_input_has_size_encoding_and_content_type_bounds():
    def body(value, *, content_type="application/json", length=None, transfer=None):
        data = value if isinstance(value, bytes) else value.encode("utf-8")
        headers = {"Content-Type": content_type, "Content-Length": str(len(data) if length is None else length)}
        if transfer:
            headers["Transfer-Encoding"] = transfer
        handler = Mock(headers=headers, rfile=io.BytesIO(data))
        return http._load_json_body(handler)

    assert body('{"post_id": 7}') == ({"post_id": 7}, None)
    assert body('{"post_id": 7}', content_type="application/json; charset=utf-8") == ({"post_id": 7}, None)
    assert body('{"post_id": 7}', content_type="text/plain")[1] == "content-type must be application/json"
    assert body('{"post_id": 7}', length=-1)[1] == "invalid content-length"
    assert body(bytes([255]))[1] == "invalid json body"
    assert body('{"post_id": 7}', transfer="chunked")[1] == "transfer-encoding is not supported"
    assert body(b"", length=http.MAX_BODY_BYTES + 1)[1] == "request body too large"


def test_http_requires_token_and_blocks_browser_origin_before_write(monkeypatch):
    monkeypatch.setenv("PICTOVA_HTTP_TOKEN", TEST_TOKEN)
    attach = Mock(return_value={"command": "attach", "status": "success"})
    monkeypatch.setattr(http, "attach_images", attach)

    server = http.serve(host="127.0.0.1", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        url = f"http://{host}:{port}/attach"

        def post(headers):
            request = Request(
                url,
                data=json.dumps({"site": "yoldaolmak", "post_id": 7}).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with urlopen(request, timeout=2) as response:
                    return response.status, json.loads(response.read())
            except HTTPError as exc:
                return exc.code, json.loads(exc.read())

        assert post({"Content-Type": "application/json"})[0] == 401
        assert post({
            "Content-Type": "text/plain",
            "Authorization": "Bearer " + TEST_TOKEN,
        })[0] == 400
        assert post({
            "Content-Type": "application/json",
            "Origin": "https://attacker.example",
            "Authorization": "Bearer " + TEST_TOKEN,
        })[0] == 403
        attach.assert_not_called()

        status, result = post({
            "Content-Type": "application/json",
            "Authorization": "Bearer " + TEST_TOKEN,
        })
        assert status == 200
        assert result["status"] == "success"
        attach.assert_called_once_with({"site": "yoldaolmak", "post_id": 7})

        unauthenticated_get = Request(f"http://{host}:{port}/jobs")
        with pytest.raises(HTTPError) as error:
            urlopen(unauthenticated_get, timeout=2)
        assert error.value.code == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
