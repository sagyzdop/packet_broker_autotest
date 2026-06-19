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

SANDBOX vs REAL HARDWARE
-------------------------
Nothing in this file should ever check `topology.mode`. An interface name
is an interface name -- whether "internal1" is a sandbox veth or a real
10G NIC port is decided entirely by topology.yaml and is invisible here.
This file should not need to change AT ALL when you move to real
hardware -- that is the whole point of this separation.
"""

# TODO: implement InterfaceHandle, InterfaceDispatcher, PacketEngine (see docstring above)
