"""
On-device LoRA adapter fine-tuning.

Spec ref: PDF Section 2.6: "When the on-device cascade detects a genuinely
novel scam pattern, it fine-tunes a small local LoRA adapter -- not the
full model." Section 8.4: strict separation between the raw
conversational-context store and whatever the local training pipeline
actually reads.

REAL vs SIM: actual LoRA fine-tuning needs the real Llama-3.2 base model
loaded on-device (multi-GB weights, a training-capable runtime) -- not
available in this sandbox. What's real here: the STRICT PRIVACY BOUNDARY
spec 8.4 requires (the training pipeline reads only a de-identified,
structured training-example view -- never the raw ConversationMemory
object with its full risk-flag/entity history), verified by type
signature -- `TrainingExample` has no field that could carry raw
session/user-linkable state.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class TrainingExample:
    """The ONLY shape local_trainer.py is allowed to read. No session_id,
    no user identifier, no raw conversation history -- just the minimum
    (text, label) pair needed to fine-tune the novel-pattern adapter.
    This is what "strict separation between the raw conversational-context
    store and whatever the local training pipeline actually reads" means
    as an enforceable type, not just a policy statement."""
    normalized_text: str
    tactic_label: str


def extract_training_example(structured_summary_entry: dict) -> TrainingExample | None:
    """
    The ONLY sanctioned crossing point from memory_compaction.py's
    structured_summary() output into the training pipeline. Deliberately
    drops everything except text + label -- turn index, confidence score,
    session id, and entity data never cross this boundary.
    """
    evidence = structured_summary_entry.get("evidence")
    tactic = structured_summary_entry.get("tactic")
    if not evidence or not tactic:
        return None
    return TrainingExample(normalized_text=evidence, tactic_label=tactic)


@dataclass
class LoraAdapterUpdate:
    """What a real on-device LoRA fine-tune step would produce: a small
    delta to a low-rank adapter, not full-model weights. Represented here
    as an opaque-shaped placeholder (a small numpy-array-shaped delta in
    production) -- this file's job ends at producing the update; dp_noise.py
    and secure_aggregation.py handle everything from here onward."""
    adapter_name: str
    delta_shape: tuple
    training_example_count: int
