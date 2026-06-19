# Testing steps 6-10 of the Implementation Roadmap

This documents how I verified the remaining 5 files of README.md §9 / CLAUDE.md
"Implementation order" (steps 1-5 were already done -- see `TESTING.md`):

6. `core/dpi_stub.py`
7. `tests/test_dpi_flow.py` (PCP=0 only)
8. `core/state_manager.py` + `core/collision_checker.py` + `core/test_runner.py`
9. `api/main.py` + `api/websocket.py` + `api/routes_tests.py`
10. `frontend/index.html`

Same two-layer approach as `TESTING.md`, plus a third layer in between:

- **Layer A -- pure logic, no sockets**: exercises `core/dpi_stub.py`,
  `core/collision_checker.py`, `core/state_manager.py`, and
  `core/test_runner.py` against fake in-memory interfaces. Runs on the Mac
  host in the same scratch virtualenv `TESTING.md` describes.
- **Layer A2 -- FastAPI route layer, no sockets**: drives the real
  `api/main.py` app (startup hook, all routes, the websocket) through
  FastAPI's `TestClient`, with `core.packet_engine.PacketEngine` and
  `core.topology.load_topology` monkeypatched to an in-process fake that
  reproduces `sandbox/broker_sim/broker_sim.py`'s logic. Also runs on the Mac
  host.
- **Layer B -- full round trip in the sandbox (Docker required)**: the real
  AF_PACKET sockets, the real veth topology, the real `broker_sim.py`. This
  is what actually matters and is where two real bugs were found (see
  "Bugs found and fixed" below) -- Layer A/A2 passed against the fakes
  before Layer B ever ran, which is exactly why Layer B exists.

---

## Layer A -- dpi_stub / collision_checker / state_manager / test_runner logic

No AF_PACKET, no Docker -- runs directly on the Mac in a disposable
virtualenv (same one `TESTING.md` sets up):

```bash
python3 -m venv /tmp/pba_venv
/tmp/pba_venv/bin/pip install -q -r requirements.txt
```

The test script (reproduced below so you can re-run it verbatim) builds two
small fakes -- `FakeDispatcher`/`FakeEngine` -- that implement the same
`subscribe()`/`unsubscribe()`/`send()` surface `core/packet_engine.py`'s real
`InterfaceDispatcher` exposes, so `DpiStub`, `BaseTest.run_once()`, and
`test_runner.run_test_loop()` all run completely unmodified against them.

Save as `/tmp/pba_layer_a_steps_6_10.py`:

