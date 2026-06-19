"""
core/dpi_stub.py
===================
See README.md -> "The DPI Stub" -- read that section first. It explains
why this component must exist at all, since the original spec document
never names it as a distinct piece.

WHAT THIS FILE OWNS
-------------------
Plays the role of the DPI ENGINE from the test framework's side. Per the
system's topology (see README.md and topology.yaml), the broker's
DPI-facing LAG is wired directly back into the test server's own dpi1..N
interfaces -- there is no separate physical DPI appliance in this rig,
in sandbox OR real-hardware mode. Something has to receive traffic on
those interfaces, decide a PCP value, stamp it into the outer VLAN tag,
and send the frame back. That is this file's entire job.

Without this component, every DPI-flow test would time out forever,
because nothing ever echoes the packet back from the DPI side.

WHAT TO IMPLEMENT
-------------------
1. `class DpiStub`

     def __init__(self, engine: PacketEngine, dpi_interfaces: list[str], dpi_vlan_id: int)
         Subscribes (via `engine.get(ifname).subscribe(...)`) on EVERY
         interface in `dpi_interfaces` -- for MVP this is just ["dpi1"],
         but loop over the list rather than hardcoding one interface,
         since a real DPI LAG will have multiple links later.
         `dpi_vlan_id` must match sandbox/broker_sim/broker_config.yaml's
         `dpi_vlan_id` (or, on real hardware, whatever VLAN ID the real
         broker uses to mark DPI-bound traffic).

     async def run(self)
         For each subscribed queue: await a frame, inspect it to find
         which registered DPI-flow test it belongs to (match against the
         predicates registered via `register()` below -- typically keyed
         on the inner packet's src IP, see packet_signature() in
         tests/test_dpi_flow.py), strip the broker's outer VLAN tag,
         re-add it with the PCP bits set
         (`Dot1Q(vlan=dpi_vlan_id, prio=pcp_value)`), and send it back out
         the SAME dpi interface it arrived on.

     def register(self, predicate: Callable[[bytes], bool], pcp_value: int)
         Called once per DPI-flow test at registration time (see
         core/test_runner.py): "when a frame matching this predicate
         arrives, echo it back with this PCP value."

WHY THIS RUNS AS ITS OWN COMPONENT, NOT INSIDE EACH TEST
-----------------------------------------------------------
Multiple DPI-flow tests (PCP 0/1/2/3 -- only PCP=0 in current MVP scope)
all share the same physical DPI interfaces. Demuxing arrivals to the
right test and echoing back is one job, done once, mirroring how a real
DPI engine is one shared component serving the whole broker, not one
engine per flow.

MVP SCOPE NOTE
-----------------
Only PCP=0 is registered for now (mirroring/steering are out of scope).
Write `register()`/`run()` generically -- do not hardcode `pcp_value=0`
anywhere -- so adding PCP 1/2/3 later is purely a matter of registering
more tests, with ZERO changes to this file.

SWITCHING TO REAL HARDWARE
-----------------------------
This file does NOT disappear. Even with real hardware, there is no
separate physical DPI appliance being tested here -- the broker's
DPI-facing LAG is wired directly back into the test server's own NICs,
exactly as in sandbox mode (that's the whole reason dpi1..dpiN exist as
test-server interfaces in topology.yaml in the first place). DpiStub is
what plays the DPI engine's role in BOTH environments. Only the
interface names in topology.yaml change (veth -> real NIC); this file's
logic does not need to change.

(Compare with sandbox/broker_sim/broker_sim.py, which DOES disappear on
real hardware, because that file stands in for the BROKER, and a real
broker is the whole point of testing on real hardware.)
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
