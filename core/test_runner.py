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

# TODO: implement register_all_tests, run_test_loop, start_all
