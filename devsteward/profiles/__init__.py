"""Profiles layer domain knowledge on top of the generic executor core.

A profile supplies a :class:`devsteward.core.seams.StepSource` (and optionally a tuned
verifier). The shipped profile is :mod:`devsteward.profiles.req`, the REQ-workflow
(Design → Build → Land) cycle. A trivial generic profile (explicit step list) is also
provided for non-REQ automation.
"""
