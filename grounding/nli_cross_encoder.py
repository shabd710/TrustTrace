"""
Real NLI cross-encoder for the entailment gate (GPU or CPU).

Spec ref: PDF Section 2.5 (small quantized cross-encoder NLI) and 8.2
(cross-encoder joint attention). REAL swap-in for the deterministic
entailment stand-in in grounding/nli_entailment_gate.py.

=== REAL vs SIM boundary ===
- With transformers + a downloaded NLI model: real cross-encoder pass.
- Without them (this sandbox): returns None, and nli_entailment_gate.py
  keeps its TESTED deterministic gate (real negation/hypothetical
  handling already verified by adversarial tests).

See docs/REAL_MODELS_SETUP.md.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

NLI_MODEL = os.environ.get("TRUSTTRACE_NLI_MODEL", "cross-encoder/nli-deberta-v3-small")


@dataclass
class NliResult:
    entailment_prob: float
    label: str


def _transformers_available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def _load_nli():
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(NLI_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(NLI_MODEL)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device).eval()
    return tok, model, device


def evaluate_entailment_nli(premise: str, hypothesis: str) -> Optional[NliResult]:
    """Real cross-encoder NLI, or None if unavailable (caller falls back)."""
    if not _transformers_available():
        return None
    try:
        import torch
        tok, model, device = _load_nli()
        inputs = tok(premise, hypothesis, return_tensors="pt", truncation=True, max_length=256).to(device)
        with torch.no_grad():
            probs = torch.softmax(model(**inputs).logits[0], dim=-1).cpu().tolist()
        id2label = getattr(model.config, "id2label", None)
        if id2label:
            label_probs = {id2label[i].lower(): p for i, p in enumerate(probs)}
            ent = label_probs.get("entailment", probs[-1])
            top = max(label_probs, key=label_probs.get)
        else:
            ent = probs[-1]
            top = ["contradiction", "neutral", "entailment"][max(range(len(probs)), key=lambda i: probs[i])]
        return NliResult(entailment_prob=float(ent), label=top)
    except Exception:
        return None