```python
import asyncio
import sys

sys.path.insert(0, ".")

from core.topology import Topology, Pair
from core.collision_checker import check_for_collisions
from core.state_manager import StateManager
from core.dpi_stub import DpiStub
from core.base_test import TestResult
from tests.test_l2_bypass import build_l2_bypass_tests
from tests.test_dpi_flow import DpiFlowTest
from core.test_runner import register_all_tests, run_test_loop, start_one, start_all
from scapy.layers.l2 import Ether, Dot1Q
from scapy.layers.inet import IP, UDP


class FakeDispatcher:
    def __init__(self, ifname):
        self.ifname = ifname
        self.sent = []
        self._subs = {}

    def subscribe(self, predicate):
        q = asyncio.Queue()
        self._subs[q] = predicate
        return q

    def unsubscribe(self, q):
        self._subs.pop(q, None)

    def send(self, raw):
        self.sent.append(raw)

    def deliver(self, raw):
        for q, pred in list(self._subs.items()):
            if pred(raw):
                q.put_nowait(raw)


class FakeEngine:
    def __init__(self, ifnames):
        self._d = {name: FakeDispatcher(name) for name in ifnames}

    def get(self, ifname):
        return self._d[ifname]


def make_topology():
    pair = Pair(
        internal="internal1", external="external1",
        internal_mac="aa:aa:aa:aa:aa:01", external_mac="aa:aa:aa:aa:aa:02",
    )
    return Topology(
        mode="sandbox", pairs=[pair], dpi_lag=["dpi1"],
        dpi_macs={"dpi1": "aa:aa:aa:aa:aa:03"}, mirroring_lag=[], steering_lag=[],
        dpi_vlan_id=999, ip_base="10.0.0.0/24",
        parallel_limit=10, send_interval_ms=50, capture_buffer=1000,
    )


def section(name):
    print(f"\n=== {name} ===")


async def main():
    topology = make_topology()
    config = {
        "tests": {
            "l2_bypass": {"enabled": True, "protocols": ["LACP", "STP", "LLDP", "CDP"]},
            "dpi_flow": {"enabled": True, "pcp_variants": [0]},
            "ip_bypass": {"enabled": False},
            "lag_hash": {"enabled": False},
            "mirroring": {"enabled": False},
        }
    }

    engine = FakeEngine(["internal1", "external1", "dpi1"])

    section("DpiStub: register + run() echoes back with VLAN/PCP")
    dpi_stub = DpiStub(engine, topology.dpi_lag, topology.dpi_vlan_id)

    tests = register_all_tests(config, topology, engine, dpi_stub)
    ids = [t.id for t in tests]
    print("registered test ids:", ids)
    assert "l2_bypass.LACP" in ids and "dpi_flow.pcp0" in ids
    assert len(dpi_stub._registrations) == 1

    dpi_task = asyncio.ensure_future(dpi_stub.run())
    await asyncio.sleep(0)

    dpi_flow_test = next(t for t in tests if t.id == "dpi_flow.pcp0")
    inner = dpi_flow_test.build_packet()
    wrapped = Ether(src=inner.src, dst=inner.dst) / Dot1Q(vlan=999) / inner.payload
    engine.get("dpi1").deliver(bytes(wrapped))
    await asyncio.sleep(0.05)

    assert len(engine.get("dpi1").sent) == 1
    echoed = Ether(engine.get("dpi1").sent[0])
    assert echoed.haslayer(Dot1Q) and echoed[Dot1Q].vlan == 999 and echoed[Dot1Q].prio == 0
    assert echoed.haslayer(IP) and echoed[IP].src == dpi_flow_test._src_ip()
    print("PASS: DpiStub echoed frame with vlan=999 prio=0, inner IP preserved:", echoed[IP].src, "->", echoed[IP].dst)

    dpi_task.cancel()
    try:
        await dpi_task
    except asyncio.CancelledError:
        pass

    section("collision_checker: catches a deliberate collision")
    colliding = build_l2_bypass_tests(topology.pairs[0], ["LACP"]) + build_l2_bypass_tests(topology.pairs[0], ["LACP"])
    try:
        check_for_collisions(colliding)
        print("FAIL: expected ValueError for colliding packet_signature()")
        sys.exit(1)
    except ValueError as e:
        print("PASS: collision raised as expected:", e)

    section("StateManager: register/update/get_status/get_history/subscribe fan-out")
    sm = StateManager()
    sm.register("l2_bypass.LACP")
    assert sm.get_status("l2_bypass.LACP")["status"] == "PENDING"

    q = sm.subscribe()
    sm.update("l2_bypass.LACP", TestResult(status="OK", latency_ms=1.2, failures=[], timestamp=1000.0))
    sm.update("l2_bypass.LACP", TestResult(status="OK", latency_ms=1.1, failures=[], timestamp=1001.0))
    sm.update("l2_bypass.LACP", TestResult(status="TIMEOUT", latency_ms=None, failures=["x"], timestamp=1002.0))

    status = sm.get_status("l2_bypass.LACP")
    print("status after 2 OK + 1 TIMEOUT:", status)
    assert status["status"] == "TIMEOUT"
    assert status["loss_pct"] == round(1 / 3 * 100, 2)
    assert status["pps"] == 1.0

    events = []
    while not q.empty():
        events.append(q.get_nowait())
    assert len(events) == 3
    print("PASS: state_manager status/history/fan-out all correct;", len(events), "events fanned out")

    sm.set_status("l2_bypass.LACP", "STOPPED")
    assert sm.get_status("l2_bypass.LACP")["status"] == "STOPPED"
    print("PASS: set_status() overrides status without a TestResult")

    section("test_runner: run_test_loop iterates and calls state_manager.update")

    class FakeTest:
        def __init__(self, id_):
            self.id = id_
            self.calls = 0

        async def run_once(self, engine):
            self.calls += 1
            return TestResult(status="OK", latency_ms=0.5, failures=[], timestamp=self.calls)

    sm2 = StateManager()
    sm2.register("fake.1")
    ft = FakeTest("fake.1")
    sem = asyncio.Semaphore(2)
    task = asyncio.ensure_future(run_test_loop(ft, engine, sm2, interval_ms=10, semaphore=sem))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert ft.calls >= 2
    assert sm2.get_status("fake.1")["status"] == "OK"
    print(f"PASS: run_test_loop ran {ft.calls} iterations and updated state_manager")

    section("test_runner: start_all respects parallel_limit via semaphore")
    sm3 = StateManager()
    for t in tests:
        sm3.register(t.id)
    loop = asyncio.get_running_loop()
    task_map, semaphore = start_all(tests, engine, sm3, loop, parallel_limit=2, interval_ms=20)
    assert isinstance(semaphore, asyncio.Semaphore)
    assert set(task_map.keys()) == set(ids)
    await asyncio.sleep(0.05)
    for task in task_map.values():
        task.cancel()
    for task in task_map.values():
        try:
            await task
        except asyncio.CancelledError:
            pass
    print("PASS: start_all() created one task per test id:", list(task_map.keys()))

    print("\nALL LAYER-A CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
/tmp/pba_venv/bin/python3 -m py_compile core/dpi_stub.py core/collision_checker.py \
    core/state_manager.py core/test_runner.py core/topology.py core/packet_engine.py \
    tests/test_dpi_flow.py api/main.py api/websocket.py api/routes_tests.py

/tmp/pba_venv/bin/python3 /tmp/pba_layer_a_steps_6_10.py
```

