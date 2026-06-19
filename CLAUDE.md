# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this
repository. It is the canonical design doc and spec for the whole project — every module's
docstring points back to a section here instead of repeating the explanation locally.

## Project state

The MVP is implemented and tested end-to-end (sandbox + API + dashboard). See "MVP scope" below
for exactly what that covers. Everything outside MVP scope is left as a docstring-only spec ending
in `# TODO (deferred)`: a precise implementation guide, not a vague placeholder. When asked to
implement one of those files, read its docstring in full first — it describes the exact
function/class shape and the reasoning behind it, written so a developer or an AI agent can pick it
up directly.

**Keep existing module docstrings when implementing a deferred file.** Add real code below or
alongside the spec docstring rather than deleting it. If a placeholder differs from the eventual
real implementation, say so explicitly (e.g. "MINIMAL BOOTSTRAP IMPLEMENTATION — replace once X
exists") rather than silently removing the spec it stands in for.

## What this system does

A packet broker sits between subscriber-facing ("internal") and network-facing ("external")
traffic, forwarding it through a DPI engine that inspects it and signals a decision back to the
broker via PCP bits (the VLAN priority field, repurposed as a signaling channel — see "Terminology"
below). This framework tests that pipeline continuously: not a one-shot test run, but a live monitor
where every registered test loops forever (send packet → wait on expected interface → verify →
record → repeat), with a live WebSocket dashboard.

## MVP scope

**In scope:** one internal/external pair, DPI flow with PCP=0 only (no mirroring/steering), L2
bypass for LACP/STP/LLDP/CDP, and the sandbox environment to develop and test all of the above
without physical hardware.

**Explicitly deferred** (every file is structured so adding these later is additive, not a
rewrite — don't build them unless asked):

| Feature | Owning file(s) | Needs |
|---|---|---|
| Mirroring (PCP=1) / steering (PCP=2/3) | `tests/test_mirroring.py` | More `DpiFlowTest(pcp_value=...)` instances — `core/dpi_stub.py` already supports arbitrary PCP values |
| Full 8192-variant encapsulation matrix | `core/encap_matrix.py` | `core/packet_builder.py`'s `apply_encap()` is already generic; MVP just never calls it with a non-empty stack |
| LAG hash type detection | `tests/test_lag_hash.py` | 2+ links in `topology.yaml`'s `dpi_lag` |
| Broadcast/multicast isolation between pairs | `tests/test_isolation.py` | 2+ pairs in `topology.yaml` |
| IP/port/proto bypass | `tests/test_ip_bypass.py` | Nothing — same shape as L2 bypass, just not built this round |
| Export/reporting beyond a 501 stub | `api/routes_export.py` | Nothing blocking — deferred by choice |
| Config hot-reload (`POST /api/config`) | `api/routes_config.py` | Nothing blocking — deferred by choice; topology is fixed at startup for MVP |
| Dashboard sub-pages (detail/config/export tabs) | `frontend/test_detail.html`, `config.html`, `export.html` | The backing routes above |

## Architecture

```
BROWSER (frontend/index.html) --ws://host/ws/live--> FastAPI app (api/main.py)
                                                         |  websocket.py, routes_tests.py,
                                                         |  routes_config.py, routes_export.py (stub)
                                                         | same asyncio event loop, no IPC
                                core/test_runner.py    — schedules each test's infinite loop as
                                                          an asyncio.Task
                                core/base_test.py      — one test iteration's shared logic
                                core/dpi_stub.py       — plays the DPI engine's role
                                core/state_manager.py  — in-memory results + WS fan-out
                                core/packet_builder.py — Scapy packet construction
                                core/packet_engine.py  — AF_PACKET sockets, fd dispatch
                                         |
                          NETWORK INTERFACES: internal1, external1, dpi1
                          (sandbox: veth pairs; real HW: real NICs)
```

Key design decisions to preserve:

- **Single process, single event loop.** FastAPI/uvicorn and every test's infinite loop are
  asyncio coroutines in one process. Tests call `state_manager.update(...)` directly — no threads,
  no message queue, no database.
- **`core/dpi_stub.py` is permanent, not sandbox-only.** Something has to play the DPI engine's
  role (receive on DPI interfaces, decide a PCP value, stamp it, send back) whether `dpi1` is a
  sandbox veth or a real NIC. There is no separate physical DPI box anywhere in this system.
- **AF_PACKET + asyncio needs the fd dispatcher pattern.** AF_PACKET sockets are blocking fds;
  `core/packet_engine.py` registers them with `loop.add_reader(sock.fileno(), callback)` so the
  event loop only wakes a coroutine when data is actually available — calling `.recv()` directly
  inside a coroutine would freeze every other test. This is the only place this pattern should live.
- **Hardware-agnostic by construction.** `core/`, `tests/`, and `api/` must never branch on `mode`
  (sandbox vs hardware) — see "Switching to real hardware" below. If you find yourself wanting
  `if mode == "sandbox":` inside those directories, something is structured wrong; push the
  difference into `topology.yaml` or `sandbox/` instead.
- **Field-level, not byte-level, packet matching.** `core/matcher.py`'s `PacketMatcher` only checks
  fields a given test explicitly cares about (e.g. `test_l2_bypass.py` checks only `eth_dst`/
  `eth_type`; `test_dpi_flow.py` checks `ip_src`/`ip_dst` but not `vlan_stack`, since the broker is
  expected to strip the outer DPI VLAN tag). A byte diff would wrongly flag legitimate broker
  modifications as failures.

### Startup ordering (enforced in `api/main.py`'s startup hook)

1. Parse `topology.yaml` → build `PacketEngine` → start all `InterfaceDispatcher`s.
2. Construct `DpiStub` over the DPI interfaces, start its `run()` loop.
3. `register_all_tests(...)` in `core/test_runner.py` — includes the collision check
   (`core/collision_checker.py`) against the full test list, failing fast at startup with an error
   naming the two colliding tests.
4. `start_all(...)` — only after steps 1–3 succeed.

Getting this order wrong (e.g. starting tests before `DpiStub` is listening) produces flaky-looking
TIMEOUTs on the first few iterations that are actually a startup race, not a real bug.

## Terminology glossary

**PCP (Priority Code Point)** — 3 bits inside an 802.1Q VLAN tag, normally used for QoS. This
system repurposes them as a signaling channel: the DPI engine sets PCP on the VLAN tag wrapping a
packet to tell the broker what to do with it on the way back (0 = normal, 1 = + mirror,
2 = steering, 3 = steering + mirror). MVP only uses PCP=0.

**fd dispatch** — the asyncio fd-registration pattern described above: `loop.add_reader(fd,
callback)` lets the event loop wake a coroutine only when a blocking AF_PACKET socket actually has
data, without any coroutine blocking.

**LAG (Link Aggregation Group)** — multiple physical links bundled into one logical link
(802.3ad/LACP), for redundancy and bandwidth. The "DPI LAG" is the bundle of links between the
broker and the DPI side. MVP uses a single-link LAG (`dpi1` only).

**LAG hash** — the algorithm a LAG uses to pick which physical link a flow goes out on (2-tuple:
src/dst IP; 4-tuple: + ports; 5-tuple: + protocol). Detecting which one the broker uses requires
varying flow fields and watching which physical link traffic lands on — needs 2+ links, deferred.

**IP/port/proto bypass** — broker rules that skip DPI inspection entirely for traffic matching
certain IP ranges, ports, or protocols (e.g. "never send DNS to DPI"). Simpler than DPI-flow tests:
no DPI round trip, just send-and-verify, like L2 bypass.

**netns / veth pair** — a network namespace is an isolated network stack (own interfaces, routing
table, ARP table), as if it were a separate physical machine. A veth pair is a virtual two-ended
cable; two namespaces connected by one behave like two boxes wired together. See "Sandbox
networking" below.

## Sandbox networking (local dev, Mac-friendly)

AF_PACKET is Linux-only, so development happens inside a privileged Docker container (Docker
Desktop on Mac runs a Linux kernel under the hood). The sandbox creates one extra network namespace,
`broker_sim`, connected to the container's default namespace via three veth pairs
(`internal1`/`external1`/`dpi1` ↔ `br_internal1`/`br_external1`/`br_dpi1`):

```
[container default namespace = "test_server"]      [namespace: broker_sim]
   internal1   <───── veth pair ─────>                  br_internal1
   external1   <───── veth pair ─────>                  br_external1
   dpi1        <───── veth pair ─────>                  br_dpi1

   (FastAPI / uvicorn / the whole                  (sandbox/broker_sim/broker_sim.py
    framework runs HERE)                            runs HERE)
```

The container's default namespace plays "test_server" (FastAPI/uvicorn run there, so Docker's
normal port mapping works with no extra routing). `sandbox/broker_sim/broker_sim.py` is a
deliberately simple stand-in DUT: it passes L2-bypass protocols straight through and wraps
everything else in an outer VLAN tag (`dpi_vlan_id` in `broker_config.yaml`) toward the DPI link,
stripping it on the way back. It is not part of the test framework and disappears once real
hardware is available.

`sandbox/setup_sandbox.sh` builds this topology at container startup (idempotent);
`sandbox/teardown_sandbox.sh` tears it down on shutdown via a trap handler in
`sandbox/entrypoint.sh`.

## Switching to real hardware

This is the part of the design meant to make that switch closer to "change a config file" than
"rewrite the project":

| What changes | What does not change |
|---|---|
| `topology.yaml`: `mode: hardware`, veth names → real NIC names | `core/packet_engine.py` — never branches on `mode`, only opens whatever interface names topology.yaml gives it |
| `sandbox/` directory becomes unused entirely | `core/dpi_stub.py` — still plays the DPI engine's role; the DPI interfaces are still test-server interfaces wired directly to the broker, hardware or not |
| Run `uvicorn api.main:app --host 0.0.0.0 --port 8000` directly on the lab Linux box (or a much simpler, non-privileged container) | `core/packet_builder.py`, `core/base_test.py`, `core/matcher.py`, every file in `tests/`, every file in `api/`, `frontend/` |
| `sandbox/broker_sim/broker_sim.py` is replaced by an actual broker — a real device, doing real forwarding | Nothing in the application layer needs to know the broker is now real |

## Configuration files

- **`topology.yaml`** — interface names (veth or real NIC), pair/LAG groupings, runtime tunables
  (`parallel_limit`, `send_interval_ms`, `capture_buffer`). `mode: sandbox|hardware` is purely
  documentary — no code branches on it.
- **`config.json`** — which test groups are enabled and how (`encap_mode`, L2 protocols, PCP
  variants), plus export/report settings. Also the shape of the body for `GET`/`POST /api/config`.
- **`sandbox/broker_sim/broker_config.yaml`** — the simulated broker's own config (DPI VLAN ID,
  bypassed L2 protocols). Must stay in sync with `protocols/l2_bypass_list.py`, or the sandbox and
  the framework will disagree about what should bypass DPI and tests will fail for reasons unrelated
  to actual bugs.

