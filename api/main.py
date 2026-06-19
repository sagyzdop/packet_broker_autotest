"""api/main.py

The FastAPI application object and the startup/shutdown sequence that wires
every other module together. This is the literal entrypoint uvicorn runs
(see sandbox/entrypoint.sh: `uvicorn api.main:app`). The startup hook below
follows the exact ordering documented in CLAUDE.md -> "Startup ordering" and
stores the resulting engine/state_manager on `app.state` so route handlers
(api/routes_tests.py etc.) can reach them via `request.app.state`.

If start_all() ran before DpiStub were actually listening, the first few
DPI-flow test iterations would spuriously TIMEOUT even though everything is
implemented correctly -- a classic flaky-looking bug that is actually just a
startup race. Awaiting each step strictly in sequence avoids it.
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
