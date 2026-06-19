"""
core/collision_checker.py
At startup, calls packet_signature() on every registered test and raises
a clear, specific error if two tests would produce indistinguishable
packets. See README.md and original spec's "Uniqueness rule" /
"Packet Uniqueness". Called from core/test_runner.register_all_tests().
"""
# TODO
