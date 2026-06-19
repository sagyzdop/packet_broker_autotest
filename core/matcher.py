"""
core/matcher.py
==================
See README.md -> "Architecture" and original spec section "PacketMatcher
-- Fast Packet Verification".

WHAT THIS FILE OWNS
-------------------
Fast, FIELD-LEVEL comparison of a received packet against what a test
expects -- explicitly NOT a byte-for-byte comparison (the broker is
allowed to legitimately change some bytes, e.g. strip the outer DPI VLAN
tag -- a byte diff would wrongly flag that as a failure).

WHAT TO IMPLEMENT
-------------------
1. `@dataclass class MatchResult`
       ok: bool
       failures: list[str]

2. `@dataclass class PacketMatcher`
       eth_src: str | None = None     # None = field is not checked
       eth_dst: str | None = None
       eth_type: int | None = None
       ip_src: str | None = None
       ip_dst: str | None = None
       ip_proto: int | None = None
       vlan_stack: list[int] | None = None
       mpls_stack: list[int] | None = None

       def match(self, pkt) -> MatchResult
           For every non-None attribute on self, compare against the
           corresponding field on the parsed Scapy packet (`pkt[Ether].src`,
           `pkt[IP].dst`, etc.). If an expected layer is simply missing
           (e.g. checking ip_dst on a packet with no IP layer), record
           that as a failure with a clear message -- don't raise. Collect
           ALL mismatches, don't short-circuit on the first one; failure
           reports are far more useful with the complete list. Return
           `MatchResult(ok=len(failures) == 0, failures=failures)`.

WHY FIELD-LEVEL, NOT BYTE-LEVEL
---------------------------------
Each test declares only the fields IT cares about. tests/test_l2_bypass.py
only checks eth_dst + eth_type survive unchanged; it doesn't care about
anything else in the frame. tests/test_dpi_flow.py checks ip_src/ip_dst
survive the broker's VLAN add/strip round trip, but deliberately does NOT
check vlan_stack, since the outer DPI VLAN tag is expected to be gone by
the time the packet reaches `external1`.
"""

# TODO: implement MatchResult and PacketMatcher
