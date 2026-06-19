"""
tests/test_mirroring.py
Mirroring (PCP=1) and steering (PCP=2/3) tests. Explicitly out of MVP
scope per team-lead guidance. core/dpi_stub.py is already written
generically enough (register() takes any pcp_value) that this mostly
needs new DpiFlowTest(pcp_value=1) / (pcp_value=2) instances -- see
tests/test_dpi_flow.py's docstring. See README.md "MVP Scope".
"""
# TODO (deferred -- explicitly out of MVP scope)
