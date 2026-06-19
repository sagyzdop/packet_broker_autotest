"""core/base_test.py

The abstract contract every test case (tests/test_*.py) implements, plus the
shared "wrap, send, then check" logic for one iteration. The asyncio
scheduling that runs that iteration forever lives in core/test_runner.py,
not here -- `run_once()` below is reused unchanged by that infinite loop, so
there is no separate "run once" vs "run forever" code path.

See CLAUDE.md -> "Architecture".
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Literal, Optional

from scapy.layers.l2 import Ether

from core.matcher import PacketMatcher
from core.packet_builder import DEFAULT_ENCAP, EncapConfig, apply_encap, serialize

# Default time to wait for a matching frame on expect_interface() before a
# TestResult of status="TIMEOUT" is recorded.
DEFAULT_TIMEOUT_S = 2.0


@dataclass
class TestResult:
    status: Literal["OK", "FAIL", "TIMEOUT"]
    latency_ms: Optional[float]
    failures: List[str]
    timestamp: float


def _predicate_from_signature(signature: dict):
    """Builds the subscribe() predicate from packet_signature() by reusing
    PacketMatcher -- the signature dict's keys are exactly PacketMatcher's
    field names, so this is just "does this raw frame match those fields"."""
    matcher = PacketMatcher(**signature)

    def predicate(raw: bytes) -> bool:
        try:
            pkt = Ether(raw)
        except Exception:
            return False
        return matcher.match(pkt).ok

    return predicate


class BaseTest(ABC):
    # Overridable per-instance, not hardcoded per-subclass.
    encap: EncapConfig = DEFAULT_ENCAP
    pair = None  # injected by test_runner.py at registration; type core.topology.Pair

    def __init__(self):
        self.encap: EncapConfig = DEFAULT_ENCAP
        self.pair = None

    @abstractmethod
    def build_packet(self):
        """Builds the INNER packet only -- no encapsulation applied yet."""
        raise NotImplementedError

    @abstractmethod
    def matcher(self) -> PacketMatcher:
        """Declares which fields of the RECEIVED packet must match for a PASS."""
        raise NotImplementedError

    @abstractmethod
    def packet_signature(self) -> dict:
        """Field/value pairs that make this test's packets unique on the wire."""
        raise NotImplementedError

    @abstractmethod
    def send_interface(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def expect_interface(self) -> str:
        raise NotImplementedError

    def wrap(self, pkt):
        return apply_encap(pkt, self.encap)

    async def run_once(self, engine, timeout_s: float = DEFAULT_TIMEOUT_S) -> TestResult:
        pkt = self.wrap(self.build_packet())
        raw = serialize(pkt)

        dispatcher = engine.get(self.expect_interface())
        predicate = _predicate_from_signature(self.packet_signature())
        queue = dispatcher.subscribe(predicate)

        start = time.monotonic()
        try:
            engine.get(self.send_interface()).send(raw)

            try:
                received = await asyncio.wait_for(queue.get(), timeout=timeout_s)
            except asyncio.TimeoutError:
                return TestResult(
                    status="TIMEOUT",
                    latency_ms=None,
                    failures=[f"no matching frame received on {self.expect_interface()} within {timeout_s}s"],
                    timestamp=time.time(),
                )

            latency_ms = (time.monotonic() - start) * 1000
            received_pkt = Ether(received)
            result = self.matcher().match(received_pkt)
            return TestResult(
                status="OK" if result.ok else "FAIL",
                latency_ms=latency_ms,
                failures=result.failures,
                timestamp=time.time(),
            )
        finally:
            dispatcher.unsubscribe(queue)
