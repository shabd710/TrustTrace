"""
Single FastAPI application entrypoint.

Spec ref: PDF Target Environment: "a single FastAPI service (Python
3.11+) -- no secondary web framework -- hosting the opt-in LLM
explain-layer, secure-aggregation worker pool, campaign-graph API, and
SMS gateway." Strict Instruction Summary: "The backend remains a single
framework (FastAPI) unless a concrete need for another is documented."

This file is the literal enforcement of that rule: there is exactly one
`FastAPI()` instantiation in this entire repository, and everything else
(api/routes.py, sync_service.py, the SMS gateway's carrier webhook)
mounts onto it.

NOT execution-verified in this sandbox -- run `pip install -r
requirements.txt && uvicorn backend.main:app --reload` in an environment
with network access.
"""
from __future__ import annotations
from fastapi import FastAPI

from .api.routes import router as api_router
from .config import settings

app = FastAPI(title=settings.app_name)
app.include_router(api_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": settings.app_name}
