#!/usr/bin/env python3
"""scripts/smoke_test_l2_bypass.py

Manual smoke test for the L2-bypass path (core/topology.py,
core/packet_builder.py, core/packet_engine.py, core/base_test.py +
core/matcher.py, tests/test_l2_bypass.py) in isolation, without going
through the full api/main.py startup sequence: load topology.yaml, build a
PacketEngine, build one L2BypassTest per protocol in config.json, and run
each test once against the sandbox's broker_sim.py.

Must run inside the sandbox container (needs AF_PACKET + the
internal1/external1/dpi1 veth interfaces created by
sandbox/setup_sandbox.sh):

    docker compose exec packetbroker python3 -m scripts.smoke_test_l2_bypass
"""

import asyncio
import json
import sys

from core.packet_engine import PacketEngine
from core.topology import load_topology
from tests.test_l2_bypass import build_l2_bypass_tests


async def main() -> int:
    topology = load_topology("topology.yaml")
    with open("config.json") as f:
        config = json.load(f)

    pair = topology.pairs[0]
    engine = PacketEngine(topology)
    engine.start_all(asyncio.get_running_loop())

    protocols = config["tests"]["l2_bypass"]["protocols"]
    tests = build_l2_bypass_tests(pair, protocols)

    print(f"Running {len(tests)} L2 bypass test(s) against {pair.internal} -> {pair.external} ...\n")

    all_ok = True
    for test in tests:
        result = await test.run_once(engine, timeout_s=2.0)
        all_ok = all_ok and result.status == "OK"
        marker = "PASS" if result.status == "OK" else "FAIL"
        print(
            f"[{marker}] {test.protocol_name:6s} status={result.status:7s} "
            f"latency_ms={result.latency_ms} failures={result.failures}"
        )

    print("\nALL OK" if all_ok else "\nSOME TESTS FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
