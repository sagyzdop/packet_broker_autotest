"""core/packet_builder.py

Turns a logical packet description into raw bytes, and applies the
encapsulation matrix (VLAN/MPLS/EoMPLS stacking) on top of it. This is the
only file that imports Scapy layers for building packets — core/packet_engine.py
never imports Scapy at all, it only deals in raw bytes. Keeping all Scapy
logic confined here means a future swap to a faster packet builder only
touches this file, never the socket/dispatcher code.

See CLAUDE.md -> "Architecture".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from scapy.contrib.mpls import MPLS
from scapy.layers.l2 import Dot1Q, Ether


@dataclass
class EncapConfig:
    vlan_stack: List[int] = field(default_factory=list)
    mpls_stack: List[int] = field(default_factory=list)
    eompls: bool = False
    inner_vlan_stack: List[int] = field(default_factory=list)
    inner_mpls_stack: List[int] = field(default_factory=list)


# Bare Ethernet -- what "smoke" mode in config.json uses, and the only mode
# needed for MVP (see CLAUDE.md "MVP scope").
DEFAULT_ENCAP = EncapConfig()


def apply_encap(pkt, encap: EncapConfig):
    """Wrap `pkt` (a full Ether/... packet) in the VLAN/MPLS layers `encap`
    describes, outermost layer first (encap.vlan_stack[0] ends up directly
    after the Ethernet header). Generic for all stack combinations -- the
    empty-stack case naturally round-trips back to an equivalent frame, no
    special-casing required. core/encap_matrix.py (post-MVP) calls this same
    function directly with non-empty stacks.
    """
    if not pkt.haslayer(Ether):
        raise ValueError("apply_encap() expects a packet with an Ether layer")

    eth = pkt[Ether]
    body = eth.payload

    # Innermost-first: build from the original payload outward so the last
    # layer applied ends up outermost.
    for label in reversed(encap.inner_mpls_stack):
        body = MPLS(label=label) / body
    for vlan in reversed(encap.inner_vlan_stack):
        body = Dot1Q(vlan=vlan) / body

    if encap.eompls:
        # EoMPLS pseudowire: the (possibly inner-tagged) frame becomes the
        # payload of a transport Ethernet header carried over MPLS.
        body = Ether() / body

    for label in reversed(encap.mpls_stack):
        body = MPLS(label=label) / body
    for vlan in reversed(encap.vlan_stack):
        body = Dot1Q(vlan=vlan) / body

    return Ether(src=eth.src, dst=eth.dst, type=eth.type) / body


def build_eth(src_mac: str, dst_mac: str, ethertype: Optional[int] = None) -> Ether:
    kwargs = {"src": src_mac, "dst": dst_mac}
    if ethertype is not None:
        kwargs["type"] = ethertype
    return Ether(**kwargs)


def serialize(pkt) -> bytes:
    return bytes(pkt)