## Running the project

```bash
docker compose up --build   # builds sandbox container, brings up simulated topology,
                             # starts broker_sim.py, starts FastAPI on :8000
docker compose down         # tears down cleanly via entrypoint.sh's trap handler
```

- Dashboard: `http://localhost:8000/`
- Health check: `http://localhost:8000/health`
- Live events: `ws://localhost:8000/ws/live`
- REST API: `http://localhost:8000/api/tests`, etc.

On real hardware (see "Switching to real hardware" above): no Docker needed (or a much simpler
non-privileged container). Run `uvicorn api.main:app --host 0.0.0.0 --port 8000` directly with real
NIC names in `topology.yaml`; `sandbox/` becomes entirely unused.

## Project structure

```
packet_broker_autotest/
├── README.md
├── docker-compose.yml
├── requirements.txt
├── topology.yaml
├── config.json
│
├── sandbox/
│   ├── Dockerfile
│   ├── setup_sandbox.sh
│   ├── teardown_sandbox.sh
│   ├── entrypoint.sh
│   └── broker_sim/
│       ├── broker_sim.py
│       └── broker_config.yaml
│
├── core/
│   ├── topology.py
│   ├── packet_engine.py
│   ├── packet_builder.py
│   ├── encap_matrix.py             # post-MVP
│   ├── matcher.py
│   ├── base_test.py
│   ├── dpi_stub.py
│   ├── test_runner.py
│   ├── state_manager.py
│   └── collision_checker.py
│
├── tests/
│   ├── test_l2_bypass.py           # MVP
│   ├── test_dpi_flow.py            # MVP (PCP=0 only)
│   ├── test_ip_bypass.py           # deferred
│   ├── test_isolation.py           # deferred
│   ├── test_lag_hash.py            # deferred
│   └── test_mirroring.py           # deferred
│
├── protocols/
│   └── l2_bypass_list.py
│
├── api/
│   ├── main.py
│   ├── websocket.py
│   ├── routes_config.py
│   ├── routes_export.py            # stub (501s) for now
│   └── routes_tests.py
│
└── frontend/
    ├── index.html                  # MVP
    ├── test_detail.html            # deferred
    ├── config.html                 # deferred
    └── export.html                 # deferred
```

