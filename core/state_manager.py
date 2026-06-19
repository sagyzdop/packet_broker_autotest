"""
core/state_manager.py
In-memory store of every test's latest TestResult plus a short history,
and websocket fan-out (every `update()` call pushes the event to all
connections subscribed via api/websocket.py). See README.md ->
"Architecture". Needed once core/test_runner.py is wired up.
"""
# TODO
