"""core/state_manager.py

In-memory store of every test's latest TestResult plus a short history, and
WebSocket fan-out (every `update()` call pushes the event to all connections
subscribed via api/websocket.py).

See CLAUDE.md -> "Architecture".
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from core.base_test import TestResult

# Ring buffer of recent TestResults kept per test, separate from the raw
# packet ring buffer in core/packet_engine.py's InterfaceDispatcher.
HISTORY_SIZE = 50


@dataclass
class _TestState:
    status: str = "PENDING"
    pps: float = 0.0
    loss_pct: float = 0.0
    last_result: Optional[TestResult] = None
    history: Deque[TestResult] = field(default_factory=lambda: deque(maxlen=HISTORY_SIZE))


class StateManager:
    """In-memory store of every test's latest TestResult plus a short
    history, and websocket fan-out -- see this file's module docstring."""

    def __init__(self):
        self._states: Dict[str, _TestState] = {}
        self._subscribers: List[asyncio.Queue] = []

    def register(self, test_id: str) -> None:
        """Called once per test at startup registration time so GET /api/tests
        can list every test immediately, even before its first run_once()
        completes (status stays "PENDING" until then)."""
        self._states.setdefault(test_id, _TestState())

    def update(self, test_id: str, result: TestResult) -> None:
        state = self._states.setdefault(test_id, _TestState())
        state.status = result.status
        state.last_result = result
        state.history.append(result)
        state.pps = self._compute_pps(state)
        state.loss_pct = self._compute_loss_pct(state)
        self._fan_out(self._event(test_id, state, timestamp=result.timestamp))

    def set_status(self, test_id: str, status: str) -> None:
        """For statuses with no associated TestResult, e.g. "STOPPED" when a
        test's task is cancelled via api/routes_tests.py."""
        state = self._states.setdefault(test_id, _TestState())
        state.status = status
        self._fan_out(self._event(test_id, state, timestamp=time.time()))

    def get_status(self, test_id: str) -> dict:
        state = self._states.setdefault(test_id, _TestState())
        return {
            "status": state.status,
            "pps": state.pps,
            "loss_pct": state.loss_pct,
            "failures": state.last_result.failures if state.last_result else [],
        }

    def get_history(self, test_id: str) -> List[TestResult]:
        state = self._states.get(test_id)
        return list(state.history) if state else []

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    def _event(self, test_id: str, state: _TestState, timestamp: float) -> dict:
        return {
            "test_id": test_id,
            "status": state.status,
            "pps": state.pps,
            "loss_pct": state.loss_pct,
            "timestamp": timestamp,
        }

    def _fan_out(self, event: dict) -> None:
        for queue in list(self._subscribers):
            queue.put_nowait(event)

    def _compute_pps(self, state: _TestState) -> float:
        if len(state.history) < 2:
            return 0.0
        interval_s = state.history[-1].timestamp - state.history[-2].timestamp
        if interval_s <= 0:
            return 0.0
        return round(1.0 / interval_s, 2)

    def _compute_loss_pct(self, state: _TestState) -> float:
        if not state.history:
            return 0.0
        lost = sum(1 for r in state.history if r.status != "OK")
        return round((lost / len(state.history)) * 100, 2)
