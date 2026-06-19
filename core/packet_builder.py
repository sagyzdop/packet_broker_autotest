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

# TODO: implement EncapConfig, apply_encap(), build_eth(), serialize()
