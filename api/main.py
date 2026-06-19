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

# MINIMAL BOOTSTRAP IMPLEMENTATION
# ----------------------------------------------------------------------
# This is intentionally NOT the full implementation described above. The
# real startup sequence (topology.py -> PacketEngine -> DpiStub ->
# register_all_tests -> start_all) depends on core/ modules that are
# still just docstring specs (see CLAUDE.md "Project state"). Wiring
# that in now would just crash on import.
#
# The goal here is the minimum needed to bring `docker compose up` to a
# healthy, browsable state so the sandbox networking setup (veth pairs,
# broker_sim.py) can be verified BEFORE the real pipeline exists:
#   - `app` importable by uvicorn (fixes "Attribute app not found")
#   - /health for a fast liveness check
#   - routers mounted under /api (each currently returns placeholder /
#     501 data -- see their own TODO docstrings)
#   - /ws/live mounted (placeholder -- no state_manager yet)
#   - static frontend mounted last so it doesn't shadow /api routes
#
# Replace this block with the real startup/shutdown hooks once
# core/topology.py through core/test_runner.py are implemented, per the
# "Implementation order" section of CLAUDE.md.
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.routes_tests import router as tests_router
from api.routes_config import router as config_router
from api.routes_export import router as export_router
from api.websocket import router as ws_router

app = FastAPI(title="packet_broker_autotest")

app.include_router(tests_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(ws_router)  # ws://host/ws/live -- no /api prefix


@app.get("/health")
async def health():
    return {"status": "ok"}


# Mounted last so it doesn't shadow the /api routes or /health above.
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
