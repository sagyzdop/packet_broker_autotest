"""
core/packet_builder.py
=========================
See README.md -> "Architecture" and original spec section "Encapsulation
Matrix".

WHAT THIS FILE OWNS
-------------------
Turning a logical packet description into raw bytes, and applying the
encapsulation matrix (VLAN/MPLS/EoMPLS stacking) on top of it. This is the
only file that imports Scapy LAYERS for building packets. core/packet_engine.py
never imports Scapy at all -- it only deals in raw bytes.

WHAT TO IMPLEMENT
-------------------
1. `@dataclass class EncapConfig` (mirrors the original spec's dataclass):
       vlan_stack: List[int] = field(default_factory=list)
       mpls_stack: List[int] = field(default_factory=list)
       eompls: bool = False
       inner_vlan_stack: List[int] = field(default_factory=list)
       inner_mpls_stack: List[int] = field(default_factory=list)

   Module-level presets, at minimum:
       DEFAULT_ENCAP = EncapConfig()   # bare Ethernet -- this is what
                                        # "smoke" mode in config.json uses,
                                        # and the only mode needed for MVP.

2. `def apply_encap(pkt, encap: EncapConfig)`
   - Wraps `pkt` (already a full Ether/IP/... Scapy packet) with the
     VLAN/MPLS layers `encap` describes, outermost first.
   - For MVP you only need the empty-stack case to behave correctly
     (return pkt unchanged) -- but write the function generically now,
     since core/encap_matrix.py (post-MVP, the full 8192-variant matrix)
     will call this same function directly later. Don't special-case
     "MVP" inside this function's logic.
   - VLAN: `scapy.layers.l2.Dot1Q`. MPLS:
     `from scapy.contrib.mpls import MPLS` (contrib layers need an
     explicit import, unlike the standard layers).

3. `def build_eth(src_mac: str, dst_mac: str, ethertype: int | None = None)`
   Thin helper so test files don't repeat the same Scapy boilerplate.

4. `def serialize(pkt) -> bytes`
   Just `bytes(pkt)`. Exists so packet_engine.py (and everything else)
   never has to import Scapy directly -- only this module does.
   core/packet_engine.py's InterfaceHandle.send() expects the bytes this
   function returns, not a Scapy object.

WHY THIS SEPARATION FROM packet_engine.py MATTERS
---------------------------------------------------
packet_engine.py is the part you'd touch least if you ever need to
optimize for raw speed (e.g. swap Scapy for a faster builder, or move
toward something like the DPDK work you've done elsewhere). Keeping all
Scapy logic confined to this one file means a future rewrite only touches
this file, never the socket/dispatcher code.
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
# needed for MVP (see README.md "MVP Scope").
DEFAULT_ENCAP = EncapConfig()


def apply_encap(pkt, encap: EncapConfig):
    """Wrap `pkt` (a full Ether/... packet) in the VLAN/MPLS layers `encap`
    describes, outermost layer first (encap.vlan_stack[0] ends up directly
    after the Ethernet header). Generic for all stack combinations -- the
    empty-stack case naturally round-trips back to an equivalent frame, no
    special-casing required.
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
