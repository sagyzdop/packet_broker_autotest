#!/usr/bin/env bash
set -e

# ==============================================================================
# entrypoint.sh
# ------------------------------------------------------------------------------
# See README.md -> "Running the Project" and "Sandbox Networking".
#
# Container startup sequence:
#   1. Build the simulated topology (namespace + veth pairs).
#   2. Start broker_sim.py inside the broker_sim namespace, in the
#      background -- it plays the role of the DUT (broker) for as long as
#      the container runs.
#   3. Start the actual test framework (uvicorn) in the foreground, in the
#      container's default namespace, where internal1/external1/dpi1 live.
#
# On SIGTERM/SIGINT (e.g. `docker compose down`), tear the sandbox topology
# back down before exiting, so re-running `docker compose up` later starts
# from a clean state instead of hitting "interface already exists" errors.
#
# This file is sandbox-only. On real hardware you do not use Docker for
# this at all (or if you do, a much simpler container without any of the
# netns/veth setup) -- see README.md "Switching to Real Hardware". You'd
# run `uvicorn api.main:app --host 0.0.0.0 --port 8000` directly.
# ==============================================================================

./sandbox/setup_sandbox.sh

cleanup() {
  echo "[entrypoint] Shutting down, tearing down sandbox topology..."
  ./sandbox/teardown_sandbox.sh
  exit 0
}
trap cleanup SIGTERM SIGINT

echo "[entrypoint] Starting broker_sim.py inside the 'broker_sim' namespace..."
ip netns exec broker_sim python3 sandbox/broker_sim/broker_sim.py &

echo "[entrypoint] Starting FastAPI app (api.main:app) on :8000 ..."
exec uvicorn api.main:app --host 0.0.0.0 --port 8000
