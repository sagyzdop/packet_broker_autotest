"""
tests/test_l2_bypass.py
==========================
See README.md -> "MVP Scope" and "Implementation Roadmap". Original spec
section "L2 Bypass (>=50 Protocols)".

WHAT THIS FILE OWNS
-------------------
Verifies the broker passes L2 control-plane protocols (LACP, STP, LLDP,
CDP for MVP -- see protocols/l2_bypass_list.py) straight through from
internal to external WITHOUT routing them through the DPI engine.

THIS IS THE RECOMMENDED FIRST TEST TO IMPLEMENT (see README.md
"Implementation Roadmap"). It has no DPI round trip, so it isolates
whether core/packet_engine.py + core/packet_builder.py + core/base_test.py
are all correct before core/dpi_stub.py's extra complexity is involved.

WHAT TO IMPLEMENT
-------------------
1. `class L2BypassTest(BaseTest)` -- one instance per protocol.

     def __init__(self, protocol_name: str, dst_mac: str, ethertype: int | None = None):
         store these on self; consumed by the methods below.

     def build_packet(self) -> scapy.Packet
         `Ether(src=<this pair's internal MAC>, dst=self.dst_mac,
         type=self.ethertype or default)`. Payload content doesn't matter
         for these protocols -- a minimal/empty payload is fine.

     def matcher(self) -> PacketMatcher
         `PacketMatcher(eth_dst=self.dst_mac, eth_type=self.ethertype)` --
         we only care that the reserved dst MAC and ethertype survive
         unchanged on the way out external1.

     def packet_signature(self) -> dict
         `{"eth_dst": self.dst_mac, "eth_type": self.ethertype}` -- must
         be unique vs every other registered test; checked by
         core/collision_checker.py at startup.

     def send_interface(self) -> str: return self.pair.internal
     def expect_interface(self) -> str: return self.pair.external

2. A factory function, e.g.
   `def build_l2_bypass_tests(pair, protocol_list) -> list[L2BypassTest]`,
   that reads `protocols/l2_bypass_list.py` filtered by config.json's
   `tests.l2_bypass.protocols` (see README.md "Configuration Files") and
   instantiates one L2BypassTest per protocol name. core/test_runner.py's
   `register_all_tests()` calls this at startup.

VERIFYING AGAINST THE SANDBOX
--------------------------------
sandbox/broker_sim/broker_sim.py already implements "pass these MACs
straight through" by reading the SAME protocol list from
broker_config.yaml. If this test fails against the sandbox, the bug is
almost certainly in your framework code, not the (intentionally trivial)
simulated broker -- that is the entire point of having the sandbox match
this test's expectations exactly.
"""

# TODO: implement L2BypassTest and build_l2_bypass_tests()