## Build order (completed for MVP; reuse the pattern for post-MVP work)

The MVP was built and tested in this order, because each later step depends on earlier ones being
correct, and each step is testable in isolation against the sandbox before moving to the next. Use
the same approach when implementing one of the deferred files above — build it, then test it in
isolation before wiring it into the rest of the system.

1. `core/topology.py` — parse topology.yaml, resolve MACs.
2. `core/packet_builder.py` — `EncapConfig`, `apply_encap()` (bare Ethernet only for MVP),
   `build_eth()`, `serialize()`.
3. `core/packet_engine.py` — `InterfaceHandle`, `InterfaceDispatcher` (the fd-registration
   pattern), `PacketEngine`.
4. `core/base_test.py` + `core/matcher.py` — the abstract test contract and field-comparison logic.
5. `tests/test_l2_bypass.py` — first real test, no DPI round trip; passing against the sandbox
   confirmed steps 1–4 were correct.
6. `core/dpi_stub.py` — the DPI engine stand-in.
7. `tests/test_dpi_flow.py` (PCP=0 only) — exercises the full round trip through `dpi_stub.py` and
   `broker_sim.py`.
8. `core/state_manager.py` + `core/collision_checker.py` + `core/test_runner.py` — registration,
   the collision check, and infinite-loop scheduling.
