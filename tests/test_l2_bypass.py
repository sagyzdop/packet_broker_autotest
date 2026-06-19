"""tests/test_l2_bypass.py

Verifies the broker passes L2 control-plane protocols (LACP, STP, LLDP, CDP
for MVP -- see protocols/l2_bypass_list.py) straight through from internal
to external without routing them through the DPI engine. No DPI round trip
involved, which makes this the simplest valid BaseTest subclass -- it
isolates whether core/packet_engine.py + core/packet_builder.py +
core/base_test.py are all correct before core/dpi_stub.py's extra
complexity is involved.

`sandbox/broker_sim/broker_sim.py` implements "pass these MACs straight
through" by reading the same protocol list from broker_config.yaml -- if
this test fails against the sandbox, the bug is almost certainly in the
framework code, not the (intentionally trivial) simulated broker.

See CLAUDE.md -> "MVP scope" and "Build order".
"""

from __future__ import annotations

from typing import List, Optional

from core.base_test import BaseTest
from core.matcher import PacketMatcher
from core.packet_builder import build_eth
from core.topology import Pair
from protocols.l2_bypass_list import L2_BYPASS_PROTOCOLS


class L2BypassTest(BaseTest):
    def __init__(self, protocol_name: str, dst_mac: str, ethertype: Optional[int] = None):
        super().__init__()
        self.protocol_name = protocol_name
        self.dst_mac = dst_mac
        self.ethertype = ethertype

    def build_packet(self):
        return build_eth(src_mac=self.pair.internal_mac, dst_mac=self.dst_mac, ethertype=self.ethertype)

    def matcher(self) -> PacketMatcher:
        return PacketMatcher(eth_dst=self.dst_mac, eth_type=self.ethertype)

    def packet_signature(self) -> dict:
        return {"eth_dst": self.dst_mac, "eth_type": self.ethertype}

    def send_interface(self) -> str:
        return self.pair.internal

    def expect_interface(self) -> str:
        return self.pair.external

    def __repr__(self) -> str:
        return f"L2BypassTest({self.protocol_name})"


def build_l2_bypass_tests(pair: Pair, protocol_names: List[str]) -> List[L2BypassTest]:
    by_name = {p["name"]: p for p in L2_BYPASS_PROTOCOLS}
    tests: List[L2BypassTest] = []
    for name in protocol_names:
        if name not in by_name:
            raise ValueError(
                f"unknown L2 bypass protocol '{name}' in config.json -- "
                f"not present in protocols/l2_bypass_list.py"
            )
        proto = by_name[name]
        test = L2BypassTest(protocol_name=name, dst_mac=proto["dst_mac"], ethertype=proto["ethertype"])
        test.pair = pair
        tests.append(test)
    return tests
