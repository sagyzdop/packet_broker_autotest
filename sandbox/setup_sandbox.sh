#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# setup_sandbox.sh
# ------------------------------------------------------------------------------
# See README.md -> "Sandbox Networking" for the full explanation/diagram.
#
# Creates ONE Linux network namespace ("broker_sim") and three veth pairs
# wiring it to the container's default namespace, simulating the physical
# cabling between the test server and the broker (DUT) described in
# topology.yaml. Must run as root inside a privileged container (creating
# namespaces requires CAP_SYS_ADMIN).
#
# Design choice: the CONTAINER'S OWN (default) namespace plays the role of
# "test_server" -- this is where internal1/external1/dpi1 live, and where
# the FastAPI app (api/main.py) runs. Only the simulated BROKER gets its
# own separate namespace. This avoids needing any port-forwarding tricks
# between namespaces: Docker's normal "ports: 8000:8000" mapping in
# docker-compose.yml just works, because uvicorn binds in the container's
# default namespace like any normal containerized app.
#
#   [container default ns = "test_server"]      [ns: broker_sim]
#     internal1  <---veth pair--->                 br_internal1
#     external1  <---veth pair--->                 br_external1
#     dpi1       <---veth pair--->                 br_dpi1
#
# Idempotent: safe to run more than once (existing namespace/interfaces are
# left alone rather than erroring out).
#
# When real hardware is available, this script is simply never run -- see
# README.md "Switching to Real Hardware". The framework binds directly to
# real NIC names listed in topology.yaml instead of these veth names.
# ==============================================================================

NS_BROKER="broker_sim"

echo "[setup_sandbox] Ensuring namespace '${NS_BROKER}' exists..."
if ! ip netns list | grep -q "^${NS_BROKER}\b"; then
  ip netns add "${NS_BROKER}"
fi
ip netns exec "${NS_BROKER}" ip link set lo up

create_veth_pair() {
  local host_if="$1"   # lives in the container's default ns ("test_server")
  local broker_if="$2" # lives in the broker_sim ns

  if ip link show "${host_if}" >/dev/null 2>&1; then
    echo "[setup_sandbox] '${host_if}' already exists, skipping."
    return
  fi

  ip link add "${host_if}" type veth peer name "${broker_if}"
  ip link set "${broker_if}" netns "${NS_BROKER}"
  ip link set "${host_if}" up
  ip netns exec "${NS_BROKER}" ip link set "${broker_if}" up
}

echo "[setup_sandbox] Wiring internal1 <-> broker_sim:br_internal1 ..."
create_veth_pair internal1 br_internal1

echo "[setup_sandbox] Wiring external1 <-> broker_sim:br_external1 ..."
create_veth_pair external1 br_external1

echo "[setup_sandbox] Wiring dpi1 <-> broker_sim:br_dpi1 ..."
create_veth_pair dpi1 br_dpi1

echo "[setup_sandbox] Done. Interfaces in the test_server (default) namespace:"
ip -brief link show | grep -E "internal1|external1|dpi1" || true

echo "[setup_sandbox] Interfaces inside '${NS_BROKER}':"
ip netns exec "${NS_BROKER}" ip -brief link show
