"""
Zero-dependency development server: the SAME three routes as
backend/api/routes.py (FastAPI), reimplemented against only the Python
standard library (http.server + json), so the backend layer can be
genuinely started and HTTP-tested in environments with no network access
to pip install fastapi/pydantic/uvicorn -- such as the sandbox this repo
was built in.

This is NOT a FastAPI replacement or a claim that FastAPI itself is
running. It is an honest, executable stand-in that exercises the exact
same underlying logic (detection/, grounding/, threat-intel/) over real
HTTP, so "the backend layer" stops being purely "written, not executed"
wherever network access to install the real framework isn't available.
backend/main.py + backend/api/routes.py remain the spec-correct,
production FastAPI implementation to deploy for real -- this file exists
purely to close the verification gap in constrained environments.

Run: python3 backend/dev_server_stdlib.py
Then: curl -X POST http://localhost:8787/v1/analyze-transcript \
        -d '{"session_id":"s1","sender":"scammer","text":"send the money now, only accept gift card, do not tell your bank, this is the irs"}'
"""
from __future__ import annotations
import json
import sys
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "threat-intel"))
sys.path.insert(0, os.path.dirname(__file__))  # so `incident_ingest` resolves whether run as script or imported as a package

from detection.conversation.model_cascade import route as cascade_route  # noqa: E402
from grounding.nli_entailment_gate import gate_candidates  # noqa: E402
from grounding.confidence_gate import apply as apply_confidence_gate, any_surfaced  # noqa: E402
from campaign_graph import CampaignGraph  # noqa: E402
from incident_ingest import record_detection, seed_demo_campaign  # noqa: E402

_campaign_graph = CampaignGraph()  # same process-lifetime graph as routes.py's reference wiring
# Dev/demo only: no-op unless TRUSTTRACE_SEED_DEMO_CAMPAIGN is set.
seed_demo_campaign(_campaign_graph)


def _analyze_transcript(body: dict) -> dict:
    text = body.get("text", "")
    cascade_result = cascade_route(text)
    survivors, entailment_results = gate_candidates(cascade_result.candidates)
    gated = apply_confidence_gate(entailment_results)
    # Feed the CampaignGraph the dashboard reads from -- only on a surfaced
    # flag, only anonymized patterns, floor still enforced downstream.
    if any_surfaced(gated):
        record_detection(_campaign_graph, text)
    return {
        "tier_reached": cascade_result.tier_reached,
        "flags": [
            {"tactic_id": g.tactic_id, "verdict": g.verdict.value, "confidence": g.confidence, "explanation": g.explanation}
            for g in gated
        ],
        "any_surfaced": any_surfaced(gated),
    }


def _explain_more(body: dict) -> tuple[int, dict]:
    # Real backend/llm_client.py refuses without network/API key -- same
    # honest behavior here, over real HTTP, instead of silently faking a
    # cloud response.
    return 503, {"detail": "Explain-more provider unavailable: no network access configured in this environment."}


def _campaign_graph_view() -> dict:
    view = _campaign_graph.k_anonymized_view()
    nodes = [{"node_key": n, "kind": str(data.get("kind", "unknown"))} for n, data in view.nodes(data=True)]
    edges = [
        {"node_a": a, "node_b": b, "corroborating_report_count": _campaign_graph.corroboration_count(a, b)}
        for a, b in view.edges()
    ]
    return {"nodes": nodes, "edges": edges}


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "service": "trusttrace-backend-stdlib-dev"})
        elif self.path == "/v1/campaign-graph":
            self._send_json(200, _campaign_graph_view())
        else:
            self._send_json(404, {"detail": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"detail": "invalid JSON body"})
            return

        if self.path == "/v1/analyze-transcript":
            self._send_json(200, _analyze_transcript(body))
        elif self.path == "/v1/explain-more":
            status, payload = _explain_more(body)
            self._send_json(status, payload)
        else:
            self._send_json(404, {"detail": "not found"})

    def log_message(self, format, *args):
        pass  # quiet -- avoid polluting test output


def serve(port: int = 8787) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return server


if __name__ == "__main__":
    srv = serve()
    print(f"TrustTrace stdlib dev server listening on http://127.0.0.1:{srv.server_port}")
    srv.serve_forever()
