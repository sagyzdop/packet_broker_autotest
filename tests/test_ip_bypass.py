"""tests/test_ip_bypass.py

IP/port/proto bypass tests: broker rules that skip DPI inspection entirely
for traffic matching certain IP ranges, ports, or protocols. Deferred past
MVP, but follows the exact same BaseTest shape as tests/test_l2_bypass.py --
no DPI round trip, just send-and-verify -- making it a natural next test to
implement.

See CLAUDE.md -> "MVP scope" and "Terminology glossary".
"""
# TODO (deferred)
