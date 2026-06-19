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

# TODO: implement DpiStub
