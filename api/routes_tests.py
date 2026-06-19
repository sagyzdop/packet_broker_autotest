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

# MINIMAL BOOTSTRAP IMPLEMENTATION
# ----------------------------------------------------------------------
# core/test_runner.py / core/state_manager.py don't exist yet, so there
# are no real tests to list or control. These placeholders return an
# empty list / 501 so the frontend and `docker compose up` smoke test
# have something real to call against, without 404ing. Replace with the
# real handlers (reading from request.app.state) once the test runner
# and state manager are implemented.
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/tests")
async def list_tests():
    # No test_runner/state_manager wired up yet -- nothing is registered.
    return []


@router.get("/tests/{test_id}")
async def get_test(test_id: str):
    raise HTTPException(status_code=404, detail="no tests registered yet")


@router.post("/tests/{test_id}/start")
async def start_test(test_id: str):
    raise HTTPException(status_code=501, detail="test_runner not implemented yet")


@router.post("/tests/{test_id}/stop")
async def stop_test(test_id: str):
    raise HTTPException(status_code=501, detail="test_runner not implemented yet")


@router.post("/tests/start-all")
async def start_all_tests():
    raise HTTPException(status_code=501, detail="test_runner not implemented yet")


@router.post("/tests/stop-all")
async def stop_all_tests():
    raise HTTPException(status_code=501, detail="test_runner not implemented yet")
