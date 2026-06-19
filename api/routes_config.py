"""api/routes_config.py

GET/POST /config -- see README.md for the route table and CLAUDE.md ->
"MVP scope" for why POST is deferred: config hot-reload (re-running
core/test_runner.register_all_tests() against a new config at runtime,
including the collision check) is intentionally out of MVP scope. Topology
editing via this endpoint is also out of scope -- MVP topology is fixed at
startup from topology.yaml; only the `tests`/`export` blocks of config.json
would ever be safe to hot-reload.
"""

# GET reads config.json straight off disk rather than from app.state, since
# POST doesn't implement hot-reload yet -- there's nothing on app.state for
# GET to diverge from.
import json

from fastapi import APIRouter, HTTPException

router = APIRouter()

CONFIG_PATH = "config.json"


@router.get("/config")
async def get_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


@router.post("/config")
async def update_config():
    raise HTTPException(
        status_code=501,
        detail="config hot-reload not implemented yet (needs core/test_runner.py)",
    )
