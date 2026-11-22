"""Shared crash-test support (PLAN §11, issue P1-12).

This package holds the crash-matrix harness that every mutation op is proven
against: :mod:`support.faulty_fs` injects a simulated power cut at a chosen
filesystem call, and :mod:`support.invariants` asserts that a library is
consistent afterwards (no content lost, every present row matches disk, no
operation left in-flight).  It is test-only code: it must never be imported by
the production engine.
"""
