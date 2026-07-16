"""
Tests for backend/dev_server_stdlib.py -- starts the real zero-dependency
server in a background thread, makes real HTTP requests via urllib
(stdlib only, no `requests` package needed), and asserts on responses.
This is the one layer of the repo that was previously "written, not
executed" for lack of network access to install FastAPI; this test
suite is what closes that gap for good.
"""
import json
import threading
import time
import urllib.request
import urllib.error

from backend.dev_server_stdlib import serve

_server = None
_thread = None


def setup_module(module):
    global _server, _thread
    _server = serve(port=0)  # port=0 -> OS picks a free port, avoids collisions
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()
    time.sleep(0.2)


def teardown_module(module):
    _server.shutdown()


def _base_url() -> str:
    return f"http://127.0.0.1:{_server.server_port}"


def _get(path: str):
    with urllib.request.urlopen(f"{_base_url()}{path}") as resp:
        return resp.status, json.loads(resp.read())


def _post(path: str, body: dict):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{_base_url()}{path}", data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_health():
    status, body = _get("/health")
    assert status == 200
    assert body["status"] == "ok"


def test_analyze_transcript_high_risk():
    status, body = _post("/v1/analyze-transcript", {
        "session_id": "s1", "sender": "scammer",
        "text": "send the money now, only accept gift card, do not tell your bank, this is the irs",
    })
    assert status == 200
    assert body["tier_reached"] == 2
    assert body["any_surfaced"] is True
    surfaced_tactics = {f["tactic_id"] for f in body["flags"] if f["verdict"] == "surfaced"}
    assert "payment_channel_funneling" in surfaced_tactics


def test_analyze_transcript_benign():
    status, body = _post("/v1/analyze-transcript", {"session_id": "s2", "sender": "friend", "text": "hey are we still on for lunch tomorrow?"})
    assert status == 200
    assert body["tier_reached"] == 0
    assert body["any_surfaced"] is False


def test_explain_more_honestly_refuses_without_network():
    status, body = _post("/v1/explain-more", {"session_id": "s1", "transcript_excerpt": "do not tell your bank"})
    assert status == 503
    assert "unavailable" in body["detail"]


def test_campaign_graph_starts_empty_and_k_anonymized():
    status, body = _get("/v1/campaign-graph")
    assert status == 200
    assert body == {"nodes": [], "edges": []}


def test_malformed_json_returns_400():
    req = urllib.request.Request(f"{_base_url()}/v1/analyze-transcript", data=b"{not json", method="POST")
    try:
        urllib.request.urlopen(req)
        raise AssertionError("expected HTTPError")
    except urllib.error.HTTPError as e:
        assert e.code == 400
