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



def test_job_enqueue_failure_returns_safe_http_error_without_killing_server(monkeypatch):
    failed_enqueue = Mock(side_effect=OSError("disk full /private/secret/jobs"))
    monkeypatch.setattr(http.job_registry, "create_job", failed_enqueue)
    server = http.serve(host="127.0.0.1", port=0, token_override=TEST_TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        address = f"http://{host}:{port}"

        def post_job(*, token=TEST_TOKEN, origin=None, content_type="application/json"):
            headers = {"Authorization": "Bearer " + token, "Content-Type": content_type}
            if origin is not None:
                headers["Origin"] = origin
            request = Request(
                address + "/jobs/attach",
                data=b'{"site":"yoldaolmak","post_id":731}',
                headers=headers,
                method="POST",
            )
            try:
                with urlopen(request, timeout=3) as response:
                    return response.status, json.loads(response.read())
            except HTTPError as error:
                return error.code, json.loads(error.read())

        assert post_job(token="wrong")[0] == 401
        assert post_job(origin="https://attacker.invalid")[0] == 403
        assert post_job(content_type="text/plain")[0] == 400
        failed_enqueue.assert_not_called()

        status, body = post_job()
        assert status == 503
        assert body["status"] == "failed"
        assert body["warning"] == "job could not be queued; no operation started"
        assert "/private/secret" not in json.dumps(body)
        failed_enqueue.assert_called_once()

        # An enqueue error is contained to one request; a later job still
        # reaches a 202 without restarting the local HTTP service.
        failed_enqueue.side_effect = None
        failed_enqueue.return_value = {"job_id": "queued-test", "status": "queued"}
        accepted, result = post_job()
        assert accepted == 202
        assert result["status"] == "accepted"
        assert result["job"]["job_id"] == "queued-test"

        with urlopen(Request(address + "/", headers={"Authorization": "Bearer " + TEST_TOKEN}), timeout=3) as response:
            assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_http_post_body_errors_match_across_studio_and_job_routes(monkeypatch):
    studio_plan = Mock()
    job_enqueue = Mock()
    monkeypatch.setattr(http.studio_plans, "plan", studio_plan)
    monkeypatch.setattr(http.job_registry, "create_job", job_enqueue)
    server = http.serve(host="127.0.0.1", port=0, token_override=TEST_TOKEN)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        address = f"http://{host}:{port}"
        for route in ("/studio/plan", "/jobs/attach", "/attach"):
            request = Request(
                address + route,
                data=b"not-json",
                headers={
                    "Authorization": "Bearer " + TEST_TOKEN,
                    "Content-Type": "application/json",
                    **({"Origin": address} if route == "/studio/plan" else {}),
                },
                method="POST",
            )
            with pytest.raises(HTTPError) as error:
                urlopen(request, timeout=3)
            assert error.value.code == 400
            assert json.loads(error.value.read())["warning"] == "invalid json body"
        studio_plan.assert_not_called()
        job_enqueue.assert_not_called()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
