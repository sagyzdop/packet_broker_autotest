"""
core/base_test.py
====================
See README.md -> "Architecture" and original spec section "Test Case
Architecture".

WHAT THIS FILE OWNS
-------------------
The abstract contract every test case (tests/test_*.py) must implement,
plus the shared "wrap and send, then check" loop body for ONE iteration.
The actual asyncio scheduling of that loop forever lives in
core/test_runner.py, not here -- this file only defines what one
iteration does.

WHAT TO IMPLEMENT
-------------------
1. `class BaseTest(ABC)`

   Overridable attributes (set per-instance, not hardcoded per-subclass):
       encap: EncapConfig = DEFAULT_ENCAP   # from core/packet_builder.py
       pair: Pair = None                     # injected by test_runner.py at registration

   Abstract methods every subclass MUST implement:

     def build_packet(self) -> scapy.Packet
         Builds the INNER packet only -- no encapsulation applied yet.
         e.g. for an L2 bypass test this is just
         Ether(dst=<reserved MAC>, ...).

     def matcher(self) -> PacketMatcher
         Declares which fields of the RECEIVED packet must match for a
         PASS. See core/matcher.py.

     def packet_signature(self) -> dict
         Returns the field/value pairs that make this test's packets
         unique on the wire (e.g. {"eth_dst": "01:80:c2:00:00:02"} for
         LACP). core/collision_checker.py calls this on every registered
         test at startup to catch two tests that would generate
         indistinguishable packets -- fail fast with a clear error
         instead of silently corrupting results later.

     def send_interface(self) -> str
         Which interface name (from topology.yaml) to send build_packet()
         out of, e.g. `self.pair.internal`.

     def expect_interface(self) -> str
         Which interface name to expect the (possibly broker-modified)
         packet to arrive on, e.g. `self.pair.external`.

   Concrete (shared, do not override) methods:

     def wrap(self, pkt) -> scapy.Packet
         `return apply_encap(pkt, self.encap)` -- from
         core/packet_builder.py.

     async def run_once(self, engine: PacketEngine) -> TestResult
         One iteration: build -> wrap -> serialize -> send via
         `engine.get(self.send_interface()).send(...)`; subscribe on
         `expect_interface()` and `await` the resulting queue with a
         timeout; run `self.matcher().match(...)` against whatever
         arrived; return a TestResult(status, latency_ms, failures).
         This single method is reused by core/test_runner.py's infinite
         loop -- see README.md "Architecture" (Operation Mode) for why
         there is no separate "run once" vs "run forever" code path:
         forever is just this method called in a loop with
         `sleep(send_interval_ms)` in between.

2. `@dataclass class TestResult`
       status: Literal["OK", "FAIL", "TIMEOUT"]
       latency_ms: float | None
       failures: list[str]
       timestamp: float

NOTE FOR THE FIRST TEST YOU WRITE (tests/test_l2_bypass.py)
-------------------------------------------------------------
L2 bypass tests are the simplest valid subclass: send_interface() and
expect_interface() are just self.pair.internal / self.pair.external, no
DPI round trip involved. Get this working end-to-end before touching
core/dpi_stub.py -- it is the cleanest way to confirm packet_engine.py
and packet_builder.py are both correct in isolation.
"""

# TODO: implement BaseTest (abstract) and TestResult