9. `api/main.py` + `api/websocket.py` + `api/routes_tests.py` — exposed over HTTP/WebSocket, in the
   startup order documented above.
10. `frontend/index.html` — the live dashboard.

## Implementation gotchas (learned the hard way — read before touching AF_PACKET code)

These three issues only showed up against real AF_PACKET sockets in the sandbox, never in
logic-only tests against fakes — keep that in mind when changing `core/packet_engine.py` or
`sandbox/broker_sim/broker_sim.py`: unit tests against fake dispatchers cannot catch this class of
bug, only a real run against the sandbox can.

1. **AF_PACKET sees its own outgoing traffic.** Any component that both sends and subscribes on the
   same interface (e.g. `core/dpi_stub.py` echoing back out the same `dpi1` it listens on) will
   re-receive and re-process its own frame as a "new arrival" unless filtered. Fixed in
   `InterfaceHandle.recv()` by using `recvfrom()` and dropping frames where
   `sll_pkttype == PACKET_OUTGOING`.

2. **The kernel strips VLAN tags from AF_PACKET's raw bytes.** Linux normalizes every received
   802.1Q frame by moving the tag out of the payload into SKB metadata before delivering it to
   AF_PACKET listeners — a plain `recv()` never sees it in-band, even though tools like `tcpdump -e`
   appear to show it (they reconstruct it separately from the same metadata via `PACKET_AUXDATA`).
   This is generic kernel behavior, not a veth/sandbox quirk, and applies identically on real
   hardware. Fixed in `InterfaceHandle.recv()` by opting into `PACKET_AUXDATA` and using
   `recvmsg()` to reconstruct the `Dot1Q` tag from the ancillary `tpacket_auxdata` struct before
   returning the bytes.

3. **A receive-only `scapy.sniff()` socket can't filter its own relayed sends.** Scapy's
   `PACKET_OUTGOING` self-filtering only applies when the same combined socket is used for both
   sending and receiving. `sandbox/broker_sim/broker_sim.py` originally used a receive-only
   `sniff()` socket plus a separate `sendp(iface=...)` socket per interface — the relayed frame had
   no way to be recognized as "our own send," producing an unbounded internal1↔external1 ping-pong
   for any bypassed protocol. Fixed by opening one combined `scapy.arch.linux.L2Socket` per
   interface and passing it to both `sniff(opened_socket=...)` and `sendp(socket=...)`.
