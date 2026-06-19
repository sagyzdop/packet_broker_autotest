"""protocols/l2_bypass_list.py

The canonical list of L2 control-plane protocols (name, dst_mac, ethertype)
consumed by tests/test_l2_bypass.py's factory function. Keep this list in
sync with sandbox/broker_sim/broker_config.yaml's `bypass_rules.l2_protocols`
-- both the framework and the sandbox's simulated broker must agree on what
should bypass DPI, or test_l2_bypass.py will fail against the sandbox for
reasons that have nothing to do with bugs in the framework code.

See CLAUDE.md -> "MVP scope" for which protocols are in scope now.
"""
# MVP scope: LACP/STP/LLDP/CDP only. Must match
# sandbox/broker_sim/broker_config.yaml's bypass_rules.l2_protocols exactly --
# same dst_mac per protocol, same set of protocols.
L2_BYPASS_PROTOCOLS = [
    {"name": "LACP", "dst_mac": "01:80:c2:00:00:02", "ethertype": 0x8809},
    {"name": "STP", "dst_mac": "01:80:c2:00:00:00", "ethertype": None},
    {"name": "LLDP", "dst_mac": "01:80:c2:00:00:0e", "ethertype": 0x88CC},
    {"name": "CDP", "dst_mac": "01:00:0c:cc:cc:cc", "ethertype": None},
]
