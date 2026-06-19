# Testing steps 1-5 of the Implementation Roadmap

This documents how I verified the first 5 files of README.md §9 / CLAUDE.md
"Implementation order":

1. `core/topology.py`
2. `core/packet_builder.py`
3. `core/packet_engine.py`
4. `core/base_test.py` + `core/matcher.py`
5. `tests/test_l2_bypass.py` (+ `protocols/l2_bypass_list.py`, which it depends on)

Two layers of testing were used, because AF_PACKET (used by `core/packet_engine.py`)
is Linux-only and can't run directly on macOS:

- **Layer A — pure logic, no sockets** (`core/packet_builder.py`, `core/matcher.py`):
  runs anywhere Python + Scapy are installed, including directly on the Mac, in a
  scratch virtualenv.
- **Layer B — full round trip over real sockets** (`core/topology.py`,
  `core/packet_engine.py`, `core/base_test.py`, `tests/test_l2_bypass.py`): requires
  the sandbox container (real AF_PACKET sockets + the veth topology + `broker_sim.py`
  acting as the simulated broker).

`core/test_runner.py` / `api/main.py` (which would normally call
`register_all_tests()` and loop the tests forever) are later steps (6-9) and aren't
implemented yet, so Layer B uses a small standalone script,
`scripts/smoke_test_l2_bypass.py`, that does by hand what `test_runner.py` will
eventually automate: load topology, build a `PacketEngine`, build the 4 L2-bypass
tests from `config.json`, and run each one once.

---

## Layer A — packet_builder.py + matcher.py logic, run on the host (no Docker)

These two files don't touch sockets, so they can be checked with a disposable
virtualenv on the Mac, without needing Linux/AF_PACKET at all.

```bash
# From the repo root.
python3 -m venv /tmp/pba_venv
/tmp/pba_venv/bin/pip install -q -r requirements.txt
```

Then, still from the repo root:

```bash
/tmp/pba_venv/bin/python3 -c "
import sys
sys.path.insert(0, '.')
from core.packet_builder import EncapConfig, DEFAULT_ENCAP, apply_encap, build_eth, serialize
from core.matcher import PacketMatcher
from scapy.layers.l2 import Ether, Dot1Q

# build_eth() + serialize() round trip
pkt = build_eth('aa:bb:cc:dd:ee:ff', '01:80:c2:00:00:02', 0x8809)
raw = serialize(pkt)
parsed = Ether(raw)
print('parsed dst', parsed.dst, 'type', hex(parsed.type))

# apply_encap() with the empty-stack (MVP/'smoke') case must be a no-op
wrapped = apply_encap(pkt, DEFAULT_ENCAP)
print('encap empty round-trip equal:', bytes(wrapped) == bytes(pkt))

# apply_encap() with a real VLAN stack, to prove the generic (non-MVP) path works too
cfg = EncapConfig(vlan_stack=[100, 200])
wrapped2 = apply_encap(build_eth('aa:bb:cc:dd:ee:ff', '11:22:33:44:55:66'), cfg)
print('outer vlan', wrapped2[Dot1Q].vlan, 'inner vlan', wrapped2[Dot1Q].payload[Dot1Q].vlan)

# PacketMatcher: matching, mismatching, and missing-layer cases
print(PacketMatcher(eth_dst='01:80:c2:00:00:02', eth_type=0x8809).match(parsed))
print(PacketMatcher(eth_dst='ff:ff:ff:ff:ff:ff').match(parsed))
print(PacketMatcher(ip_dst='10.0.0.1').match(parsed))
"
```

**What this proves / expected output:**
- `parsed dst 01:80:c2:00:00:02 type 0x8809` — `build_eth()`/`serialize()` produce
  bytes that parse back to the same fields.
- `encap empty round-trip equal: True` — `apply_encap()` with `DEFAULT_ENCAP`
  (bare Ethernet) is a true no-op, as required for MVP/"smoke" mode.
- `outer vlan 100 inner vlan 200` — `apply_encap()` stacks VLAN tags
  outermost-first per `EncapConfig.vlan_stack`, proving the function is generic
  and not special-cased for the empty-stack MVP case.
- The three `PacketMatcher` lines show: a full match (`ok=True`), a field
  mismatch reported with old vs. new value, and a "field expected but layer
  missing" failure — all without raising an exception.

---

## Layer B — full round trip in the sandbox (Docker required)

This exercises `core/topology.py`, `core/packet_engine.py` (real AF_PACKET
sockets), `core/base_test.py`'s `run_once()`, and `tests/test_l2_bypass.py`
against the real veth topology and `sandbox/broker_sim/broker_sim.py`.

### 1. Build and start the sandbox container

```bash
docker compose up --build -d
```