**Expected output:** every section prints `PASS: ...`, ending with
`ALL LAYER-A CHECKS PASSED`. Specifically this proves:

- `DpiStub.register()`/`.run()` correctly demuxes by predicate, strips the
  inbound VLAN tag, and echoes back with the right `vlan_id`/`prio` -- without
  ever touching a real socket.
- `collision_checker.check_for_collisions()` raises `ValueError` naming both
  colliding tests when two tests share a `packet_signature()`.
- `StateManager` computes `pps`/`loss_pct` correctly from a result history,
  fans every `update()`/`set_status()` out to subscribed queues, and
  `PENDING` is the default status before any result lands.
- `test_runner.run_test_loop()` loops forever at the given interval and
  pushes every result into `state_manager`; `start_all()` returns one task
  per test id plus a shared semaphore.

---

## Layer A2 -- FastAPI route layer (api/main.py, websocket.py, routes_tests.py)

Same idea, one level up: drive the actual `api.main.app` object through
`TestClient`, with the socket layer faked. The fake reproduces
`sandbox/broker_sim/broker_sim.py`'s actual forwarding logic in-process (L2
bypass straight through; everything else wrapped in
`Dot1Q(vlan=dpi_vlan_id)` toward `dpi1`), so the registered `L2BypassTest`/
`DpiFlowTest` instances exercise their real `run_once()` logic end-to-end,
not just a trivial echo.

```bash
/tmp/pba_venv/bin/pip install -q httpx   # TestClient's transport dependency
```

Save as `/tmp/pba_api_integration.py`:

