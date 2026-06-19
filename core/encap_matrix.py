"""core/encap_matrix.py

Generates the full encapsulation-variant EncapConfig matrix (VLAN/MPLS/EoMPLS
stack combinations, layered via core/packet_builder.py's `apply_encap()`,
which is already written generically to support this). Not needed for
MVP -- config.json's "smoke" encap_mode (bare Ethernet only, see
DEFAULT_ENCAP) is sufficient for now.

See CLAUDE.md -> "MVP scope".
"""
# TODO (deferred -- implement when scope expands past MVP)
