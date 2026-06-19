"""
api/main.py
=============
See README.md -> "Architecture" (FastAPI + asyncio share one event loop)
and original spec section "REST API".

WHAT THIS FILE OWNS
-------------------
The FastAPI application object and the startup/shutdown sequence that
wires every other module together. This is the literal entrypoint
uvicorn runs (see sandbox/entrypoint.sh: `uvicorn api.main:app`).

WHAT TO IMPLEMENT
-------------------
1. `app = FastAPI()` at module level -- uvicorn needs to import this name.

2. `@app.on_event("startup") async def startup():`
   Follow the EXACT ordering documented in core/test_runner.py's
   "STARTUP ORDERING" section:
     load topology.yaml + config.json (core/topology.py) ->
     build PacketEngine, start all dispatchers ->
     build + start core/dpi_stub.DpiStub ->
     core/test_runner.register_all_tests(...) (includes the collision
     check) ->
     core/test_runner.start_all(...).
   Store the resulting engine / state_manager on `app.state` so route
   handlers (api/routes_tests.py etc.) can reach them via
   `request.app.state`.

3. `@app.on_event("shutdown") async def shutdown():`
   Cancel all running test tasks cleanly -- don't just let the process
   die. If you add a `PacketEngine.close_all()`, call it here so AF_PACKET
   fds don't leak across container restarts.

4. Mount the sub-routers:
     from api.routes_tests import router as tests_router
     from api.routes_config import router as config_router
     from api.routes_export import router as export_router
     from api.websocket import router as ws_router
     app.include_router(tests_router, prefix="/api")
     app.include_router(config_router, prefix="/api")
     app.include_router(export_router, prefix="/api")
     app.include_router(ws_router)   # ws://host/ws/live -- no /api prefix

5. Mount the static frontend (see frontend/index.html):
     app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
   Mount this AFTER the routers above are included, or it will shadow
   the API routes.

6. A plain `GET /health` route returning `{"status": "ok"}` -- the
   fastest way to confirm the container is alive before debugging
   anything deeper.

WHY STARTUP ORDER MATTERS HERE SPECIFICALLY
----------------------------------------------
If start_all() runs before DpiStub is actually listening, the first few
DPI-flow test iterations will spuriously TIMEOUT even though everything
is implemented correctly -- a classic flaky-looking bug that is actually
just a startup race. Awaiting each step strictly in sequence avoids it.
"""

import asyncio
import json
import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes_tests import router as tests_router
from api.routes_config import router as config_router
from api.routes_export import router as export_router
from api.websocket import router as ws_router
from core.dpi_stub import DpiStub
from core.packet_engine import PacketEngine
from core.state_manager import StateManager
from core.test_runner import register_all_tests, start_all
from core.topology import load_topology

logger = logging.getLogger(__name__)

app = FastAPI(title="packet_broker_autotest")

app.include_router(tests_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(ws_router)  # ws://host/ws/live -- no /api prefix


@app.on_event("startup")
async def startup():
    loop = asyncio.get_running_loop()

    # 1. Parse topology.yaml -> build PacketEngine -> start all dispatchers.
    topology = load_topology("topology.yaml")
    with open("config.json") as f:
        config = json.load(f)

    engine = PacketEngine(topology)
    engine.start_all(loop)

    # 2. Construct DpiStub over the DPI interfaces, start its run() loop.
    dpi_stub = DpiStub(engine, topology.dpi_lag, topology.dpi_vlan_id)
    dpi_task = loop.create_task(dpi_stub.run())

    # 3. register_all_tests(...) -- includes the collision check.
    tests = register_all_tests(config, topology, engine, dpi_stub)

    state_manager = StateManager()
    for test in tests:
        state_manager.register(test.id)

    # 4. start_all(...) -- only after steps 1-3 succeed.
    tasks, semaphore = start_all(
        tests, engine, state_manager, loop, topology.parallel_limit, topology.send_interval_ms
    )

    app.state.topology = topology
    app.state.config = config
    app.state.engine = engine
    app.state.dpi_stub = dpi_stub
    app.state.dpi_task = dpi_task
    app.state.tests = {test.id: test for test in tests}
    app.state.state_manager = state_manager
    app.state.tasks = tasks
    app.state.semaphore = semaphore
    app.state.loop = loop

    logger.info("startup complete: %d test(s) registered and running", len(tests))


@app.on_event("shutdown")
async def shutdown():
    for task in getattr(app.state, "tasks", {}).values():
        task.cancel()
    dpi_task = getattr(app.state, "dpi_task", None)
    if dpi_task is not None:
        dpi_task.cancel()
    engine = getattr(app.state, "engine", None)
    if engine is not None:
        engine.close_all()


@app.get("/health")
async def health():
    return {"status": "ok"}


# Mounted last so it doesn't shadow the /api routes or /health above.
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
