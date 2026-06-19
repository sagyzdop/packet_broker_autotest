"""core/dpi_stub.py

Plays the role of the DPI engine from the test framework's side. The
broker's DPI-facing LAG is wired directly back into the test server's own
dpi1..N interfaces -- there is no separate physical DPI appliance in this
rig, in sandbox or real-hardware mode (see CLAUDE.md -> "Architecture").
Something has to receive traffic on those interfaces, decide a PCP value,
stamp it into the outer VLAN tag, and send the frame back; without this
component every DPI-flow test would time out forever.

This runs as one shared component rather than per-test logic because
multiple DPI-flow tests (PCP 0/1/2/3 -- only PCP=0 in MVP scope) all share
the same physical DPI interfaces, mirroring how a real DPI engine serves
the whole broker rather than one engine per flow. `register()`/`run()` are
written generically over `pcp_value`, so adding PCP 1/2/3 tests later is
purely a matter of registering more tests, with zero changes to this file.

This file does not disappear on real hardware -- unlike
sandbox/broker_sim/broker_sim.py (which stands in for the broker itself and
is replaced by a real device), DpiStub plays the DPI engine's role in both
environments; only the interface names in topology.yaml change.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, List, Tuple

from scapy.layers.l2 import Dot1Q, Ether

from core.packet_builder import serialize

logger = logging.getLogger(__name__)


class DpiStub:
    """Plays the DPI engine's role on every interface in `dpi_interfaces` (see
    this file's module docstring above)."""

    def __init__(self, engine, dpi_interfaces: List[str], dpi_vlan_id: int):
        self.engine = engine
        self.dpi_interfaces = list(dpi_interfaces)
        self.dpi_vlan_id = dpi_vlan_id
        # (predicate, pcp_value) pairs, one per registered DPI-flow test --
        # see register().
        self._registrations: List[Tuple[Callable[[bytes], bool], int]] = []

    def register(self, predicate: Callable[[bytes], bool], pcp_value: int) -> None:
        self._registrations.append((predicate, pcp_value))

    def _matches_any_registration(self, raw: bytes) -> bool:
        """Subscription predicate for engine.get(ifname).subscribe(...): true if
        ANY registered DPI-flow test's predicate matches this frame."""
        return any(predicate(raw) for predicate, _ in self._registrations)

    async def run(self) -> None:
        queues = [
            (ifname, self.engine.get(ifname).subscribe(self._matches_any_registration))
            for ifname in self.dpi_interfaces
        ]

        async def consume(ifname: str, queue: asyncio.Queue) -> None:
            while True:
                raw = await queue.get()
                self._echo(ifname, raw)

        await asyncio.gather(*(consume(ifname, queue) for ifname, queue in queues))

    def _echo(self, ifname: str, raw: bytes) -> None:
        try:
            pkt = Ether(raw)
        except Exception:
            logger.exception("DpiStub: failed to parse frame received on %s", ifname)
            return

        pcp_value = None
        for predicate, pcp in self._registrations:
            try:
                if predicate(raw):
                    pcp_value = pcp
                    break
            except Exception:
                logger.exception("DpiStub: registered predicate raised on %s", ifname)
        if pcp_value is None:
            # Should not happen -- _matches_any_registration already filtered for
            # this -- but don't crash the run() loop over a stale/edge-case frame.
            logger.warning("DpiStub: frame on %s matched no registered predicate", ifname)
            return

        if not pkt.haslayer(Dot1Q):
            logger.warning(
                "DpiStub: frame on %s has no outer VLAN tag to strip (expected one "
                "added by the broker before DPI-eligible traffic reaches here)",
                ifname,
            )
            inner = pkt.payload
        else:
            inner = pkt[Dot1Q].payload

        echoed = Ether(src=pkt.src, dst=pkt.dst) / Dot1Q(vlan=self.dpi_vlan_id, prio=pcp_value) / inner
        self.engine.get(ifname).send(serialize(echoed))
