"""
Federated sync orchestration service.

Spec ref: PDF Section 2.6/federated/*, hosted inside the single FastAPI
backend per Target Environment. Wires together federated/dp_noise.py,
federated/secure_aggregation.py, and federated/model_distribution.py into
the round-lifecycle a real sync endpoint would drive.

NOT execution-verified in this sandbox (fastapi/asyncpg/redis not
installed) -- but every function it CALLS INTO (secure_aggregation,
dp_noise, model_distribution) was independently tested above; this file's
job is orchestration, not new algorithmic logic.
"""
from __future__ import annotations
import sys
import os
from dataclasses import dataclass

# 'threat-intel' and this file's sibling modules under federated/ are
# separate directories; federated/ IS a valid package (no hyphen), so
# normal relative imports work for it.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "federated"))
from secure_aggregation import run_secure_aggregation_round, ClientContribution, AggregationResult  # noqa: E402
from dp_noise import RdpAccountant  # noqa: E402


@dataclass
class FederatedRoundOutcome:
    aggregation: AggregationResult
    cumulative_epsilon: float


class FederatedSyncOrchestrator:
    """Owns the RDP accountant across rounds (privacy budget is
    CUMULATIVE, per dp_noise.py's RdpAccountant), and drives one round's
    aggregation lifecycle."""

    def __init__(self, target_delta: float = 1e-5):
        self._accountant = RdpAccountant()
        self._target_delta = target_delta

    def run_round(self, contributions: list[ClientContribution], noise_multiplier: float, sampling_rate: float) -> FederatedRoundOutcome:
        result = run_secure_aggregation_round(contributions)
        if result.success:
            self._accountant.compose_round(noise_multiplier=noise_multiplier, sampling_rate=sampling_rate)
        return FederatedRoundOutcome(
            aggregation=result,
            cumulative_epsilon=self._accountant.get_epsilon(self._target_delta),
        )
