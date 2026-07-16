"""
Real on-device LLM runtime for the Tier 1/2 cascade (Linux + GPU).

Spec ref: PDF Target Environment (Tier 1 = Llama-3.2-1B quantized; Tier 2
= Llama-3.2-3B 4-bit default) and Section 3.4 (mature runtime). REAL
swap-in for the deterministic Tier-1/2 stand-in.

=== REAL vs SIM boundary ===
- With GGUF weights + llama-cpp-python installed: REAL model inference.
- Without them (this sandbox / CPU-only): returns None, and
  model_cascade.py keeps its TESTED heuristic path. The cascade never
  breaks; it degrades to verified deterministic behavior.

Import-verified for the fallback path; the inference path runs on a
machine with weights + a CUDA build. See docs/REAL_MODELS_SETUP.md.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

TIER1_MODEL_PATH = os.environ.get(
    "TRUSTTRACE_TIER1_GGUF",
    os.path.expanduser("~/models/Llama-3.2-1B-Instruct-Q4_K_M.gguf"),
)
TIER2_MODEL_PATH = os.environ.get(
    "TRUSTTRACE_TIER2_GGUF",
    os.path.expanduser("~/models/Llama-3.2-3B-Instruct-Q4_K_M.gguf"),
)
N_GPU_LAYERS = int(os.environ.get("TRUSTTRACE_N_GPU_LAYERS", "-1"))
N_CTX = int(os.environ.get("TRUSTTRACE_N_CTX", "4096"))


@dataclass
class LlmRefinement:
    tactic_id: str
    confidence: float
    rationale: str


def _llama_available(model_path: str | None = None) -> bool:
    """True when llama-cpp-python imports AND the weights actually used are on
    disk. Callers that load a non-Tier-1 model (e.g. the explain layer, which
    uses Tier 2) must pass that path -- otherwise availability is checked
    against a different file than the one loaded."""
    try:
        import llama_cpp  # noqa: F401
    except Exception:
        return False
    return os.path.isfile(model_path or TIER1_MODEL_PATH)


@lru_cache(maxsize=2)
def _load_model(model_path: str):
    from llama_cpp import Llama
    return Llama(model_path=model_path, n_gpu_layers=N_GPU_LAYERS, n_ctx=N_CTX, verbose=False)


_SYSTEM_PROMPT = (
    "You are a careful fraud-analysis assistant. For each flagged "
    "manipulation tactic, judge ONLY whether the quoted message text "
    "actually supports that tactic. Output strict JSON: a list of "
    '{"tactic_id": str, "confidence": 0.0-1.0, "rationale": str}. '
    "Confidence reflects how strongly the QUOTED TEXT supports the tactic, "
    "not general suspicion. Keep rationale under 20 words, grounded in the "
    "quoted text. Never invent text that is not present."
)


def _build_user_prompt(text: str, tactic_ids: list[str]) -> str:
    return (f"MESSAGE TEXT:\n{text}\n\n"
            f"FLAGGED TACTICS TO ASSESS: {', '.join(tactic_ids)}\n\n"
            "Return the JSON list now.")


def refine_candidates_with_llm(text: str, tactic_ids: list[str], tier: int = 1) -> Optional[list[LlmRefinement]]:
    """Real LLM refinement, or None if runtime/weights unavailable."""
    if not tactic_ids or not _llama_available():
        return None
    model_path = TIER2_MODEL_PATH if tier == 2 else TIER1_MODEL_PATH
    if not os.path.isfile(model_path):
        return None
    try:
        model = _load_model(model_path)
        resp = model.create_chat_completion(
            messages=[{"role": "system", "content": _SYSTEM_PROMPT},
                      {"role": "user", "content": _build_user_prompt(text, tactic_ids)}],
            temperature=0.0, max_tokens=512, response_format={"type": "json_object"},
        )
        content = resp["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        rows = parsed if isinstance(parsed, list) else parsed.get("results", [])
        out: list[LlmRefinement] = []
        valid = set(tactic_ids)
        for row in rows:
            tid = str(row.get("tactic_id", ""))
            if tid not in valid:
                continue
            conf = max(0.0, min(1.0, float(row.get("confidence", 0.0))))
            out.append(LlmRefinement(tactic_id=tid, confidence=conf,
                                     rationale=str(row.get("rationale", ""))[:200]))
        return out or None
    except Exception:
        return None
