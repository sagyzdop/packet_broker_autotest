"""
api/routes_tests.py
======================
See README.md and original spec's REST API table.

WHAT TO IMPLEMENT
-------------------
GET  /tests                 -> list every registered test + current
                                status from state_manager (id, status,
                                pps, loss_pct, last_result.failures).
GET  /tests/{id}             -> full detail for one test: its
                                matcher()/encap/packet_signature() plus
                                recent TestResult history (keep the last
                                N in state_manager -- a small ring buffer
                                of RESULTS, separate from the packet ring
                                buffer in core/packet_engine.py).
POST /tests/{id}/start       -> (re)create the asyncio task for one test
                                if it isn't already running.
POST /tests/{id}/stop        -> cancel that task; mark status accordingly
                                in state_manager (e.g. a "STOPPED" status
                                value beyond OK/FAIL/TIMEOUT).
POST /tests/start-all        -> core/test_runner.start_all() for every
                                currently-stopped test.
POST /tests/stop-all         -> cancel every running task.

(Mounted under the "/api" prefix from api/main.py, so the real paths are
/api/tests, /api/tests/{id}, etc.)

All handlers reach the running engine/test objects via
`request.app.state` (set in api/main.py's startup hook) -- never
re-instantiate anything in a route handler.
"""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request

from core.test_runner import start_one

router = APIRouter()


@router.get("/tests")
async def list_tests(request: Request):
    state = request.app.state
    out = []
    for test_id, test in state.tests.items():
        out.append({
            "id": test_id,
            "pair": {"internal": test.pair.internal, "external": test.pair.external},
            "running": test_id in state.tasks,
            **state.state_manager.get_status(test_id),
        })
    return out


@router.get("/tests/{test_id}")
async def get_test(test_id: str, request: Request):
    state = request.app.state
    if test_id not in state.tests:
        raise HTTPException(status_code=404, detail=f"no test registered with id '{test_id}'")
    test = state.tests[test_id]
    return {
        "id": test_id,
        "pair": {"internal": test.pair.internal, "external": test.pair.external},
        "encap": asdict(test.encap),
        "packet_signature": test.packet_signature(),
        "running": test_id in state.tasks,
        **state.state_manager.get_status(test_id),
        "history": [asdict(r) for r in state.state_manager.get_history(test_id)],
    }


@router.post("/tests/{test_id}/start")
async def start_test(test_id: str, request: Request):
    state = request.app.state
    if test_id not in state.tests:
        raise HTTPException(status_code=404, detail=f"no test registered with id '{test_id}'")
    if test_id not in state.tasks:
        state.tasks[test_id] = start_one(
            state.tests[test_id], state.engine, state.state_manager, state.loop,
            state.semaphore, state.topology.send_interval_ms,
        )
    return {"id": test_id, "running": True}


@router.post("/tests/{test_id}/stop")
async def stop_test(test_id: str, request: Request):
    state = request.app.state
    if test_id not in state.tests:
        raise HTTPException(status_code=404, detail=f"no test registered with id '{test_id}'")
    task = state.tasks.pop(test_id, None)
    if task is not None:
        task.cancel()
    state.state_manager.set_status(test_id, "STOPPED")
    return {"id": test_id, "running": False}


@router.post("/tests/start-all")
async def start_all_tests(request: Request):
    state = request.app.state
    started = []
    for test_id, test in state.tests.items():
        if test_id not in state.tasks:
            state.tasks[test_id] = start_one(
                test, state.engine, state.state_manager, state.loop,
                state.semaphore, state.topology.send_interval_ms,
            )
            started.append(test_id)
    return {"started": started}


@router.post("/tests/stop-all")
async def stop_all_tests(request: Request):
    state = request.app.state
    stopped = list(state.tasks.keys())
    for test_id, task in list(state.tasks.items()):
        task.cancel()
        state.state_manager.set_status(test_id, "STOPPED")
    state.tasks.clear()
    return {"stopped": stopped}
