#!/usr/bin/env python3
"""sandbox/broker_sim/broker_sim.py

A deliberately simple stand-in for the real packet broker (the DUT). Runs
inside the `broker_sim` network namespace (started by sandbox/entrypoint.sh)
and reproduces, in software, the minimal behavior the MVP test framework
expects from the real device:

  1. L2 control-plane protocols listed in broker_config.yaml are passed
     straight through between internal and external, in both directions,
     completely unmodified ("bypass").
  2. Everything else arriving on the internal side is treated as
     DPI-eligible: wrap it in the outer VLAN tag (dpi_vlan_id) and send it
     out the DPI-facing link.
  3. Whatever comes back on the DPI-facing link (core/dpi_stub.py echoes it
     back with PCP set) has that outer VLAN tag stripped and is forwarded
     out the external side, completing the round trip.

This file does not exist when real hardware is used -- on real hardware
there is a real broker performing this role, wired directly to the test
server's same internal1/external1/dpi1 interfaces. It is intentionally
simplistic: it does not implement PCP=1/2/3 (mirroring/steering) handling,
matching current MVP scope.

See CLAUDE.md -> "Sandbox networking" and "Switching to real hardware".
"""

import yaml
from threading import Thread
from scapy.all import sniff, sendp, Ether, Dot1Q
from scapy.arch.linux import L2Socket

CONFIG_PATH = "sandbox/broker_sim/broker_config.yaml"

IFACE_INTERNAL = "br_internal1"
IFACE_EXTERNAL = "br_external1"
IFACE_DPI = "br_dpi1"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def is_l2_bypass(pkt, bypass_macs: set) -> bool:
    return pkt.haslayer(Ether) and pkt[Ether].dst.lower() in bypass_macs


def make_handlers(dpi_vlan_id: int, bypass_macs: set, socks: dict):
    # NOTE ON socks: each handler sends through the SAME L2Socket its
    # corresponding sniff() call below reads from (see main()), not a fresh
    # sendp(iface=...) socket. scapy's default sniff() opens a receive-only
    # socket (self.outs = None), which disables its own built-in
    # PACKET_OUTGOING filter -- so a plain sendp(iface=...) call's frame would
    # loop straight back into this same handler as a "new" arrival, and for
    # L2-bypass MACs (which bounce internal <-> external unconditionally)
    # that turns into an unbounded amplifying ping-pong between the two
    # threads below. Sharing one combined L2Socket per interface (self.outs
    # = self.ins) makes scapy's existing self-filtering apply, exactly
    # mirroring the PACKET_OUTGOING fix in core/packet_engine.py.
    def handle_internal(pkt):
        if is_l2_bypass(pkt, bypass_macs):
            sendp(pkt, socket=socks[IFACE_EXTERNAL], verbose=False)
            return
        # DPI-eligible traffic: add the outer VLAN tag, forward to the DPI link.
        tagged = Ether(src=pkt[Ether].src, dst=pkt[Ether].dst) / \
            Dot1Q(vlan=dpi_vlan_id) / pkt[Ether].payload
        sendp(tagged, socket=socks[IFACE_DPI], verbose=False)

    def handle_external(pkt):
        # Reverse direction for L2 bypass protocols only (MVP does not send
        # DPI-eligible traffic from external -> internal).
        if is_l2_bypass(pkt, bypass_macs):
            sendp(pkt, socket=socks[IFACE_INTERNAL], verbose=False)

    def handle_dpi(pkt):
        if pkt.haslayer(Dot1Q) and pkt[Dot1Q].vlan == dpi_vlan_id:
            inner = Ether(src=pkt[Ether].src, dst=pkt[Ether].dst) / pkt[Dot1Q].payload
            sendp(inner, socket=socks[IFACE_EXTERNAL], verbose=False)

    return handle_internal, handle_external, handle_dpi


def main():
    config = load_config()
    dpi_vlan_id = config["dpi_vlan_id"]
    bypass_macs = {p["dst_mac"].lower() for p in config["bypass_rules"]["l2_protocols"]}

    print(f"[broker_sim] dpi_vlan_id={dpi_vlan_id}")
    print(f"[broker_sim] l2 bypass dst MACs={sorted(bypass_macs)}")

    # One combined send+recv L2Socket per interface -- see make_handlers()'s
    # note on why this replaces separate sniff()/sendp(iface=...) sockets.
    socks = {
        IFACE_INTERNAL: L2Socket(iface=IFACE_INTERNAL),
        IFACE_EXTERNAL: L2Socket(iface=IFACE_EXTERNAL),
        IFACE_DPI: L2Socket(iface=IFACE_DPI),
    }

    handle_internal, handle_external, handle_dpi = make_handlers(dpi_vlan_id, bypass_macs, socks)

    Thread(target=sniff, kwargs=dict(opened_socket=socks[IFACE_INTERNAL], prn=handle_internal, store=False), daemon=True).start()
    Thread(target=sniff, kwargs=dict(opened_socket=socks[IFACE_EXTERNAL], prn=handle_external, store=False), daemon=True).start()

    print("[broker_sim] Listening on br_internal1, br_external1, br_dpi1 ...")
    sniff(opened_socket=socks[IFACE_DPI], prn=handle_dpi, store=False)


if __name__ == "__main__":
    main()
