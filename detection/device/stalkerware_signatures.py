"""
Stalkerware signature matching with a Bloom-filter pre-check.

Spec ref: PDF Section 7.4 / 9.5: Bloom filter is a fast O(1) PRE-FILTER
only -- any hit must clear an exact signature match before it can ever
become a user-facing flag, since a Bloom filter has false positives by
construction and this system's own grounding standard forbids surfacing
an unconfirmed probabilistic hit as "stalkerware detected".

Real, running logic: a genuine (if small/toy-sized) Bloom filter
implementation using Python's hashlib for independent hash functions, plus
the exact-match confirmation step. Sized here for a small demo signature
set; production sizing (bit-array size, hash-function count) is calibrated
against the real EFF Coalition Against Stalkerware feed's actual signature
volume, per spec 9.5.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field


@dataclass
class BloomFilter:
    size_bits: int
    hash_count: int
    bits: bytearray = field(init=False)

    def __post_init__(self):
        self.bits = bytearray((self.size_bits + 7) // 8)

    def _indices(self, item: str) -> list[int]:
        idxs = []
        for i in range(self.hash_count):
            h = hashlib.sha256(f"{i}:{item}".encode()).digest()
            idx = int.from_bytes(h[:8], "big") % self.size_bits
            idxs.append(idx)
        return idxs

    def add(self, item: str) -> None:
        for idx in self._indices(item):
            self.bits[idx // 8] |= (1 << (idx % 8))

    def might_contain(self, item: str) -> bool:
        return all(self.bits[idx // 8] & (1 << (idx % 8)) for idx in self._indices(item))


@dataclass
class SignatureMatch:
    signature_id: str
    exact_match_confirmed: bool


class StalkerwareSignatureIndex:
    """Wraps a Bloom-filter pre-filter + an exact-match set, so a
    probabilistic Bloom hit NEVER alone becomes `exact_match_confirmed=True`
    -- callers must check that field before surfacing anything to the user."""

    def __init__(self, known_signatures: list[str], bloom_size_bits: int = 8192, bloom_hash_count: int = 5):
        self._exact_set = set(known_signatures)
        self._bloom = BloomFilter(size_bits=bloom_size_bits, hash_count=bloom_hash_count)
        for sig in known_signatures:
            self._bloom.add(sig)

    def check(self, candidate_signature: str) -> SignatureMatch | None:
        if not self._bloom.might_contain(candidate_signature):
            return None  # definitely not present -- Bloom filters have no false negatives
        exact = candidate_signature in self._exact_set
        return SignatureMatch(signature_id=candidate_signature, exact_match_confirmed=exact)
