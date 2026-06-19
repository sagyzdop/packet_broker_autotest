"""
core/topology.py
Loads and validates topology.yaml, resolves each interface's real MAC
address at startup (read /sys/class/net/<ifname>/address), and exposes a
`Pair` object (internal/external interface names + resolved MACs) per
configured pair. See README.md -> "Configuration Files". Implement this
before core/packet_engine.py needs it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import yaml

MAC_SYSFS_PATH = "/sys/class/net/{ifname}/address"


@dataclass
class Pair:
    internal: str
    external: str
    internal_mac: str
    external_mac: str


@dataclass
class Topology:
    mode: str
    pairs: List[Pair]
    dpi_lag: List[str]
    dpi_macs: Dict[str, str]
    mirroring_lag: List[str]
    steering_lag: List[str]
    ip_base: str
    parallel_limit: int
    send_interval_ms: int
    capture_buffer: int

    def all_interface_names(self) -> List[str]:
        """Every interface name PacketEngine needs to open a socket on."""
        names: List[str] = []
        for pair in self.pairs:
            names.append(pair.internal)
            names.append(pair.external)
        names.extend(self.dpi_lag)
        names.extend(self.mirroring_lag)
        names.extend(self.steering_lag)
        return names


def resolve_mac(ifname: str) -> str:
    path = MAC_SYSFS_PATH.format(ifname=ifname)
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        raise RuntimeError(
            f"interface '{ifname}' not found ({path} does not exist) -- "
            f"check topology.yaml against the interfaces actually present on this host"
        ) from None


def load_topology(path: str = "topology.yaml") -> Topology:
    with open(path) as f:
        raw = yaml.safe_load(f)

    interfaces = raw["interfaces"]

    pairs: List[Pair] = []
    for p in interfaces["pairs"]:
        internal = p["internal"]
        external = p["external"]
        pairs.append(
            Pair(
                internal=internal,
                external=external,
                internal_mac=resolve_mac(internal),
                external_mac=resolve_mac(external),
            )
        )

    dpi_lag = list(interfaces.get("dpi_lag", []))
    dpi_macs = {ifname: resolve_mac(ifname) for ifname in dpi_lag}

    # Not implemented yet (see README.md "MVP Scope") -- expected empty for MVP,
    # but resolved the same way as everything else if ever populated.
    mirroring_lag = list(interfaces.get("mirroring_lag", []))
    steering_lag = list(interfaces.get("steering_lag", []))

    return Topology(
        mode=raw.get("mode", "sandbox"),
        pairs=pairs,
        dpi_lag=dpi_lag,
        dpi_macs=dpi_macs,
        mirroring_lag=mirroring_lag,
        steering_lag=steering_lag,
        ip_base=raw.get("ip_base", "10.0.0.0/24"),
        parallel_limit=raw.get("parallel_limit", 10),
        send_interval_ms=raw.get("send_interval_ms", 1000),
        capture_buffer=raw.get("capture_buffer", 1000),
    )
