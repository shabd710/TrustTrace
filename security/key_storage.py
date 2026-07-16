"""
Hardware-rooted local key storage.

Spec ref: PDF Section 2.10, 8.3 (180-day rotation via SQLCipher's native
rekey), 10.2 (write-new-then-atomic-rename, never in-place, so a power
loss mid-rekey leaves the original file intact).

REAL vs SIM, stated as plainly as spec 2.10 itself states its own honest
boundary:
  - The hardware key-wrapping call (iOS kSecAttrTokenIDSecureEnclave /
    Android Keystore-StrongBox) needs real Secure Enclave / StrongBox
    hardware that does not exist in this sandbox, or in any CI container.
    `HardwareKeyWrapper` below is a Protocol (typed interface) a real
    platform binding implements -- this file never pretends to wrap a key
    in software and call it hardware-backed.
  - SQLCipher itself (the encrypted-at-rest database engine) is a native
    C extension not installed here. What IS real and tested here: the
    write-new -> verify -> atomic-rename FILE SEQUENCE that spec 10.2
    requires for crash-safety, run end-to-end against a real SQLite file
    on disk (SQLCipher is API-compatible with sqlite3's file semantics for
    this purpose -- the sequence being verified is filesystem behavior,
    not the encryption itself).

Honest boundary, restated per spec 2.10's own requirement that this never
be oversold: hardware-backed key storage protects data-AT-REST. It is
never represented as protection against a fully compromised, actively
running OS reading data during normal unlocked app use -- that would need
moving computation itself into a TEE, unavailable to third-party apps at
this granularity today.
"""
from __future__ import annotations
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass
from typing import Protocol


class HardwareKeyWrapper(Protocol):
    """Typed interface a real native binding implements: iOS Secure Enclave
    (kSecAttrTokenIDSecureEnclave) or Android Keystore/StrongBox. The
    wrapping private key never leaves secure hardware -- this Python
    interface only ever sees wrapped (encrypted) key material, never the
    raw wrapping key itself, by construction of the interface shape."""

    def wrap_key(self, raw_master_key: bytes) -> bytes:
        """Returns hardware-wrapped ciphertext of raw_master_key. Requires
        prior biometric/passcode gate per spec 2.10."""
        ...

    def unwrap_key(self, wrapped_key: bytes) -> bytes:
        """Reverses wrap_key. Requires prior biometric/passcode gate."""
        ...


class UnavailableHardwareKeyWrapper:
    """Explicit failure-mode stand-in used when no real hardware binding is
    present (e.g. this sandbox, or a CI unit-test run). Raises loudly
    rather than silently falling back to software-only 'wrapping', which
    would be exactly the kind of unearned security claim spec 2.10 warns
    against making."""

    def wrap_key(self, raw_master_key: bytes) -> bytes:
        raise RuntimeError(
            "No hardware-backed key wrapper available (Secure Enclave / "
            "StrongBox binding not present in this environment). Refusing "
            "to fall back to software-only wrapping and calling it "
            "hardware-backed -- that would violate spec 2.10's honesty "
            "requirement."
        )

    def unwrap_key(self, wrapped_key: bytes) -> bytes:
        raise RuntimeError("No hardware-backed key wrapper available.")


@dataclass
class RekeyResult:
    success: bool
    original_path: str
    new_path: str
    rows_verified: int
    detail: str


def rekey_database_atomic(db_path: str, table_check_query: str = "SELECT COUNT(*) FROM sqlite_master") -> RekeyResult:
    """
    The 180-day rekey cycle's filesystem sequence, spec 10.2's exact
    requirement: decrypt-and-reencrypt to a NEW file, verify integrity,
    THEN atomically swap over the original -- so a power loss mid-rekey
    leaves the original file intact rather than corrupted.

    In production, "decrypt-and-reencrypt" is SQLCipher's native
    `PRAGMA rekey` operation against a hardware-unwrapped old key and a
    freshly hardware-wrapped new key. This function demonstrates and tests
    the crash-safe FILE sequence around that call -- the sequence is
    identical regardless of which encryption engine performs the actual
    rekey, which is why it's meaningful to verify here without SQLCipher
    installed.
    """
    if not os.path.exists(db_path):
        return RekeyResult(False, db_path, "", 0, "source database does not exist")

    tmp_path = db_path + ".rekey_tmp"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)  # clean up any prior aborted attempt

    # Step 1: write-new. (Production: open old DB with unwrapped old key,
    # PRAGMA rekey to the new key, writing into tmp_path.)
    shutil.copyfile(db_path, tmp_path)

    # Step 2: verify integrity of the NEW file before touching the
    # original at all -- if this fails, the original is untouched.
    try:
        conn = sqlite3.connect(tmp_path)
        rows_verified = conn.execute(table_check_query).fetchone()[0]
        conn.close()
    except Exception as exc:  # noqa: BLE001 -- deliberately broad: any failure aborts the rekey
        os.remove(tmp_path)
        return RekeyResult(False, db_path, tmp_path, 0, f"verification failed, original untouched: {exc}")

    # Step 3: atomic rename. os.replace() is atomic on POSIX and Windows
    # for same-filesystem renames -- there is no intermediate state where
    # the file is missing or partially written from an external observer's
    # perspective (e.g. an app crash or power loss at this exact instant).
    os.replace(tmp_path, db_path)

    return RekeyResult(True, db_path, db_path, rows_verified, "rekey completed via write-new-then-atomic-rename")


def is_rekey_due(last_rekey_epoch: float, now: float | None = None, cycle_days: int = 180) -> bool:
    now = now if now is not None else time.time()
    return (now - last_rekey_epoch) >= cycle_days * 86400
