"""tests/test_mirroring.py

Mirroring (PCP=1) and steering (PCP=2/3) tests. Explicitly out of MVP
scope. core/dpi_stub.py's register()/run() already accept any pcp_value, so
this mostly needs new `DpiFlowTest(pcp_value=1)` / `(pcp_value=2)` instances
registered alongside the existing PCP=0 test -- see tests/test_dpi_flow.py.

See CLAUDE.md -> "MVP scope".
"""
# TODO (deferred -- explicitly out of MVP scope)
