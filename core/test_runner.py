"""
core/test_runner.py
======================
See README.md -> "Architecture" (asyncio model) and original spec
sections "Operation Mode" and "Parallelism".

WHAT THIS FILE OWNS
-------------------
Turning a list of registered BaseTest instances into running asyncio
tasks, and the "continuous monitoring" infinite loop described in the
original spec -- there is no separate "run once and exit" mode anywhere
in this system.

WHAT TO IMPLEMENT
-------------------
1. `def register_all_tests(config: dict, engine: PacketEngine, dpi_stub: DpiStub) -> list[BaseTest]`
   - Reads config.json's `tests` block (see README.md "Configuration
     Files"). For each ENABLED test group, calls that group's factory --
     e.g. `tests.test_l2_bypass.build_l2_bypass_tests(pair, protocols)`,
     or constructs `tests.test_dpi_flow.DpiFlowTest(pcp_value=0)` for
     each value in `pcp_variants`.
   - Calls core/collision_checker.py against the FULL resulting list
     BEFORE returning -- fail fast at startup (original spec's
     "Uniqueness rule") with an error that names the two colliding tests
     specifically, not a generic exception.
   - For any DpiFlowTest instances, also calls `dpi_stub.register(...)`
     for each (see tests/test_dpi_flow.py's note on this wiring -- keep
     it in this one place only).

2. `async def run_test_loop(test: BaseTest, engine, state_manager, interval_ms: int)`
       while True:
           result = await test.run_once(engine)
           state_manager.update(test.id, result)
           await asyncio.sleep(interval_ms / 1000)
   Intentionally almost nothing -- base_test.py's run_once() already has
   the real logic (see its docstring for why).

3. `def start_all(tests: list[BaseTest], engine, state_manager, loop, parallel_limit: int)`
   - Creates one `asyncio.Task` per test via
     `loop.create_task(run_test_loop(...))`.
   - Respect `parallel_limit` from topology.yaml. For MVP's handful of
     tests this won't actually bind, but don't hardcode "run everything
     unconditionally" either -- a simple `asyncio.Semaphore` acquired/
     released around `test.run_once()` inside run_test_loop is the
     simplest correct implementation.

STARTUP ORDERING (enforced from api/main.py's startup hook, which calls
into this file -- see that file's docstring too)
--------------------------------------------------------------------------
  1. Parse topology.yaml -> build PacketEngine -> start all
     InterfaceDispatchers.
  2. Construct DpiStub over the DPI interfaces, start its run() loop.
  3. register_all_tests(...) -- includes the collision check.
  4. start_all(...) -- only after steps 1-3 succeed.
If any step fails, the process should exit non-zero with a readable
error, never hang silently. Getting this order wrong (e.g. starting tests
before DpiStub is listening) produces flaky-looking TIMEOUTs on the first
few iterations that are actually a startup race, not a real bug -- see
api/main.py's docstring for the same warning.
"""

from __future__ import annotations

import asyncio
from typing import Dict, List, Tuple

from core.base_test import BaseTest, _predicate_from_signature
from core.collision_checker import check_for_collisions
from core.dpi_stub import DpiStub
from tests.test_dpi_flow import DpiFlowTest
from tests.test_l2_bypass import build_l2_bypass_tests


def register_all_tests(config: dict, topology, engine, dpi_stub: DpiStub) -> List[BaseTest]:
    """Builds every enabled test from config.json's `tests` block against the
    parsed topology, wires DPI-flow tests into `dpi_stub`, and runs the
    collision check before returning -- see this file's module docstring.

    NOTE: takes `topology` in addition to the (config, engine, dpi_stub) sketch
    in this file's own docstring -- resolving each test's Pair (with real
    MACs) and DpiFlowTest's ip_base both require the parsed Topology object,
    not just the raw config.json dict.
    """
    pair = topology.pairs[0]  # MVP: single internal/external pair.
    tests: List[BaseTest] = []

    l2_cfg = config["tests"]["l2_bypass"]
    if l2_cfg.get("enabled", False):
        for test in build_l2_bypass_tests(pair, l2_cfg["protocols"]):
            test.id = f"l2_bypass.{test.protocol_name}"
            tests.append(test)

    dpi_cfg = config["tests"]["dpi_flow"]
    if dpi_cfg.get("enabled", False):
        for pcp_value in dpi_cfg["pcp_variants"]:
            test = DpiFlowTest(pcp_value=pcp_value)
            test.pair = pair
            test.ip_base = topology.ip_base
            test.id = f"dpi_flow.pcp{pcp_value}"
            tests.append(test)
            # Keep this wiring in this one place -- see tests/test_dpi_flow.py's note.
            dpi_stub.register(_predicate_from_signature(test.packet_signature()), pcp_value)

    check_for_collisions(tests)

    return tests


async def run_test_loop(test: BaseTest, engine, state_manager, interval_ms: int, semaphore: asyncio.Semaphore) -> None:
    while True:
        async with semaphore:
            result = await test.run_once(engine)
        state_manager.update(test.id, result)
        await asyncio.sleep(interval_ms / 1000)


def start_one(test: BaseTest, engine, state_manager, loop: asyncio.AbstractEventLoop,
              semaphore: asyncio.Semaphore, interval_ms: int) -> asyncio.Task:
    """Starts a single test's infinite loop as an asyncio.Task. Shared by
    start_all() below and api/routes_tests.py's per-test start endpoint, so
    individually (re)started tests still respect the same parallel_limit
    semaphore as everything started at boot."""
    return loop.create_task(run_test_loop(test, engine, state_manager, interval_ms, semaphore))


def start_all(tests: List[BaseTest], engine, state_manager, loop: asyncio.AbstractEventLoop,
              parallel_limit: int, interval_ms: int = 1000) -> Tuple[Dict[str, asyncio.Task], asyncio.Semaphore]:
    """Creates one asyncio.Task per test, respecting `parallel_limit` via a
    shared asyncio.Semaphore. Returns (tasks keyed by test.id, the semaphore)
    -- api/main.py's startup hook stashes both on app.state so
    api/routes_tests.py can start/stop individual tests later against the
    same limit.
    """
    semaphore = asyncio.Semaphore(parallel_limit)
    tasks = {test.id: start_one(test, engine, state_manager, loop, semaphore, interval_ms) for test in tests}
    return tasks, semaphore
