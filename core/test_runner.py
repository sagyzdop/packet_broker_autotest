"""core/test_runner.py

Turns a list of registered BaseTest instances into running asyncio tasks
that loop forever -- there is no separate "run once and exit" mode anywhere
in this system. `run_test_loop()` is intentionally almost nothing, since
core/base_test.py's `run_once()` already has the real per-iteration logic.

`register_all_tests()` builds every enabled test from config.json's `tests`
block, wires DPI-flow tests into the DpiStub, and runs the collision check
(core/collision_checker.py) against the full resulting list before
returning, so a packet-signature collision fails fast at startup naming
both colliding tests.

See CLAUDE.md -> "Architecture" and "Startup ordering" -- the exact ordering
this file's results are consumed in from api/main.py's startup hook.
Getting that order wrong (e.g. starting tests before DpiStub is listening)
produces flaky-looking TIMEOUTs on the first few iterations that are
actually a startup race, not a real bug.
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
