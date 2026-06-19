#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# teardown_sandbox.sh
# ------------------------------------------------------------------------------
# See README.md -> "Sandbox Networking".
#
# Deleting the "broker_sim" namespace removes every interface inside it
# (br_internal1, br_external1, br_dpi1). Because veth interfaces are
# created in pairs, deleting one end automatically deletes its peer --
# so internal1/external1/dpi1 in the default namespace disappear too.
# No need to manually `ip link del` anything else.
# ==============================================================================

NS_BROKER="broker_sim"

if ip netns list | grep -q "^${NS_BROKER}\b"; then
  ip netns del "${NS_BROKER}"
  echo "[teardown_sandbox] Namespace '${NS_BROKER}' and its veth pairs removed."
else
  echo "[teardown_sandbox] Namespace '${NS_BROKER}' not found, nothing to do."
fi
