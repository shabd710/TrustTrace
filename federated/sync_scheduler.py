"""
Charging + WiFi sync gate, continuously re-verified mid-transfer.

Spec ref: PDF Target Environment ("sync scheduled to charging + WiFi
only"), 8.4 ("Continuous mid-transfer verification of charging/unmetered
state -- aborting immediately if conditions change during an in-progress
upload, not just checked once at the start"), 10.4 (exponential backoff,
giving up until the next scheduled sync window rather than looping against
unstable connectivity).
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from enum import Enum


class DeviceState(str, Enum):
    OK = "ok"
    UNPLUGGED_MID_TRANSFER = "unplugged_mid_transfer"
    METERED_NETWORK_MID_TRANSFER = "metered_network_mid_transfer"


@dataclass
class DeviceStateProvider:
    """Native platform binding in production (BatteryManager / ConnectivityManager
    on Android, equivalent iOS APIs). A simple polling function here so the
    scheduler's abort logic can be tested without a real device."""
    is_charging_fn: callable
    is_unmetered_wifi_fn: callable

    def poll(self) -> DeviceState:
        if not self.is_charging_fn():
            return DeviceState.UNPLUGGED_MID_TRANSFER
        if not self.is_unmetered_wifi_fn():
            return DeviceState.METERED_NETWORK_MID_TRANSFER
        return DeviceState.OK


@dataclass
class SyncOutcome:
    completed: bool
    aborted_reason: str | None
    chunks_transferred: int
    retry_after_seconds: float | None


def run_sync_with_continuous_verification(
    total_chunks: int,
    provider: DeviceStateProvider,
    poll_interval_chunks: int = 1,
) -> SyncOutcome:
    """
    Transfers total_chunks, re-polling device state before EVERY chunk
    (poll_interval_chunks=1 by default -- continuous, not one-time)
    rather than only checking once at the start.
    """
    for chunk_index in range(total_chunks):
        if chunk_index % poll_interval_chunks == 0:
            state = provider.poll()
            if state != DeviceState.OK:
                return SyncOutcome(
                    completed=False, aborted_reason=state.value,
                    chunks_transferred=chunk_index, retry_after_seconds=None,
                )
        # (real chunk upload happens here in production)
    return SyncOutcome(completed=True, aborted_reason=None, chunks_transferred=total_chunks, retry_after_seconds=None)


def next_retry_delay(attempt_number: int, base_seconds: float = 30.0, max_seconds: float = 3600.0) -> float:
    """Exponential backoff per spec 10.4 -- giving up until the next
    scheduled sync window rather than looping against unstable
    connectivity, instead of immediate infinite retry."""
    return min(max_seconds, base_seconds * (2 ** attempt_number))