```python
import asyncio
import sys

sys.path.insert(0, ".")

import core.packet_engine as packet_engine_module
import core.topology as topology_module
from core.topology import Topology, Pair
from scapy.layers.l2 import Ether, Dot1Q


class FakeDispatcher:
    def __init__(self, ifname, broker):
        self.ifname = ifname
        self.broker = broker
        self._subs = {}

    def subscribe(self, predicate):
        q = asyncio.Queue()
        self._subs[q] = predicate
        return q

    def unsubscribe(self, q):
        self._subs.pop(q, None)

    def send(self, raw):
        self.broker.handle(self.ifname, raw)

    def deliver(self, raw):
        for q, pred in list(self._subs.items()):
            if pred(raw):
                q.put_nowait(raw)


class FakeBroker:
    """In-process stand-in for sandbox/broker_sim/broker_sim.py."""

    BYPASS_MACS = {"01:80:c2:00:00:02", "01:80:c2:00:00:00", "01:80:c2:00:00:0e", "01:00:0c:cc:cc:cc"}

    def __init__(self, dpi_vlan_id):
        self.dpi_vlan_id = dpi_vlan_id
        self.dispatchers = {}

    def handle(self, ifname, raw):
        pkt = Ether(raw)
        if ifname == "internal1":
            if pkt.dst.lower() in self.BYPASS_MACS:
                self.dispatchers["external1"].deliver(raw)
            else:
                tagged = Ether(src=pkt.src, dst=pkt.dst) / Dot1Q(vlan=self.dpi_vlan_id) / pkt.payload
                self.dispatchers["dpi1"].deliver(bytes(tagged))
        elif ifname == "dpi1":
            if pkt.haslayer(Dot1Q) and pkt[Dot1Q].vlan == self.dpi_vlan_id:
                inner = Ether(src=pkt.src, dst=pkt.dst) / pkt[Dot1Q].payload
                self.dispatchers["external1"].deliver(bytes(inner))


class FakePacketEngine:
    def __init__(self, topology):
        self.broker = FakeBroker(topology.dpi_vlan_id)
        self._dispatchers = {name: FakeDispatcher(name, self.broker) for name in topology.all_interface_names()}
        self.broker.dispatchers = self._dispatchers

    def start_all(self, loop):
        pass

    def get(self, ifname):
        return self._dispatchers[ifname]

    def close_all(self):
        pass


def fake_load_topology(path="topology.yaml"):
    pair = Pair(internal="internal1", external="external1",
                internal_mac="aa:aa:aa:aa:aa:01", external_mac="aa:aa:aa:aa:aa:02")
    return Topology(
        mode="sandbox", pairs=[pair], dpi_lag=["dpi1"], dpi_macs={"dpi1": "aa:aa:aa:aa:aa:03"},
        mirroring_lag=[], steering_lag=[], dpi_vlan_id=999, ip_base="10.0.0.0/24",
        parallel_limit=10, send_interval_ms=100, capture_buffer=1000,
    )


packet_engine_module.PacketEngine = FakePacketEngine
topology_module.load_topology = fake_load_topology

from fastapi.testclient import TestClient
import api.main as main_module

main_module.PacketEngine = FakePacketEngine
main_module.load_topology = fake_load_topology


def section(name):
    print(f"\n=== {name} ===")


with TestClient(main_module.app) as client:
    section("GET /health")
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}, r.text
    print("PASS:", r.json())

    section("GET /api/tests -- all 5 MVP tests registered")
    r = client.get("/api/tests")
    body = r.json()
    ids = sorted(t["id"] for t in body)
    print("ids:", ids)
    assert ids == sorted(["l2_bypass.LACP", "l2_bypass.STP", "l2_bypass.LLDP", "l2_bypass.CDP", "dpi_flow.pcp0"])
    assert all(t["pair"] == {"internal": "internal1", "external": "external1"} for t in body)
    assert all(t["running"] for t in body)
    print("PASS: all 5 tests listed, correct pair, all running")

    section("Wait for at least one iteration, then re-check statuses are OK")
    import time
    time.sleep(0.5)
    r = client.get("/api/tests")
    statuses = {t["id"]: t["status"] for t in r.json()}
    print("statuses:", statuses)
    assert all(s == "OK" for s in statuses.values())
    print("PASS: every test round-trips OK through the fake broker (L2 bypass + full DPI flow)")

    section("GET /api/tests/{id} -- detail with history + encap + packet_signature")
    r = client.get("/api/tests/dpi_flow.pcp0")
    detail = r.json()
    assert detail["packet_signature"] == {"ip_src": "10.0.0.10"}
    assert len(detail["history"]) >= 1
    print("PASS: detail includes packet_signature + non-empty history:", detail["packet_signature"])

    section("GET /api/tests/does-not-exist -- 404")
    r = client.get("/api/tests/does-not-exist")
    assert r.status_code == 404, r.text
    print("PASS: 404 for unknown test id")

    section("POST /api/tests/{id}/stop then start")
    r = client.post("/api/tests/l2_bypass.LACP/stop")
    assert r.json() == {"id": "l2_bypass.LACP", "running": False}, r.text
    r = client.get("/api/tests")
    running = {t["id"]: t["running"] for t in r.json()}
    assert running["l2_bypass.LACP"] is False
    print("PASS: stop -> running=False")

    r = client.post("/api/tests/l2_bypass.LACP/start")
    assert r.json()["running"] is True, r.text
    time.sleep(0.3)
    r = client.get("/api/tests")
    lacp = [t for t in r.json() if t["id"] == "l2_bypass.LACP"][0]
    assert lacp["running"] is True and lacp["status"] == "OK"
    print("PASS: restarted test resumes and goes OK again")

    section("POST /api/tests/stop-all then start-all")
    r = client.post("/api/tests/stop-all")
    print("stopped:", sorted(r.json()["stopped"]))
    r = client.get("/api/tests")
    assert all(t["running"] is False for t in r.json())
    print("PASS: stop-all stopped every test")

    r = client.post("/api/tests/start-all")
    print("started:", sorted(r.json()["started"]))
    time.sleep(0.3)
    r = client.get("/api/tests")
    assert all(t["running"] is True and t["status"] == "OK" for t in r.json())
    print("PASS: start-all restarted every test, all back to OK")

    section("WebSocket /ws/live -- receives live events")
    with client.websocket_connect("/ws/live") as ws:
        event = ws.receive_json()
        print("first ws event:", event)
        assert set(event.keys()) == {"test_id", "status", "pps", "loss_pct", "timestamp"}
        assert event["test_id"] in ids
    print("PASS: websocket delivered a correctly-shaped live event")

    section("Static frontend mount -- GET /")
    r = client.get("/")
    assert r.status_code == 200 and "packet_broker_autotest" in r.text
    print("PASS: frontend/index.html served at /")

print("\nALL API INTEGRATION CHECKS PASSED")
```

