"""api/routes_export.py

Export/report routes -- deferred past MVP (see CLAUDE.md -> "MVP scope").
Stubbed to return HTTP 501 rather than 404, so the frontend's export tab can
distinguish "not built yet" from "wrong URL".

Future shape:
  POST /export/capture          -> dump each interface's ring buffer (see
                                    core/packet_engine.py's InterfaceDispatcher)
                                    to per-interface .pcap files + one merged
                                    .pcapng; return a job_id.
  GET  /export/capture/{job_id} -> stream back the resulting .pcapng.
  GET  /export/report           -> build a JSON/Markdown/HTML report from
                                    current state_manager contents.
"""

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
