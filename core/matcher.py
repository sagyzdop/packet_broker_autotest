"""core/matcher.py

Fast, field-level comparison of a received packet against what a test
expects -- explicitly not a byte-for-byte comparison, since the broker is
allowed to legitimately change some bytes (e.g. strip the outer DPI VLAN
tag) and a byte diff would wrongly flag that as a failure. Each test
declares only the fields it cares about: tests/test_l2_bypass.py checks only
eth_dst/eth_type; tests/test_dpi_flow.py checks ip_src/ip_dst but
deliberately not vlan_stack, since the outer DPI VLAN tag is expected to be
gone by the time the packet reaches `external1`.

See CLAUDE.md -> "Architecture".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from scapy.contrib.mpls import MPLS
from scapy.layers.inet import IP
from scapy.layers.l2 import Dot1Q, Ether


@dataclass
class MatchResult:
    ok: bool
    failures: List[str]


@dataclass
class PacketMatcher:
    eth_src: Optional[str] = None
    eth_dst: Optional[str] = None
    eth_type: Optional[int] = None
    ip_src: Optional[str] = None
    ip_dst: Optional[str] = None
    ip_proto: Optional[int] = None
    vlan_stack: Optional[List[int]] = None
    mpls_stack: Optional[List[int]] = None

    def match(self, pkt) -> MatchResult:
        failures: List[str] = []

        self._check_eth(pkt, failures)
        self._check_ip(pkt, failures)
        self._check_vlan_stack(pkt, failures)
        self._check_mpls_stack(pkt, failures)

        return MatchResult(ok=len(failures) == 0, failures=failures)

    def _check_eth(self, pkt, failures: List[str]) -> None:
        fields = {"src": self.eth_src, "dst": self.eth_dst, "type": self.eth_type}
        if not any(v is not None for v in fields.values()):
            return
        if not pkt.haslayer(Ether):
            for name, expected in fields.items():
                if expected is not None:
                    failures.append(f"eth_{name}: expected {expected!r}, but packet has no Ether layer")
            return
        eth = pkt[Ether]
        for name, expected in fields.items():
            if expected is None:
                continue
            actual = getattr(eth, name)
            if str(actual).lower() != str(expected).lower():
                failures.append(f"eth_{name}: expected {expected!r}, got {actual!r}")

    def _check_ip(self, pkt, failures: List[str]) -> None:
        fields = {"src": self.ip_src, "dst": self.ip_dst, "proto": self.ip_proto}
        if not any(v is not None for v in fields.values()):
            return
        if not pkt.haslayer(IP):
            for name, expected in fields.items():
                if expected is not None:
                    failures.append(f"ip_{name}: expected {expected!r}, but packet has no IP layer")
            return
        ip = pkt[IP]
        for name, expected in fields.items():
            if expected is None:
                continue
            actual = getattr(ip, name)
            if actual != expected:
                failures.append(f"ip_{name}: expected {expected!r}, got {actual!r}")

    def _check_vlan_stack(self, pkt, failures: List[str]) -> None:
        if self.vlan_stack is None:
            return
        actual_stack: List[int] = []
        layer = pkt
        while layer is not None and layer.haslayer(Dot1Q):
            dot1q = layer[Dot1Q]
            actual_stack.append(dot1q.vlan)
            layer = dot1q.payload
        if actual_stack != self.vlan_stack:
            failures.append(f"vlan_stack: expected {self.vlan_stack!r}, got {actual_stack!r}")

    def _check_mpls_stack(self, pkt, failures: List[str]) -> None:
        if self.mpls_stack is None:
            return
        actual_stack: List[int] = []
        layer = pkt
        while layer is not None and layer.haslayer(MPLS):
            mpls = layer[MPLS]
            actual_stack.append(mpls.label)
            layer = mpls.payload
        if actual_stack != self.mpls_stack:
            failures.append(f"mpls_stack: expected {self.mpls_stack!r}, got {actual_stack!r}")