Run it:

```bash
/tmp/pba_venv/bin/python3 /tmp/pba_api_integration.py
```

**Expected output:** every section prints `PASS: ...`, ending with
`ALL API INTEGRATION CHECKS PASSED`. This is the only layer that exercises
`api/main.py`'s real startup hook (the exact ordering documented in
`core/test_runner.py`'s "STARTUP ORDERING"), every route in
`api/routes_tests.py`, the websocket fan-out in `api/websocket.py`, and
`StaticFiles` serving `frontend/index.html` -- all without Docker.

---

## Layer B -- full round trip in the sandbox (Docker required)

This is the layer that actually matters, and the one that caught two real
bugs (see next section). It exercises the real AF_PACKET sockets, the real
veth topology, and the real `sandbox/broker_sim/broker_sim.py`.

### 1. Build and start the sandbox container

```bash
docker compose up --build -d
```

### 2. Confirm clean startup

```bash
docker compose logs --tail=40
```

Expect the same ordering `TESTING.md` describes (veth wiring -> `broker_sim.py`
starting -> uvicorn starting), with **no** `DpiStub: frame on dpi1 has no
outer VLAN tag to strip` warnings anywhere in the log (see "Bugs found and
fixed" below for what that warning meant before the fix).

```bash
curl -s http://localhost:8000/health
```

Expect `{"status":"ok"}`.

### 3. All 5 MVP tests registered and passing

```bash
curl -s http://localhost:8000/api/tests | python3 -m json.tool
```

Expect a JSON array of 5 objects (`l2_bypass.LACP`/`STP`/`LLDP`/`CDP`,
`dpi_flow.pcp0`), each `"pair": {"internal": "internal1", "external":
"external1"}`, `"running": true`. Statuses may briefly show `"PENDING"`
immediately after startup; within ~1-2s (one `send_interval_ms` cycle) they
should all settle to `"status": "OK"`, `"loss_pct": 0.0`, `"pps"` near `1.0`.

### 4. DPI-flow round trip in detail, with stable latency

```bash
curl -s http://localhost:8000/api/tests/dpi_flow.pcp0 | python3 -m json.tool
```

Check `"packet_signature": {"ip_src": "10.0.0.10"}` and inspect the
`"history"` array's `latency_ms` values -- they should stay in a small,
roughly-flat range (single-digit milliseconds in this environment; exact
numbers vary by machine), **not** trend upward across entries. A steadily
growing `latency_ms` (eventually ending in a `TIMEOUT`) is the symptom of
the queue-backlog bug described below -- if you see that, something has
regressed.

### 5. Live websocket events

```bash
docker compose exec packetbroker python3 -c "
import asyncio
import websockets

async def main():
    async with websockets.connect('ws://localhost:8000/ws/live') as ws:
        for _ in range(3):
            print(await asyncio.wait_for(ws.recv(), timeout=3))

asyncio.run(main())
"
```

Expect 3 lines of JSON shaped like
`{"test_id": "...", "status": "OK", "pps": 0.99, "loss_pct": 0.0, "timestamp": ...}`.

### 6. Individual start/stop and start-all/stop-all

```bash
curl -s -X POST http://localhost:8000/api/tests/l2_bypass.LACP/stop | python3 -m json.tool
curl -s http://localhost:8000/api/tests/l2_bypass.LACP | python3 -c "import json,sys; d=json.load(sys.stdin); print('running:', d['running'], 'status:', d['status'])"
# Expect: running: False status: STOPPED

curl -s -X POST http://localhost:8000/api/tests/l2_bypass.LACP/start | python3 -m json.tool
sleep 1.5
curl -s http://localhost:8000/api/tests/l2_bypass.LACP | python3 -c "import json,sys; d=json.load(sys.stdin); print('running:', d['running'], 'status:', d['status'])"
# Expect: running: True status: OK

curl -s -X POST http://localhost:8000/api/tests/stop-all | python3 -m json.tool
curl -s http://localhost:8000/api/tests | python3 -c "import json,sys; print(all(t['running'] is False for t in json.load(sys.stdin)))"
# Expect: True

curl -s -X POST http://localhost:8000/api/tests/start-all | python3 -m json.tool
sleep 1.5
curl -s http://localhost:8000/api/tests | python3 -c "import json,sys; d=json.load(sys.stdin); print(all(t['running'] and t['status']=='OK' for t in d))"
# Expect: True
```

### 7. Negative-path check (carried over from TESTING.md, re-verified here)

A non-bypassed, non-DPI-registered protocol must TIMEOUT, not false-PASS --
this still holds with the new `core/dpi_stub.py` in the picture:

```bash
docker compose exec packetbroker python3 -c "
import asyncio
from core.packet_engine import PacketEngine
from core.topology import load_topology
from tests.test_l2_bypass import L2BypassTest

async def main():
    topology = load_topology('topology.yaml')
    pair = topology.pairs[0]
    engine = PacketEngine(topology)
    engine.start_all(asyncio.get_running_loop())
    t = L2BypassTest('NOT_BYPASSED', dst_mac='02:00:00:00:00:01', ethertype=0x1234)
    t.pair = pair
    print(await t.run_once(engine, timeout_s=1.5))

asyncio.run(main())
"
```

Expected: `TestResult(status='TIMEOUT', ...)`.

### 8. Re-run the steps 1-5 smoke test, to confirm no regression

```bash
docker compose exec packetbroker python3 -m scripts.smoke_test_l2_bypass
```

Expected: `ALL OK`, all 4 protocols `[PASS]` -- this runs concurrently with
the live app's own tests (a second `PacketEngine` binding its own AF_PACKET
sockets to the same interfaces), confirming multiple independent listeners
on the same interface still work correctly.

