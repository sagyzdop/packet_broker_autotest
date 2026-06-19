"""tests/test_lag_hash.py

LAG hash type detection: vary flow fields (2/4/5-tuple) and watch which
physical DPI link traffic lands on to determine the broker's hashing
algorithm. Requires 2+ DPI links to be meaningful -- MVP's `dpi_lag` in
topology.yaml has only one interface (dpi1).

See CLAUDE.md -> "MVP scope" and "Terminology glossary".
"""
# TODO (deferred -- needs 2+ DPI links in topology.yaml)
