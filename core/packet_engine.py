"""
core/packet_engine.py
========================
See README.md -> "Architecture" and "Switching to Real Hardware".

WHAT THIS FILE OWNS
-------------------
The ONLY place in the codebase that touches AF_PACKET sockets directly.
Every other module sends/receives packets through the objects this file
exposes -- never opens a socket itself.

WHY IT EXISTS (context)
------------------------
AF_PACKET gives raw, unmodified access to every Ethernet frame on an
interface -- required because tests need to send/receive frames with
spoofed src MACs, reserved multicast dst MACs (LACP/STP/etc.), and
arbitrary VLAN/MPLS stacks that a normal kernel socket would reject or
silently rewrite.

AF_PACKET sockets are BLOCKING file descriptors. Calling .recv() directly
inside an asyncio coroutine would freeze the entire event loop (every
other test included, not just this one). The fix: register each socket's
fd with the event loop via `loop.add_reader(fd, callback)`, so asyncio
only calls `callback` once data is actually waiting -- it never blocks.

WHAT TO IMPLEMENT
-------------------
1. `class InterfaceHandle`
   - Wraps one AF_PACKET socket bound to one interface (e.g. "internal1").
   - `__init__(self, ifname: str)`: open
     socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003)),
     then `.bind((ifname, 0))`.
   - `send(self, raw_bytes: bytes)`: `self._sock.send(raw_bytes)`. Scapy
     packets must already be serialized (via packet_builder.serialize())
     before reaching this method -- this file does not import Scapy.
   - `recv(self) -> bytes`: `self._sock.recv(65535)`.
   - `fileno(self) -> int`: `self._sock.fileno()` -- used by the
     dispatcher to register with the event loop.

2. `class InterfaceDispatcher`
   - One instance per interface. Owns one InterfaceHandle.
   - `start(self, loop)`: `loop.add_reader(handle.fileno(), self._on_data)`.
   - `_on_data(self)`: read available bytes, then:
       a) push a copy into the ring buffer (see core/state_manager.py /
          original spec "Ring Buffer for Captures")
       b) iterate current subscriptions and route the frame to any whose
          predicate matches (see subscribe() below)
   - `subscribe(self, predicate: Callable[[bytes], bool]) -> asyncio.Queue`
     A test calls this ONCE at startup: "wake me when a frame matching
     `predicate` arrives on this interface." `predicate` is normally built
     from packet_signature() (see core/base_test.py). Returns a fresh
     asyncio.Queue the caller awaits on.
   - `unsubscribe(self, queue)`.
   - IMPORTANT: an interface can have MULTIPLE simultaneous subscribers
     (e.g. every DPI interface is watched by core/dpi_stub.py AND by
     whichever DPI-flow test is currently mid-flight). Check every
     subscription on every received frame; deliver to all matches.

3. `class PacketEngine`
   - Built from the parsed topology.yaml (see core/topology.py). Owns one
     InterfaceDispatcher per interface name; `start_all(self, loop)`
     starts them all.
   - `get(self, ifname: str) -> InterfaceDispatcher` -- the lookup every
     other module uses to send/subscribe on a named interface.

EDGE CASES
----------
- An interface name from topology.yaml that doesn't exist on the host
  must fail LOUDLY at startup (name the missing interface in the error),
  not be silently skipped.
- `recv()` returning 0 bytes (interface went down) is non-fatal: log and
  keep the reader registered.
- Two subscriptions matching the same frame should never happen if
  core/collision_checker.py did its job -- but don't crash if it does;
  deliver to both and log a warning.

POST-IMPLEMENTATION NOTE: AF_PACKET and VLAN tags
-----------------------------------------------------
The kernel normalizes every received 802.1Q frame into its "accelerated"
form before delivering it to AF_PACKET listeners: the VLAN tag is stripped
out of the actual bytes a plain recv()/recvfrom() sees and moved into SKB
metadata instead (this is generic core networking-stack behavior, not a
veth-only or sandbox-only quirk -- tools like tcpdump only LOOK like they
see the tag in-band because they separately reconstruct it from that same
metadata). Confirmed by hand with two bare AF_PACKET sockets on an isolated
veth pair, independent of this codebase. core/dpi_stub.py needs the real
VLAN ID to demux DPI-eligible traffic, so InterfaceHandle enables
PACKET_AUXDATA and reconstructs the tag from recvmsg()'s ancillary data
before anything else (matcher.py, dpi_stub.py, etc.) ever sees the bytes --
see InterfaceHandle.recv() below. This applies identically to a real NIC,
not just sandbox veths, so it lives here rather than in sandbox/.

SANDBOX vs REAL HARDWARE
-------------------------
Nothing in this file should ever check `topology.mode`. An interface name
is an interface name -- whether "internal1" is a sandbox veth or a real
10G NIC port is decided entirely by topology.yaml and is invisible here.
This file should not need to change AT ALL when you move to real
hardware -- that is the whole point of this separation.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import struct
from collections import deque
from typing import Callable, Deque, Dict

logger = logging.getLogger(__name__)

ETH_P_ALL = 0x0003

# sockaddr_ll's sll_pkttype value for a frame this socket itself transmitted.
# AF_PACKET sockets see traffic in BOTH directions on a bound interface, so
# without filtering this out, anything that both sends AND subscribes on the
# same interface (core/dpi_stub.py, sending its echo back out the same dpi
# interface it listens on) would re-receive and re-process its own frame --
# see InterfaceHandle.recv().
PACKET_OUTGOING = 4

# Not exposed by Python's socket module by name, but stable across Linux
# versions -- see linux/if_packet.h.
SOL_PACKET = 263
PACKET_AUXDATA = 8
TP_STATUS_VLAN_VALID = 0x10
TP_STATUS_VLAN_TPID_VALID = 0x40
# struct tpacket_auxdata { u32 tp_status, tp_len, tp_snaplen; u16 tp_mac,
# tp_net, tp_vlan_tci, tp_vlan_tpid; } -- no padding, all fields naturally
# aligned.
_AUXDATA_FMT = "=IIIHHHH"
_AUXDATA_LEN = struct.calcsize(_AUXDATA_FMT)


class InterfaceHandle:
    """One AF_PACKET socket bound to one interface."""

    def __init__(self, ifname: str):
        self.ifname = ifname
        self._sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
        try:
            self._sock.bind((ifname, 0))
        except OSError as exc:
            self._sock.close()
            raise RuntimeError(
                f"interface '{ifname}' could not be opened (check topology.yaml): {exc}"
            ) from exc
        # See "POST-IMPLEMENTATION NOTE: AF_PACKET and VLAN tags" above --
        # needed to recover VLAN tags the kernel strips out of the raw bytes.
        self._sock.setsockopt(SOL_PACKET, PACKET_AUXDATA, 1)

    def send(self, raw_bytes: bytes) -> None:
        self._sock.send(raw_bytes)

    def recv(self) -> bytes:
        """Returns the next frame's raw bytes, or b"" if it was this socket's
        OWN outgoing traffic looped back by the kernel (see PACKET_OUTGOING
        above) -- InterfaceDispatcher._on_data() already treats b"" as "nothing
        to dispatch this round" (same handling as a 0-byte real recv()).

        Reinserts the 802.1Q tag the kernel normalizes out of the wire bytes
        (see this module's "AF_PACKET and VLAN tags" note) using PACKET_AUXDATA
        ancillary data, so every consumer downstream (core/matcher.py,
        core/dpi_stub.py, ...) sees the frame exactly as it appeared on the
        wire -- single VLAN tag only, matching this codebase's current MVP
        scope (no QinQ/double-tagging).
        """
        data, ancdata, _flags, addr = self._sock.recvmsg(65535, socket.CMSG_SPACE(_AUXDATA_LEN))
        pkttype = addr[2]
        if pkttype == PACKET_OUTGOING:
            return b""

        for level, cmsg_type, cmsg_data in ancdata:
            if level != SOL_PACKET or cmsg_type != PACKET_AUXDATA:
                continue
            tp_status, _tp_len, _tp_snaplen, _tp_mac, _tp_net, tp_vlan_tci, tp_vlan_tpid = struct.unpack(
                _AUXDATA_FMT, cmsg_data[:_AUXDATA_LEN]
            )
            if not (tp_status & TP_STATUS_VLAN_VALID):
                break
            tpid = tp_vlan_tpid if (tp_status & TP_STATUS_VLAN_TPID_VALID) else 0x8100
            # dst(6) + src(6) already at data[:12]; everything from data[12:]
            # is the original ethertype + payload, with the tag missing.
            data = data[:12] + struct.pack("!HH", tpid, tp_vlan_tci) + data[12:]
            break

        return data

    def fileno(self) -> int:
        return self._sock.fileno()

    def close(self) -> None:
        self._sock.close()


class InterfaceDispatcher:
    """Owns one InterfaceHandle; fans incoming frames out to subscribers and
    a capture ring buffer via the asyncio fd-registration pattern (see
    README.md -> "Architecture")."""

    def __init__(self, ifname: str, capture_buffer: int = 1000):
        self.ifname = ifname
        self.handle = InterfaceHandle(ifname)
        self.ring_buffer: Deque[bytes] = deque(maxlen=capture_buffer)
        self._subscriptions: Dict[asyncio.Queue, Callable[[bytes], bool]] = {}

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        loop.add_reader(self.handle.fileno(), self._on_data)

    def send(self, raw_bytes: bytes) -> None:
        """Passthrough to the underlying InterfaceHandle -- engine.get(ifname)
        is the lookup every other module uses to both send AND subscribe on
        a named interface (see core/base_test.py's run_once())."""
        self.handle.send(raw_bytes)

    def _on_data(self) -> None:
        try:
            data = self.handle.recv()
        except OSError as exc:
            logger.warning("recv() failed on %s: %s", self.ifname, exc)
            return

        if not data:
            logger.debug(
                "recv() returned 0 bytes on %s (interface down, or this was our "
                "own outgoing frame filtered by PACKET_OUTGOING)",
                self.ifname,
            )
            return

        self.ring_buffer.append(data)

        matched = False
        for queue, predicate in list(self._subscriptions.items()):
            try:
                is_match = predicate(data)
            except Exception:
                logger.exception("subscription predicate raised on %s", self.ifname)
                continue
            if is_match:
                if matched:
                    logger.warning(
                        "frame on %s matched more than one subscription "
                        "(core/collision_checker.py should have prevented this)",
                        self.ifname,
                    )
                matched = True
                queue.put_nowait(data)

    def subscribe(self, predicate: Callable[[bytes], bool]) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscriptions[queue] = predicate
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscriptions.pop(queue, None)

    def close(self) -> None:
        self.handle.close()


class PacketEngine:
    """Built from a parsed topology.yaml (core/topology.py). Owns one
    InterfaceDispatcher per interface name."""

    def __init__(self, topology):
        self._dispatchers: Dict[str, InterfaceDispatcher] = {}
        for ifname in topology.all_interface_names():
            self._dispatchers[ifname] = InterfaceDispatcher(
                ifname, capture_buffer=topology.capture_buffer
            )

    def start_all(self, loop: asyncio.AbstractEventLoop) -> None:
        for dispatcher in self._dispatchers.values():
            dispatcher.start(loop)

    def get(self, ifname: str) -> InterfaceDispatcher:
        try:
            return self._dispatchers[ifname]
        except KeyError:
            raise KeyError(f"no interface '{ifname}' configured in topology.yaml") from None

    def close_all(self) -> None:
        """Closes every underlying AF_PACKET socket -- called from api/main.py's
        shutdown hook so fds don't leak across container restarts."""
        for dispatcher in self._dispatchers.values():
            dispatcher.close()
