"""Seeded random draws keyed by what they are for.

A draw depends only on the seed and its key (merchant, segment, purpose), so the same
merchant behaves the same way in every approach the simulation compares.
"""

import hashlib


def draw(seed: int, *key: object) -> float:
    """A uniform number in [0, 1) fixed by the seed and the key."""
    digest = hashlib.blake2b(repr((seed, *key)).encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64
