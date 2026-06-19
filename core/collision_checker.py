"""core/collision_checker.py

At startup, calls packet_signature() on every registered test and raises a
clear, specific error if two tests would produce indistinguishable packets.
Called from core/test_runner.register_all_tests().
"""
from __future__ import annotations

from typing import List


def check_for_collisions(tests: List) -> None:
    """Raises ValueError naming the two specific colliding tests if any two
    tests' packet_signature() would produce indistinguishable packets."""
    seen = {}
    for test in tests:
        signature = test.packet_signature()
        key = tuple(sorted(signature.items()))
        if key in seen:
            other = seen[key]
            raise ValueError(
                f"packet_signature collision between "
                f"'{getattr(other, 'id', repr(other))}' and "
                f"'{getattr(test, 'id', repr(test))}': both produce signature "
                f"{dict(signature)!r}"
            )
        seen[key] = test
