"""
api/websocket.py
===================
See README.md -> "Architecture" and original spec section "WebSocket".

WHAT THIS FILE OWNS
-------------------
The single WebSocket endpoint the frontend dashboard connects to for
live updates. core/state_manager.py is the source of truth; this file is
purely the transport.

WHAT TO IMPLEMENT
-------------------
1. `router = APIRouter()`

2. `@router.websocket("/ws/live") async def ws_live(websocket: WebSocket):`
   - `await websocket.accept()`
   - Register this connection with state_manager (e.g.
     `queue = state_manager.subscribe()`) so it receives every future
     update event.
   - Loop: `await websocket.send_json(event)` for each event pulled off
     that per-connection queue, until the client disconnects
     (`WebSocketDisconnect`) -- then `state_manager.unsubscribe(queue)`
     and return.
   - Event shape (original spec): `{test_id, status, pps, loss_pct, timestamp}`.

WHY PUSH, NOT POLL
---------------------
core/test_runner.py's `run_test_loop` already calls
`state_manager.update()` every iteration (every `send_interval_ms`, 1
second for MVP). The simplest correct design is state_manager fanning
that same update out to every connected websocket immediately, rather
than this file polling state_manager on a timer. Implement the
subscribe/fan-out logic in core/state_manager.py, not here -- keep this
file a thin transport shim.
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
