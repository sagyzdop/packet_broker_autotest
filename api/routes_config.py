"""
api/routes_config.py
=======================
See README.md -> "Configuration Files" and original spec's "Full System
Config" section.

WHAT TO IMPLEMENT
-------------------
GET  /config   -> return the full config.json contents as currently
                  loaded in `app.state` (not re-read from disk, so it
                  reflects any prior POST below).
POST /config   -> accept a full config.json-shaped body, validate it (at
                  minimum: every interface name referenced exists in the
                  loaded topology; every test group name is recognized),
                  then re-run core/test_runner.register_all_tests(...)
                  (including the collision check) against the NEW
                  config. For MVP, pick the simplest correct behavior:
                  stop every running test, re-register, and require the
                  caller to POST /tests/start-all afterward -- document
                  this clearly in the response.

NOT IN MVP SCOPE YET
-----------------------
Topology editing (changing interfaces/pairs) via this endpoint -- MVP
topology is fixed at startup from topology.yaml. Only the `tests` and
`export` blocks of config.json are safe to hot-reload for now. See
README.md "MVP Scope".
"""

# MINIMAL BOOTSTRAP IMPLEMENTATION
# ----------------------------------------------------------------------
# core/test_runner.py's register_all_tests/collision check don't exist
# yet, so POST can't actually re-register anything. GET reads config.json
# straight off disk for now (not yet cached on app.state, since there is
# no startup hook loading it -- see api/main.py). Replace once the
# topology/test_runner modules are implemented.
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
