"""
core/topology.py
Loads and validates topology.yaml, resolves each interface's real MAC
address at startup (read /sys/class/net/<ifname>/address), and exposes a
`Pair` object (internal/external interface names + resolved MACs) per
configured pair. See README.md -> "Configuration Files". Implement this
before core/packet_engine.py needs it.
"""
# TODO
