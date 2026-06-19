"""tests/test_dpi_flow.py

Verifies the main scenario: a packet sent from internal goes through the
broker -> DPI round trip (core/dpi_stub.py plays the DPI engine's role) ->
arrives on external unchanged in its meaningful fields. MVP scope: only
PCP=0 ("normal" forwarding) -- the pcp1/pcp2/pcp3 variants (mirroring/
steering) are deferred, but `DpiFlowTest` already takes `pcp_value` as a
constructor arg, so adding them later is just registering more instances,
not new code.

Registration wiring: when a `DpiFlowTest` is registered (see
core/test_runner.register_all_tests()), it must also call
`dpi_stub.register(predicate, self.pcp_value)` so the stub knows to echo
this test's packets back with the right PCP. That wiring lives in
test_runner.py only -- don't duplicate it here.

`sandbox/broker_sim/broker_sim.py`'s handle_internal() adds the outer VLAN
(dpi_vlan_id from broker_config.yaml) to anything that isn't an L2-bypass
MAC, and handle_dpi() strips it on the way back; core/dpi_stub.py's echoed
VLAN ID must match dpi_vlan_id exactly, or broker_sim.py won't recognize the
echo as DPI-return traffic and this test TIMEOUTs instead of FAILs (a useful
distinction when debugging: TIMEOUT here usually means a VLAN ID or
interface-naming mismatch, not a logic bug in the test itself).

See CLAUDE.md -> "MVP scope".
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
