# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state: this is a scaffold, not a working app

Every file under `core/`, `tests/`, `api/`, and `protocols/` (except `__init__.py`) is currently a
detailed docstring specification ending in a `# TODO: implement ...` comment — there is no working
code yet. The docstrings are the spec: they describe exact function/class signatures, algorithms,
and the reasoning behind them. When asked to "implement X", read X's docstring in full before
writing anything; it is intentionally written as a precise implementation guide, not a vague
placeholder.

`README.md` is the shared design doc for the whole repo and is the canonical source of truth.
Every file's docstring points back to specific README sections (e.g. "See README.md ->
'Architecture'"). Read README.md fully before implementing anything non-trivial — it covers the
architecture diagram, the MVP scope, sandbox networking, the real-hardware migration story, and a
terminology glossary (PCP, LAG, LAG hash, fd dispatch, netns/veth).

**Always keep the existing module docstrings/comments when implementing a file.** Add real code
below or alongside the spec docstring instead of deleting it — including for minimal/bootstrap
implementations (e.g. just enough to get `docker compose up` running before the real pipeline
exists). If a placeholder differs from the eventual real implementation, say so explicitly in a
comment (e.g. "MINIMAL BOOTSTRAP IMPLEMENTATION — replace once core/X.py exists") rather than
removing the spec it's standing in for.

## What this system does

A packet broker sits between subscriber-facing ("internal") and network-facing ("external")
traffic, forwarding it through a DPI engine that inspects it and signals a decision back to the
broker via PCP bits (the VLAN priority field, repurposed as a signaling channel — see README §6).
This framework tests that pipeline continuously: not a one-shot test run, but a live monitor where
every registered test loops forever (send packet → wait on expected interface → verify → record →
repeat), with a live WebSocket dashboard.

**MVP scope** (see README §2): one internal/external pair, DPI flow with PCP=0 only (no mirroring/
steering), L2 bypass for LACP/STP/LLDP/CDP, and the sandbox environment. Mirroring, the full encap
matrix, LAG hash detection, broadcast/multicast isolation, IP/port/proto bypass, and real export
are explicitly deferred but the codebase is structured so adding them later is additive, not a
rewrite — do not build those parts unless asked.

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

Key design decisions to preserve when implementing:

- **Single process, single event loop.** FastAPI/uvicorn and every test's infinite loop are
  asyncio coroutines in one process. Tests call `state_manager.update(...)` directly — no threads,
  no message queue, no database.
- **`core/dpi_stub.py` is permanent, not sandbox-only.** Something has to play the DPI engine's
  role (receive on DPI interfaces, decide a PCP value, stamp it, send back) whether `dpi1` is a
  sandbox veth or a real NIC.
- **AF_PACKET + asyncio needs the fd dispatcher pattern.** AF_PACKET sockets are blocking fds;
  `core/packet_engine.py` registers them with `loop.add_reader(sock.fileno(), callback)` so the
  event loop only wakes a coroutine when data is actually available. This is the only place this
  pattern should live.
- **Hardware-agnostic by construction.** `core/`, `tests/`, and `api/` must never branch on
  `mode` (sandbox vs hardware) — see README §5. If you find yourself wanting
  `if mode == "sandbox":` inside those directories, something is structured wrong; that's a signal
  to push the difference into `topology.yaml` or `sandbox/` instead.
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

## Sandbox networking (local dev, Mac-friendly)

AF_PACKET is Linux-only, so development happens inside a privileged Docker container (Docker
Desktop on Mac runs a Linux kernel under the hood). The sandbox creates one extra network namespace,
`broker_sim`, connected to the container's default namespace via three veth pairs
(`internal1`/`external1`/`dpi1` ↔ `br_internal1`/`br_external1`/`br_dpi1`). The container's default
namespace plays "test_server" (FastAPI/uvicorn run there, so Docker's normal port mapping works with
no extra routing). `sandbox/broker_sim/broker_sim.py` is a deliberately simple stand-in DUT: it
passes L2-bypass protocols straight through and wraps everything else in an outer VLAN tag
(`dpi_vlan_id` in `broker_config.yaml`) toward the DPI link, stripping it on the way back. It is not
part of the test framework and disappears once real hardware is available.

`sandbox/setup_sandbox.sh` builds this topology at container startup (idempotent); `teardown_
sandbox.sh` tears it down on shutdown via a trap handler in `sandbox/entrypoint.sh`.

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

On real hardware (see README §5): no Docker needed (or a much simpler non-privileged container).
Run `uvicorn api.main:app --host 0.0.0.0 --port 8000` directly with real NIC names in
`topology.yaml`; `sandbox/` becomes entirely unused.

## Implementation order

The README (§9) specifies a strict build order because later files depend on earlier ones being
correct, and each step is testable in isolation against the sandbox before moving on:

1. `core/topology.py` — parse topology.yaml, resolve MACs.
2. `core/packet_builder.py` — `EncapConfig`, `apply_encap()` (bare Ethernet only for MVP),
   `build_eth()`, `serialize()`.
3. `core/packet_engine.py` — `InterfaceHandle`, `InterfaceDispatcher` (fd-registration pattern),
   `PacketEngine`.
4. `core/base_test.py` + `core/matcher.py` — the abstract test contract and field comparison.
5. `tests/test_l2_bypass.py` — first real test, no DPI round trip; if it passes against the
   sandbox, steps 1–4 are correct.
6. `core/dpi_stub.py` — the DPI engine stand-in.
7. `tests/test_dpi_flow.py` (PCP=0 only) — exercises the full round trip through `dpi_stub.py` and
   `broker_sim.py`.
8. `core/state_manager.py` + `core/collision_checker.py` + `core/test_runner.py` — wire
   registration, the collision check, and infinite-loop scheduling together.
9. `api/main.py` + `api/websocket.py` + `api/routes_tests.py` — expose over HTTP/WebSocket, in the
   startup order documented above.
10. `frontend/index.html` — the live dashboard.

Everything else (`tests/test_ip_bypass.py`, `test_isolation.py`, `test_lag_hash.py`,
`test_mirroring.py`, `core/encap_matrix.py`, `api/routes_export.py`, `frontend/test_detail.html`,
`config.html`, `export.html`) is explicitly deferred past MVP — don't implement unless asked.
