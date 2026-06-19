"""
api/routes_export.py
=======================
See README.md and original spec section "Export and Reports". NOT
required for the MVP dashboard to function -- stub now so the frontend's
export tab has something real to call later.

WHAT TO IMPLEMENT (can be deferred past MVP, but keep this shape)
----------------------------------------------------------------------
POST /export/capture            -> trigger a dump of each interface's
                                    ring buffer (see core/packet_engine.py
                                    -- "pushes a copy into the ring
                                    buffer") to per-interface .pcap files
                                    + one merged .pcapng; return a job_id.
GET  /export/capture/{job_id}    -> stream back the resulting .pcapng.
GET  /export/report              -> build the JSON/Markdown/HTML report
                                    (original spec "Report Structure")
                                    from current state_manager contents.

MVP NOTE
-----------
It's fine for these three routes to return HTTP 501 for now -- just
don't 404, so the frontend can distinguish "not built yet" from "wrong
URL" while you build the rest of the system.
"""

# MINIMAL BOOTSTRAP IMPLEMENTATION
# ----------------------------------------------------------------------
# Per the MVP note above, 501 is acceptable here -- these just need to
# exist so the frontend's export tab gets a real (non-404) response.
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/export/capture")
async def trigger_capture():
    raise HTTPException(status_code=501, detail="export capture not implemented yet")


@router.get("/export/capture/{job_id}")
async def get_capture(job_id: str):
    raise HTTPException(status_code=501, detail="export capture not implemented yet")


@router.get("/export/report")
async def get_report():
    raise HTTPException(status_code=501, detail="export report not implemented yet")
