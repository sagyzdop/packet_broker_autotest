# PacketBroker AutoTest Framework

This README is the shared context for every file in this repository. Every
core/, tests/, api/, frontend/, and sandbox/ file contains a comment block
that references a section of this document. Read this once before
implementing anything; refer back to specific sections as the per-file
comments point you to them.

---

## 1. What This System Does

A packet broker sits between subscriber-facing traffic ("internal") and
network-facing traffic ("external"), forwarding it through a DPI engine
that inspects it and marks a decision (via PCP bits — see §6 Glossary) for
the broker to act on. This framework tests that pipeline automatically and
continuously, instead of by hand.

It is not "run a test suite, get a pass/fail report." It is a live monitor:
start it once, and every registered test runs forever in a loop — send a
packet, wait for it on the expected interface, check it, record the
result, repeat. Change the broker's configuration and you see the effect
within seconds on the dashboard, without re-running anything.

---

## 2. MVP Scope

Per current team-lead guidance, this MVP intentionally implements a subset
of the full spec:

**In scope:**
- One internal/external pair, traffic flowing end-to-end within that pair
- DPI flow, PCP=0 only ("normal" forwarding — no mirroring, no steering)
- L2 bypass policies (a handful of protocols: LACP, STP, LLDP, CDP)
- The sandbox environment to develop and test all of the above without
  any physical hardware

**Explicitly deferred (do not build yet, but every file is structured so
this is additive later, not a rewrite):**
- Mirroring (PCP=1) and steering (PCP=2/3) — `tests/test_mirroring.py`
- The full 8192-variant encapsulation matrix — `core/encap_matrix.py`
  (MVP uses "smoke" mode: bare Ethernet only)
- LAG hash type detection — needs 2+ DPI links (`tests/test_lag_hash.py`)
- Broadcast/multicast isolation between pairs — needs 2+ pairs
  (`tests/test_isolation.py`)
- IP/port/proto bypass — `tests/test_ip_bypass.py` (a natural *next* test
  after L2 bypass, same shape, just not in this round)
- Export/reporting beyond a 501 stub — `api/routes_export.py`

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────┐
│                  BROWSER (frontend/)                    │
│        index.html — live dashboard over WebSocket       │
└────────────────────────┬────────────────────────────────┘
                          │ ws://host/ws/live
┌────────────────────────▼────────────────────────────────┐
│              FastAPI app (api/main.py)                  │
│   websocket.py    routes_tests.py    routes_config.py   │
│   routes_export.py (stub for now)                        │
└────────────────────────┬────────────────────────────────┘
                          │ same asyncio event loop, no IPC
┌────────────────────────▼────────────────────────────────┐
│  core/test_runner.py   — schedules each test's infinite  │
│                           loop as an asyncio.Task         │
│  core/base_test.py      — one iteration's logic (shared)  │
│  core/dpi_stub.py       — plays the DPI engine's role      │
│  core/state_manager.py — in-memory results + WS fan-out   │
│  core/packet_builder.py— Scapy packet construction         │
│  core/packet_engine.py — AF_PACKET sockets, dispatch fds   │
└────────────────────────┬────────────────────────────────┘
                          │
