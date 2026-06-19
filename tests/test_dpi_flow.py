"""
tests/test_dpi_flow.py
=========================
See README.md -> "MVP Scope" and "The DPI Stub". Original spec section
"DPI Flow (Main Scenario)".

WHAT THIS FILE OWNS
-------------------
Verifies the main scenario: a packet sent from internal goes through the
broker -> DPI round trip (core/dpi_stub.py plays the DPI engine's role,
see that file's docstring) -> arrives on external unchanged in its
meaningful fields.

MVP SCOPE: only `dpi_flow_pcp0` (PCP=0, "normal" forwarding). The
pcp1/pcp2/pcp3 variants (mirroring/steering) are deferred -- see
README.md "MVP Scope" -- but follow the SAME class shape below so adding
them later is just adding more pcp_value instances, not new code.

WHAT TO IMPLEMENT
-------------------
1. `class DpiFlowTest(BaseTest)`

     def __init__(self, pcp_value: int = 0):
         self.pcp_value = pcp_value

     def build_packet(self) -> scapy.Packet
         A simple Ether/IP/UDP packet:
         `Ether(src=<pair internal MAC>) /
         IP(src=<this test's assigned src IP, from topology.yaml's
         ip_base>, dst=<arbitrary test dst IP>) / UDP(...)`.
         Must NOT match any L2 bypass dst MAC -- it needs to be "normal"
         traffic the broker treats as DPI-eligible.

     def matcher(self) -> PacketMatcher
         `PacketMatcher(ip_src=..., ip_dst=...)` -- verifies the inner IP
         packet survives the broker's VLAN add/strip + core/dpi_stub.py's
         PCP-stamping round trip unchanged. Do NOT check vlan_stack here:
         by the time the packet reaches external1, the broker should have
         stripped the outer DPI VLAN tag entirely (see
         sandbox/broker_sim/broker_sim.py's handle_dpi()).

     def packet_signature(self) -> dict
         `{"ip_src": <this test's assigned src IP>}` -- must be unique
         across all DPI-flow tests AND distinct from any future IP-bypass
         test signature (tests/test_ip_bypass.py, deferred for now).

     def send_interface(self) -> str: return self.pair.internal
     def expect_interface(self) -> str: return self.pair.external

2. Registration with the DPI stub: when this test is registered (see
   core/test_runner.register_all_tests()), it must ALSO call
   `dpi_stub.register(predicate, self.pcp_value)` (see core/dpi_stub.py)
   so the stub knows to echo this test's packets back with the right
   PCP. Keep this wiring in ONE place (test_runner.py is the natural
   spot) -- don't duplicate it inside this class.

VERIFYING AGAINST THE SANDBOX
--------------------------------
sandbox/broker_sim/broker_sim.py's handle_internal() adds the outer VLAN
(dpi_vlan_id from broker_config.yaml) to anything that isn't an L2-bypass
MAC, and handle_dpi() strips it on the way back. core/dpi_stub.py is what
sits "in front of" that strip step from the framework's side -- make sure
the VLAN ID it re-adds before echoing matches dpi_vlan_id exactly, or
broker_sim.py won't recognize the echoed frame as DPI-return traffic and
this test will TIMEOUT instead of FAIL (a useful distinction when
debugging: TIMEOUT here usually means a VLAN ID or interface-naming
mismatch, not a logic bug in the test itself).
"""

from __future__ import annotations

import ipaddress

from scapy.layers.inet import IP, UDP

from core.base_test import BaseTest
from core.matcher import PacketMatcher
from core.packet_builder import build_eth

# Reserve .1-.9 of ip_base for infra-style addresses; PCP variants 0-3 each
# get their own deterministic, collision-free src IP starting at .10.
SRC_IP_OFFSET = 10
DST_IP_OFFSET = 200


class DpiFlowTest(BaseTest):
    # Overridable, not hardcoded -- injected by core/test_runner.py at
    # registration time alongside `pair` (see core/base_test.py), since this
    # test needs topology.yaml's ip_base to compute its assigned IPs.
    ip_base = "10.0.0.0/24"

    def __init__(self, pcp_value: int = 0):
        super().__init__()
        self.pcp_value = pcp_value
        self.ip_base = DpiFlowTest.ip_base

    def _src_ip(self) -> str:
        network = ipaddress.ip_network(self.ip_base, strict=False)
        return str(network.network_address + SRC_IP_OFFSET + self.pcp_value)

    def _dst_ip(self) -> str:
        network = ipaddress.ip_network(self.ip_base, strict=False)
        return str(network.network_address + DST_IP_OFFSET)

    def build_packet(self):
        eth = build_eth(src_mac=self.pair.internal_mac, dst_mac=self.pair.external_mac)
        return eth / IP(src=self._src_ip(), dst=self._dst_ip()) / UDP(sport=12345, dport=54321)

    def matcher(self) -> PacketMatcher:
        return PacketMatcher(ip_src=self._src_ip(), ip_dst=self._dst_ip())

    def packet_signature(self) -> dict:
        return {"ip_src": self._src_ip()}

    def send_interface(self) -> str:
        return self.pair.internal

    def expect_interface(self) -> str:
        return self.pair.external

    def __repr__(self) -> str:
        return f"DpiFlowTest(pcp={self.pcp_value})"
