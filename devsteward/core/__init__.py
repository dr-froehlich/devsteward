"""The generic executor core.

Knows nothing about requirements. It resolves the next eligible step from the ledger
in dependency order, invokes ``claude -p`` headless, verifies the result, commits, and
advances the cursor. Everything domain-specific is injected through the seams in
:mod:`devsteward.core.seams`.
"""
