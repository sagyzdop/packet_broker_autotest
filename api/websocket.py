"""api/websocket.py

The single WebSocket endpoint the frontend dashboard connects to for live
updates. core/state_manager.py is the source of truth and owns the
subscribe/fan-out logic; this file is purely a thin transport shim. Push,
not poll: core/test_runner.py's `run_test_loop` already calls
`state_manager.update()` every iteration, and state_manager fans that same
update out to every connected websocket immediately. Event shape:
`{test_id, status, pps, loss_pct, timestamp}`.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket):
    await websocket.accept()
    state_manager = websocket.app.state.state_manager
    queue = state_manager.subscribe()
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        state_manager.unsubscribe(queue)
