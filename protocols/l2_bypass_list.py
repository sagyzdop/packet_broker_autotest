"""
protocols/l2_bypass_list.py
The canonical list of L2 control-plane protocols (name, dst_mac,
ethertype) consumed by tests/test_l2_bypass.py's factory function.
Keep this list in sync with sandbox/broker_sim/broker_config.yaml's
`bypass_rules.l2_protocols` -- both the framework and the sandbox's
simulated broker must agree on what should bypass DPI, or
test_l2_bypass.py will fail against the sandbox for reasons that have
nothing to do with bugs in your framework code.

See README.md -> "MVP Scope" for which protocols are in scope now
(LACP/STP/LLDP/CDP) vs deferred (the remaining ~46 from the original
spec's "L2 Bypass" protocol table).
"""
# TODO: define L2_BYPASS_PROTOCOLS = [{"name": ..., "dst_mac": ..., "ethertype": ...}, ...]