### 9. Frontend dashboard

```bash
curl -s http://localhost:8000/ | head -5   # confirm frontend/index.html is served
```

Then open `http://localhost:8000/` in a browser. Expect: a header bar with
a "`N / N running`" counter, a websocket status pill that turns green/"live"
within a second, Start All / Stop All buttons, and one
"`internal1 -> external1`" section containing a table of all 5 tests, each
row showing a green "✓ OK" status, `pps`, and `loss%`, updating live without
a page refresh. Clicking a row navigates to `test_detail.html?id=<id>`
(that page itself is still the deferred placeholder -- only the navigation
hook was required for this round, per its own docstring).

*(I verified this functionally via the API calls above, which is exactly
what the page's JS calls; a full interactive browser screenshot pass was
skipped this round.)*

### 10. Tear down

```bash
docker compose down
```

---

## Bugs found and fixed along the way

Layer A and Layer A2 passed cleanly against their fakes; Layer B (the real
sandbox) immediately surfaced two real, pre-existing issues that the
fakes couldn't reproduce because they don't model raw-socket kernel
behavior:

### 1. AF_PACKET sees its own outgoing traffic (`core/packet_engine.py`)

`core/dpi_stub.py` is the first component that both **sends** and
**subscribes** on the *same* interface (`dpi1`). AF_PACKET sockets deliver
traffic in both directions by default, so `DpiStub`'s own echoed frame was
being re-delivered to itself as a "new arrival" and re-echoed, in an
unbounded loop (confirmed via `docker stats` showing the warning log line
growing without bound). Fixed in `InterfaceHandle.recv()` by switching to
`recvfrom()` and filtering out frames where `sll_pkttype == PACKET_OUTGOING`
(`core/packet_engine.py`'s new `PACKET_OUTGOING` constant). This was a
latent bug in the already-"done" `core/packet_engine.py` from steps 1-5 --
invisible there because `tests/test_l2_bypass.py` never sends and
subscribes on the same interface.

### 2. The kernel strips VLAN tags from AF_PACKET's raw bytes (`core/packet_engine.py`)

Even after fixing #1, `core/dpi_stub.py` kept logging
`"frame on dpi1 has no outer VLAN tag to strip"` for every genuine frame
from `broker_sim.py`. Isolated with two bare `AF_PACKET` sockets on a
throwaway veth pair (no scapy, no broker_sim): a hand-crafted 802.1Q frame
sent through one socket arrived at the other **4 bytes shorter, with the
tag gone** -- the Linux kernel normalizes every received 802.1Q frame by
moving the tag out of the payload into SKB metadata before delivering it to
AF_PACKET listeners. (`tcpdump -e` appears to show the tag because it
separately reconstructs it from that same metadata via `PACKET_AUXDATA` --
it does not reflect what a plain `recv()` actually returns.) This is
generic Linux networking-stack behavior, not a veth-only or sandbox-only
quirk -- `ethtool -K ... rxvlan off txvlan off` had no effect, confirming
it. Fixed for good in `InterfaceHandle.recv()`: the socket now opts into
`PACKET_AUXDATA` and `recv()` uses `recvmsg()` to read the ancillary
`tpacket_auxdata` struct, reconstructing the `Dot1Q` tag in-band from
`tp_vlan_tci`/`tp_vlan_tpid` before returning. Because this is core kernel
behavior rather than a sandbox artifact, the fix lives in
`core/packet_engine.py` (not `sandbox/`) and applies identically on real
hardware.

### 3. `broker_sim.py`'s own `sniff()` calls also see their own sends

While investigating #2, `dpi_flow.pcp0`'s `latency_ms` was found to grow
steadily across iterations (134ms -> 1644ms) before eventually `TIMEOUT`ing.
A 12-second `tcpdump` capture showed **349 frames on `external1`** where
only ~60 were expected (5 tests x ~1/sec x 12s) -- an unbounded
amplification. Root cause: `broker_sim.py` used scapy's `sniff()` (which
opens a receive-only socket) and a separate `sendp(iface=...)` call (which
opens its own send-only socket) per interface. Scapy's `L2Socket` *does*
have built-in `PACKET_OUTGOING` filtering, but it only activates when the
same combined socket is used for both -- a receive-only `sniff()` socket
can never see itself as the sender, so it has no way to filter its own
relayed L2-bypass frames bouncing right back to it, creating an
internal1<->external1 ping-pong that amplified without bound (confirmed by
inspecting the captured frames: dozens of LACP/STP/LLDP/CDP frames per
second instead of one). Fixed in `sandbox/broker_sim/broker_sim.py` by
opening one combined `scapy.arch.linux.L2Socket` per interface up front and
passing it to both `sniff(opened_socket=...)` and `sendp(socket=...)`, so
scapy's existing self-filtering applies. This bug was **pre-existing in
steps 1-5's `broker_sim.py`** but invisible to `tests/test_l2_bypass.py`,
since each L2-bypass test iteration only cares about the *first* matching
frame on a freshly-subscribed, freshly-discarded queue -- the amplified
duplicates were silently wasting CPU/bandwidth in the background without
ever causing a visible test failure. It only became visible once
`core/dpi_stub.py` introduced a single **long-lived** subscription whose
queue could actually accumulate backlog from `dpi1`-adjacent traffic
contention.

All three fixes were verified by re-running the full Layer B suite above
from a clean `docker compose down && docker compose up --build -d`: no
warnings in the logs, `dpi1`/`external1` frame counts back to expected
levels, and `dpi_flow.pcp0`'s `latency_ms` flat in the low single-digit
milliseconds across 50 consecutive iterations.
