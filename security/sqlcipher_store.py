"""
Real SQLCipher-encrypted local store (Linux/Windows with pysqlcipher3).

Spec ref: PDF Section 2.10 (SQLCipher, HW-wrapped key) and 8.3/10.2
(180-day rekey, write-new-then-atomic-rename). REAL swap-in for plain
sqlite3 -- genuine AES-256 at-rest encryption.

=== REAL vs SIM boundary ===
- With pysqlcipher3 + the SQLCipher native lib: REAL encrypted DB (the
  file on disk is AES-256 ciphertext; verify_encrypted_on_disk() proves
  it can't be opened as plain sqlite3).
- Without it (this sandbox): open_encrypted_store() falls back to plain
  sqlite3 with a LOUD flag (encrypted=False). Nothing silently pretends.

HONEST HARDWARE BOUNDARY (spec 2.10): the master key here is a SOFTWARE
key (keyfile, 0600). True Secure Enclave / StrongBox custody needs the
phone's security chip, which no PC has. Real ENCRYPTION; software custody.

See docs/REAL_MODELS_SETUP.md.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Optional


@dataclass
class EncryptedStore:
    connection: object
    encrypted: bool
    db_path: str


def _pysqlcipher_available() -> bool:
    try:
        from pysqlcipher3 import dbapi2  # noqa: F401
        return True
    except Exception:
        return False


def _get_or_create_key(keyfile: str) -> str:
    if os.path.isfile(keyfile):
        with open(keyfile) as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    old = os.umask(0o077)
    try:
        with open(keyfile, "w") as f:
            f.write(key)
    finally:
        os.umask(old)
    return key


def open_encrypted_store(db_path: str, keyfile: Optional[str] = None) -> EncryptedStore:
    """Real SQLCipher when available; clearly-flagged sqlite3 fallback otherwise."""
    keyfile = keyfile or (db_path + ".key")
    if _pysqlcipher_available():
        from pysqlcipher3 import dbapi2 as sqlcipher
        key = _get_or_create_key(keyfile)
        conn = sqlcipher.connect(db_path)
        conn.execute(f"PRAGMA key = \"x'{key}'\"")
        conn.execute("PRAGMA cipher_page_size = 4096")
        conn.execute("PRAGMA kdf_iter = 256000")
        conn.execute("CREATE TABLE IF NOT EXISTS _trusttrace_meta (k TEXT PRIMARY KEY, v TEXT)")
        conn.commit()
        return EncryptedStore(connection=conn, encrypted=True, db_path=db_path)
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS _trusttrace_meta (k TEXT PRIMARY KEY, v TEXT)")
    conn.commit()
    return EncryptedStore(connection=conn, encrypted=False, db_path=db_path)


def verify_encrypted_on_disk(db_path: str) -> bool:
    """True only if the file CANNOT be opened as plain sqlite3 -- proof of
    real encryption. Use in your own setup to confirm SQLCipher is active."""
    import sqlite3
    if not os.path.isfile(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        conn.close()
        return False
    except sqlite3.DatabaseError:
        return True
