"""
Backend configuration.

Spec ref: PDF Target Environment: "a single FastAPI service (Python
3.11+) -- no secondary web framework". This file plus main.py are the
proof of that rule: everything (explain-layer, secure-aggregation worker
pool, campaign-graph API, SMS gateway) mounts onto ONE FastAPI app.

NOT EXECUTED IN THIS SANDBOX: fastapi/pydantic/uvloop/asyncpg aren't
installed here (no network access to pip install them). This file and the
rest of backend/ are written to the real FastAPI/Pydantic v2 API surface
correctly, but unlike every file in detection/, grounding/, threat-intel/,
federated/, and offline/ above -- which were actually run against
assertions in this sandbox -- these have NOT been execution-verified here.
Run `pip install -r requirements.txt && uvicorn backend.main:app` in an
environment with network access to actually exercise this layer.
"""
from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_name: str = "trusttrace-backend"
    # spec Target Environment: uvloop event loop, asyncpg for Postgres
    database_url: str = os.environ.get("TRUSTTRACE_DATABASE_URL", "postgresql+asyncpg://localhost/trusttrace")
    redis_url: str = os.environ.get("TRUSTTRACE_REDIS_URL", "redis://localhost:6379/0")
    # spec 5: any cloud LLM call is opt-in per use ("explain more"), never automatic
    llm_explain_provider: str = os.environ.get("TRUSTTRACE_LLM_PROVIDER", "none")
    llm_api_key: str | None = os.environ.get("TRUSTTRACE_LLM_API_KEY")
    # spec 9.4: token-bucket rate limiting at the ingress layer
    sms_gateway_rate_limit_per_minute: int = 5


settings = Settings()