This builds the image, then `sandbox/entrypoint.sh` runs inside the container and:
creates the `broker_sim` netns + the 3 veth pairs (`internal1`/`external1`/`dpi1` ↔
`br_internal1`/`br_external1`/`br_dpi1`), starts `broker_sim.py` in that namespace,
then starts `uvicorn api.main:app` in the foreground.

### 2. Confirm the container came up cleanly

```bash
docker compose logs --tail=40
```

Look for, in order: the 3 `[setup_sandbox] Wiring ...` lines, the interface list
showing `internal1`/`external1`/`dpi1` as `UP`, `[entrypoint] Starting broker_sim.py
...`, and finally `Uvicorn running on http://0.0.0.0:8000`. If uvicorn starts before
the veth wiring finishes, something is wrong with `entrypoint.sh`'s ordering.

```bash
curl -s http://localhost:8000/health
```

Expect `{"status":"ok"}` — confirms the container's networking/port-mapping itself
is fine before testing anything packet-related.

### 3. Run the L2 bypass smoke test

```bash
docker compose exec packetbroker python3 -m scripts.smoke_test_l2_bypass
```

(Run as `-m scripts.smoke_test_l2_bypass`, not as a plain script path — the script
imports `core.*`/`tests.*` as packages, which only resolves correctly when Python
treats `/app` as the package root via `-m`.)

This script (`scripts/smoke_test_l2_bypass.py`) loads `topology.yaml`, builds a
`PacketEngine`, builds one `L2BypassTest` per protocol listed in `config.json`'s
`tests.l2_bypass.protocols` (LACP, STP, LLDP, CDP), and calls `run_once()` on each:
send the frame out `internal1`, wait on `external1`, check the result.

**Expected output:**

```
Running 4 L2 bypass test(s) against internal1 -> external1 ...

[PASS] LACP   status=OK      latency_ms=... failures=[]
[PASS] STP    status=OK      latency_ms=... failures=[]
[PASS] LLDP   status=OK      latency_ms=... failures=[]
[PASS] CDP    status=OK      latency_ms=... failures=[]

ALL OK
```

I ran this 3 times in a row to confirm it's repeatable (no leaked sockets/
subscriptions across runs) — all 3 runs passed all 4 protocols.

### 4. Negative-path check: a non-bypass protocol must TIMEOUT, not false-PASS

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

    # Not in protocols/l2_bypass_list.py -- broker_sim.py treats this as
    # DPI-eligible and forwards it to dpi1, which nothing reads yet
    # (core/dpi_stub.py is step 6, not implemented). Must TIMEOUT.
    t = L2BypassTest('NOT_BYPASSED', dst_mac='02:00:00:00:00:01', ethertype=0x1234)
    t.pair = pair
    print(await t.run_once(engine, timeout_s=1.5))

asyncio.run(main())
"
```

Expected: `TestResult(status='TIMEOUT', latency_ms=None, failures=['no matching
frame received on external1 within 1.5s'], ...)`. This matters because
`L2BypassTest`'s `subscribe()` predicate and `matcher()` check the same fields —
without this check, a bug that always reports `OK` (e.g. a predicate that matches
everything) wouldn't be caught by the happy-path test alone.

### 5. Edge case: an interface name not present on the host must fail loudly

```bash
docker compose exec packetbroker python3 -c "
from core.packet_engine import InterfaceHandle
try:
    InterfaceHandle('does_not_exist0')
except RuntimeError as e:
    print('Got expected RuntimeError:', e)
"
```

Expected: `Got expected RuntimeError: interface 'does_not_exist0' could not be
opened (check topology.yaml): [Errno 19] No such device` — per
`core/packet_engine.py`'s docstring, a misconfigured `topology.yaml` must fail
with the bad interface name in the message, not silently skip it.

### 6. Tear down

```bash
docker compose down
```

`sandbox/entrypoint.sh`'s `trap` handler runs `sandbox/teardown_sandbox.sh`, which
deletes the `broker_sim` namespace; since veth interfaces are created in pairs,
that also removes `internal1`/`external1`/`dpi1` from the container's default
namespace. Run `docker compose up --build -d` again any time to get a clean
topology back.

---

## Why a standalone script instead of `docker compose up` alone

`api/main.py` currently only has a "MINIMAL BOOTSTRAP IMPLEMENTATION" (enough to
make `docker compose up` boot uvicorn cleanly) — it does not yet call
`core/test_runner.py`'s `register_all_tests()` / `start_all()`, because
`core/test_runner.py`, `core/state_manager.py`, and `core/collision_checker.py`
are steps 6-9, not part of this round. `scripts/smoke_test_l2_bypass.py` is a
throwaway harness standing in for that wiring, scoped specifically to proving
steps 1-5 are correct in isolation — exactly what README.md §9 / CLAUDE.md's
"Implementation order" asks for at this stage ("if this passes against the
sandbox, steps 1-5 are correct").