┌────────────────────────▼────────────────────────────────┐
│        NETWORK INTERFACES: internal1, external1, dpi1    │
│        (sandbox: veth pairs — see §4. real HW: real NICs)│
└────────────────────────────────────────────────────────────┘
```

**Why one process, one event loop:** FastAPI/uvicorn and every test's
infinite loop run as asyncio coroutines on the same event loop, in the
same process. A test can call `state_manager.update(...)` directly; no
threads, no message queue, no database. This is why "no external DB" in
the original spec is realistic — state is just a Python dict, mutated by
coroutines, read by route handlers.

**The one non-obvious component: the DPI stub.** The original spec's
architecture diagram lists `dpi1..N` as test-server interfaces, directly
wired to the broker — there is no separate physical DPI box anywhere in
this system. That means *something* in the framework has to behave like
the DPI engine: receive traffic on the DPI interfaces, decide a PCP value,
stamp it, and send the frame back. That's `core/dpi_stub.py`. It is not a
sandbox-only convenience — it's a permanent part of the architecture, used
identically whether `dpi1` is a sandbox veth or a real NIC (see §5).

**Why AF_PACKET + asyncio needs the fd dispatcher pattern:** AF_PACKET
sockets are blocking file descriptors. asyncio's event loop is built on
`epoll`; you register a socket's fd with
`loop.add_reader(sock.fileno(), callback)` so the loop calls `callback`
only when data is actually waiting, instead of any coroutine blocking and
freezing every other test. `core/packet_engine.py` is the only place this
happens — see that file's docstring for the dispatcher design.

---

## 4. Sandbox Networking

You're building this on a Mac with no physical broker hardware available
yet. AF_PACKET is Linux-only, so the whole framework needs a Linux
environment regardless — Docker Desktop on Mac already runs one under the
hood, and a **privileged container** gives the framework access to that
kernel's networking, including AF_PACKET and **network namespaces**.

A network namespace is an isolated network stack — its own interfaces,
routing table, ARP table — as if it were a separate physical machine.
Connected with a **veth pair** (a virtual two-ended cable), two namespaces
behave exactly like two boxes wired together.

This project's sandbox uses ONE extra namespace, `broker_sim`, to play the
role of the broker (DUT). The container's own default namespace plays the
role of the test server — this is deliberate: it means uvicorn/FastAPI
(running in the default namespace) is reachable through Docker's normal
port mapping with no extra routing tricks.

```
[container default namespace = "test_server"]      [namespace: broker_sim]
   internal1   <───── veth pair ─────>                  br_internal1
   external1   <───── veth pair ─────>                  br_external1
   dpi1        <───── veth pair ─────>                  br_dpi1

   (FastAPI / uvicorn / the whole                  (sandbox/broker_sim/broker_sim.py
    framework runs HERE)                            runs HERE)
```

`sandbox/setup_sandbox.sh` creates this at container startup;
`sandbox/teardown_sandbox.sh` tears it down on shutdown.
`sandbox/broker_sim/broker_sim.py` is a deliberately simple Python script
that:
- Passes L2 bypass protocols straight through both directions, unmodified
- Wraps everything else in an outer VLAN tag (`dpi_vlan_id` in
  `broker_config.yaml`) and forwards it to the DPI-facing link
- Strips that VLAN tag from whatever comes back on the DPI link and
  forwards it out external — completing the round trip

It is a stand-in for the real broker. It is **not** part of the test
framework and disappears entirely once you have real hardware.

---

## 5. Switching to Real Hardware

This is the part of the design meant to make that switch closer to
"change a config file" than "rewrite the project":

| What changes | What does not change |
|---|---|
| `topology.yaml`: `mode: hardware`, veth names → real NIC names | `core/packet_engine.py` — never branches on `mode`, only opens whatever interface names topology.yaml gives it |
| `sandbox/` directory becomes unused entirely | `core/dpi_stub.py` — still plays the DPI engine's role; the DPI interfaces are still test-server interfaces wired directly to the broker, hardware or not |
| You run `uvicorn api.main:app --host 0.0.0.0 --port 8000` directly on the lab Linux box (or a much simpler, non-privileged container) | `core/packet_builder.py`, `core/base_test.py`, `core/matcher.py`, every file in `tests/`, every file in `api/`, `frontend/` |
| `sandbox/broker_sim/broker_sim.py` is replaced by an actual broker — a real device, doing real forwarding | Nothing in the application layer needs to know the broker is now real |

If you ever find yourself wanting to write `if mode == "sandbox":` inside
`core/` or `tests/`, that's a signal something is structured wrong —
those files are supposed to be hardware-agnostic by construction.

---

## 6. Terminology Glossary

**PCP (Priority Code Point)** — 3 bits inside an 802.1Q VLAN tag, normally
used for QoS. This system repurposes them as a signaling channel: the DPI
engine sets PCP on the VLAN tag wrapping a packet to tell the broker what
to do with it on the way back (0 = normal, 1 = + mirror, 2 = steering,
3 = steering + mirror). MVP only uses PCP=0.

**File descriptor (fd)** — the integer handle the Linux kernel uses to
refer to an open socket (or file, or pipe). asyncio's event loop watches
fds via `epoll`; registering a socket's fd with `loop.add_reader()` lets
the event loop wake a coroutine only when data is actually available,
without any coroutine blocking.

**LAG (Link Aggregation Group)** — multiple physical links bundled into
one logical link (802.3ad/LACP), for redundancy and bandwidth. The
"DPI LAG" is the bundle of links between the broker and the DPI side.
MVP uses a single-link LAG (`dpi1` only).

**LAG hash** — the algorithm a LAG uses to pick which physical link a flow
goes out on (2-tuple: src/dst IP; 4-tuple: + ports; 5-tuple: + protocol).
Detecting which one the broker uses requires varying flow fields and
watching which physical link traffic lands on — needs 2+ links, deferred
past MVP.

**IP/port/proto bypass** — broker rules that skip DPI inspection entirely
for traffic matching certain IP ranges, ports, or protocols (e.g. "never
send DNS to DPI"). Simpler than DPI-flow tests: no DPI round trip, just
send-and-verify, like L2 bypass. Deferred past MVP, but a natural next
test once L2 bypass works.

**Network namespace / veth pair** — see §4 above.

---

## 7. Configuration Files

**`topology.yaml`** — interface names (sandbox veth or real NIC),
pair/LAG groupings, and a few runtime tunables (`parallel_limit`,
`send_interval_ms`, `capture_buffer`). `mode: sandbox|hardware` is purely
documentary/logging — no code branches on it (see §5).

**`config.json`** — which test groups are enabled and how (e.g.
`encap_mode: smoke`, which L2 protocols to test, which PCP variants),
plus export/report settings (not functional yet). This is also the shape
of the body for `GET`/`POST /api/config`.

**`sandbox/broker_sim/broker_config.yaml`** — the simulated broker's own
config: which VLAN ID it uses for DPI round trips, which L2 protocols it
bypasses. Must stay in sync with `protocols/l2_bypass_list.py`, or the
sandbox and the framework will disagree about what should bypass DPI.

---

## 8. Running the Project

```bash
`docker compose up --build
````

This builds the sandbox container, brings up the simulated broker topology,
starts `broker_sim.py`, and starts the FastAPI app on `http://localhost:8000`.

