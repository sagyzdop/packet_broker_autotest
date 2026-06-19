# packet_broker_autotest

A continuous test framework for a packet broker / DPI pipeline. It doesn't run once and exit — it
sends packets in an infinite loop, verifies them on the expected interface, and streams live
pass/fail status to a WebSocket dashboard, so a config change on the broker shows up within seconds
without re-running anything.

## How it works

Subscriber-facing ("internal") traffic flows through the broker to network-facing ("external")
traffic. The broker routes it via a DPI engine that inspects it and signals a decision back over
PCP bits (the VLAN priority field, repurposed as a signaling channel). This framework drives that
pipeline end to end: build a packet, send it in on `internal1`, wait for it on `external1`, check
the fields that matter, record the result, repeat — once per second, forever, for every registered
test, all running concurrently in one process.

Currently implemented: a single internal/external pair, the DPI round trip at PCP=0 (normal
forwarding), and L2 control-plane bypass (LACP/STP/LLDP/CDP) — see [CLAUDE.md](CLAUDE.md) for the
full scope and what's deferred.

## Quick start

Requires Docker (the test framework needs Linux's AF_PACKET sockets, so on macOS this runs inside a
privileged container via Docker Desktop's Linux VM).

```bash
docker compose up --build
```

This builds the sandbox container, brings up a simulated broker topology (network namespaces +
veth pairs standing in for real cabling), starts the simulated broker, and starts the FastAPI app.

- Dashboard: <http://localhost:8000/>
- Health check: <http://localhost:8000/health>
- Live events: `ws://localhost:8000/ws/live`
- REST API: <http://localhost:8000/api/tests>

```bash
docker compose down
```

Tears the container down cleanly, including the simulated topology.

## REST API

| Method | Path | Description |
|---|---|---|
| GET | `/api/tests` | List every registered test with current status |
| GET | `/api/tests/{id}` | Full detail for one test: encapsulation, packet signature, result history |
| POST | `/api/tests/{id}/start` | (Re)start one test's loop |
| POST | `/api/tests/{id}/stop` | Stop one test's loop |
| POST | `/api/tests/start-all` | Start every stopped test |
| POST | `/api/tests/stop-all` | Stop every running test |
| GET | `/api/config` | Current `config.json` contents |
| POST | `/api/config` | *(not yet implemented — deferred past MVP)* |
| WebSocket | `/ws/live` | Live `{test_id, status, pps, loss_pct, timestamp}` events |

## Project structure

```
core/        Engine: topology parsing, AF_PACKET I/O, packet building/matching, the DPI stub,
             test scheduling and state tracking
tests/       One file per test family (test_l2_bypass.py and test_dpi_flow.py are implemented;
             the rest are specced but deferred)
protocols/   Static protocol tables (e.g. the L2 bypass MAC/ethertype list)
api/         FastAPI app: REST routes + the live WebSocket
frontend/    Plain HTML/JS dashboard, no build step
sandbox/     Local dev environment — simulates the broker so you can develop without hardware
```

See [CLAUDE.md](CLAUDE.md) for the full architecture, configuration reference, terminology
glossary, and the sandbox-vs-real-hardware migration story — it's the canonical design doc for this
repo and every module's docstring points back to it.

## Configuration

- **`topology.yaml`** — interfaces, pair/LAG groupings, runtime tunables.
- **`config.json`** — which test groups are enabled and how.
- **`sandbox/broker_sim/broker_config.yaml`** — the simulated broker's own config; must stay in
  sync with `protocols/l2_bypass_list.py`.

## Status

The MVP described above is implemented and tested against the sandbox. Mirroring/steering, the
full encapsulation matrix, LAG hash detection, multi-pair isolation, IP/port/proto bypass, and
report export are deferred but designed to be additive — see CLAUDE.md's "MVP scope" table for what
each one needs.
