"""
Provider-agnostic opt-in cloud "explain more" client wrapper.

Spec ref: PDF Section 5: "Any cloud LLM call is opt-in per use ('explain
more'), never automatic, and transcripts are not retained server-side
beyond the single request." Target Environment: "provider-agnostic client
wrapper."

Enforcement note: this is the ONLY file in the entire backend permitted to
make an external LLM API call -- every other module (detection/,
grounding/, threat-intel/) is fully on-device-equivalent / local
computation. Keeping that call surface in exactly one file is what makes
"opt-in per use, never automatic" auditable: there is one place to check,
not a scattered set of call sites.

REAL vs SIM:
- LocalLlamaProvider: REAL on-device explanation via llama.cpp when Tier 2
  GGUF weights are present (the spec's on-device-first path for explain).
- AnthropicProvider: REAL HTTPS call to api.anthropic.com/v1/messages via
  stdlib urllib (no extra dependency), used only when an API key is set
  AND the caller opted into cloud. Honors spec 5 no-retention: the excerpt
  is never written to disk or logged here.
- NoProviderConfigured: explicit unavailability, never a fabricated answer.

Provider resolution order (build_provider): on-device Llama first, then
cloud Anthropic if a key is configured, else NoProviderConfigured.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass


class LlmProviderError(Exception):
    pass


class LlmProvider(ABC):
    @abstractmethod
    async def complete(self, prompt: str) -> str: ...


class LocalLlamaProvider(LlmProvider):
    """On-device-first explanation: reuses the same llama.cpp runtime and
    Tier 2 weights the detection cascade uses. No network, no data leaves
    the box. Returns via the detection.conversation.llm_runtime seam."""

    async def complete(self, prompt: str) -> str:
        try:
            from detection.conversation.llm_runtime import (
                _llama_available,
                _load_model,
                TIER1_MODEL_PATH,
                TIER2_MODEL_PATH,
            )
        except Exception as exc:  # pragma: no cover - import guard
            raise LlmProviderError(f"local runtime import failed: {exc}") from exc
        # Prefer Tier 2 (better explanations); degrade to Tier 1 rather than
        # failing the request when only the smaller model is installed.
        model_path = TIER2_MODEL_PATH if os.path.isfile(TIER2_MODEL_PATH) else TIER1_MODEL_PATH
        if not _llama_available(model_path):
            raise LlmProviderError(
                f"local Llama weights not present (looked for {model_path}); "
                "set TRUSTTRACE_TIER1_GGUF / TRUSTTRACE_TIER2_GGUF"
            )
        try:
            model = _load_model(model_path)
            resp = model.create_chat_completion(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=300,
            )
            return str(resp["choices"][0]["message"]["content"]).strip()
        except Exception as exc:
            raise LlmProviderError(f"local explanation failed: {exc}") from exc


class AnthropicProvider(LlmProvider):
    """Real Anthropic Messages API call over stdlib urllib -- no SDK dep."""

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model: str | None = None):
        self._api_key = api_key
        self._model = model or os.environ.get(
            "TRUSTTRACE_ANTHROPIC_MODEL", "claude-3-5-haiku-latest"
        )

    async def complete(self, prompt: str) -> str:
        payload = json.dumps(
            {
                "model": self._model,
                "max_tokens": 400,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            self.API_URL,
            data=payload,
            method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            # urlopen is blocking; run it off the event loop so the async
            # aggregation/server loop is never stalled (spec 10.4).
            import asyncio

            def _do_request() -> str:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                parts = body.get("content", [])
                text = "".join(
                    p.get("text", "") for p in parts if p.get("type") == "text"
                )
                if not text:
                    raise LlmProviderError("empty response from provider")
                return text.strip()

            return await asyncio.get_event_loop().run_in_executor(None, _do_request)
        except urllib.error.HTTPError as exc:
            raise LlmProviderError(f"provider HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise LlmProviderError(f"provider unreachable: {exc.reason}") from exc


class NoProviderConfigured(LlmProvider):
    async def complete(self, prompt: str) -> str:
        raise LlmProviderError(
            "No LLM provider configured -- 'explain more' is unavailable until one is set."
        )


@dataclass
class ExplainRequest:
    transcript_excerpt: str  # already length-capped by ExplainMoreRequest's Pydantic Field


EXPLAIN_SYSTEM_PREAMBLE = (
    "You are explaining a possible scam-manipulation pattern in plain, non-technical "
    "language for a general audience, including non-native English speakers and elderly "
    "users. Do not use security jargon. Cite the specific words that concerned you. "
    "Never claim certainty -- explain what the pattern usually means and why it's worth "
    "caution, not a verdict."
)


async def explain_more(provider: LlmProvider, request: ExplainRequest) -> str:
    """
    The single call site. `request.transcript_excerpt` is NOT persisted
    anywhere by this function -- no database write, no logging of the
    excerpt content -- per spec 5's "not retained server-side beyond the
    single request."
    """
    prompt = f'{EXPLAIN_SYSTEM_PREAMBLE}\n\nMessage: "{request.transcript_excerpt}"'
    return await provider.complete(prompt)


def build_provider(provider_name: str, api_key: str | None) -> LlmProvider:
    """On-device-first: prefer local Llama when weights are present, then
    cloud Anthropic if a key is configured, else explicit unavailability."""
    # On-device path first (spec 5: on-device-first for every module).
    # Either tier is enough for the explain layer: it prefers Tier 2 and
    # degrades to Tier 1, so gate on whichever weights are present.
    try:
        from detection.conversation.llm_runtime import (
            _llama_available,
            TIER1_MODEL_PATH,
            TIER2_MODEL_PATH,
        )

        if _llama_available(TIER2_MODEL_PATH) or _llama_available(TIER1_MODEL_PATH):
            return LocalLlamaProvider()
    except Exception:
        pass
    if provider_name == "anthropic" and api_key:
        return AnthropicProvider(api_key)
    return NoProviderConfigured()