- Dashboard: `http://localhost:8000/`
- Health check: `http://localhost:8000/health`
- Live events: `ws://localhost:8000/ws/live`
- REST API: `http://localhost:8000/api/tests`, etc.

```bash
docker compose down
```

Tears the container down; `sandbox/entrypoint.sh`'s trap handler runs
`teardown_sandbox.sh` first so the next `up` starts clean.

---

## 9. Implementation Roadmap

Build in this order — each step is testable in isolation against the
sandbox before moving to the next:

1. **`core/topology.py`** — parse topology.yaml, resolve MACs. Needed by
   everything else.
2. **`core/packet_builder.py`** — `EncapConfig`, `apply_encap()` (bare
   Ethernet path only for now), `build_eth()`, `serialize()`.
3. **`core/packet_engine.py`** — `InterfaceHandle`, `InterfaceDispatcher`
   (the fd-registration pattern), `PacketEngine`.
4. **`core/base_test.py` + `core/matcher.py`** — the abstract contract and
   field-comparison logic.
5. **`tests/test_l2_bypass.py`** — your first real test. No DPI round
   trip. If this passes against the sandbox, steps 1–4 are correct.
6. **`core/dpi_stub.py`** — the DPI engine stand-in.
7. **`tests/test_dpi_flow.py`** (PCP=0 only) — exercises the full round
   trip through `dpi_stub.py` and `broker_sim.py`.
8. **`core/state_manager.py` + `core/collision_checker.py` +
   `core/test_runner.py`** — wire registration, the collision check, and
   the infinite-loop scheduling together.
9. **`api/main.py` + `api/websocket.py` + `api/routes_tests.py`** —
   expose it all over HTTP/WebSocket, in the exact startup order
   documented in `core/test_runner.py` and `api/main.py`.
10. **`frontend/index.html`** — the live dashboard.

Everything else (`tests/test_ip_bypass.py`, `test_isolation.py`,
`test_lag_hash.py`, `test_mirroring.py`, `core/encap_matrix.py`,
`api/routes_export.py`, the other frontend pages) is explicitly deferred
— see §2.

---

## 10. Project Structure

```
packet_broker_autotest/
├── README.md                       # this file
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
