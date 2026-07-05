"""REQ-071 AC1 — the concept-phase & wiring-gap doctrine is present on all four surfaces.

The wiring proof for a doctrine REQ: a hermetic anchor test per surface, so "edited only
one surface" fails mechanically. The shipped copies are the oracle — the repo-root
``STEWARD.md`` is a symlink to the template and the skill files are hardlinked to theirs,
so asserting the package data covers the working copies too.
"""

from __future__ import annotations

from importlib.resources import files

_HANDBOOK = files("devsteward") / "handbook"
_TEMPLATES = files("devsteward") / "templates"


def _norm(text: str) -> str:
    """Collapse all whitespace so anchors match across prose line-wrapping."""
    return " ".join(text.split())

_DECISION_RULE = "cannot be honestly written at intake"
_EARN_LINE = "earn the ACs you can't yet write"
_WIRED = "≠ wired"
_ENTRYPOINT = "real running entrypoint"
_FOLLOW_ON = "named follow-on REQ"
_TERMINAL = "is the terminal act"
_NO_IMPORTED_BAR = "never carry the downstream REQ's acceptance bar"


def _steward() -> str:
    return _norm((_TEMPLATES / "STEWARD.md").read_text(encoding="utf-8"))


def _method() -> str:
    return _norm((_HANDBOOK / "_00-method.qmd").read_text(encoding="utf-8"))


def _skill(name: str) -> str:
    return _norm(
        (_TEMPLATES / ".claude" / "skills" / name / "SKILL.md").read_text(
            encoding="utf-8"
        )
    )


def test_steward_manual_and_handbook_carry_all_five_rules():
    """STEWARD.md and _00-method state the decision rule and all five rules."""
    for doc in (_steward(), _method()):
        # decision rule + rule 1 (concept-phase-as-functional-spec).
        assert _DECISION_RULE in doc
        assert _EARN_LINE in doc
        # rule 2 (wire-through-the-live-entrypoint).
        assert _ENTRYPOINT in doc
        assert _WIRED in doc
        # rule 3 (don't-scope-a-known-defect-out).
        assert _FOLLOW_ON in doc
        assert "silently deferred" in doc
        # rule 4 (concept-phase-iterates-until-frozen).
        assert _TERMINAL in doc
        assert "already-clean tree" in doc
        # rule 5 (phase-model-placement).
        assert _NO_IMPORTED_BAR in doc
        assert "develop: split" in doc


def test_intake_skill_interrogates_the_doctrine():
    """/intake carries the decision rule, the wiring rule, the known-defect rule, and
    the phase-model-placement interrogation."""
    intake = _skill("intake")

    assert _DECISION_RULE in intake
    assert _ENTRYPOINT in intake and _WIRED in intake
    assert _FOLLOW_ON in intake
    assert _NO_IMPORTED_BAR in intake
    # the fork itself is named: split vs. a named downstream REQ, asked explicitly.
    assert "develop: split" in intake
    assert "downstream REQ" in intake


def test_advance_skill_seeds_the_iterative_concept_scope():
    """/advance seeds an empirical concept phase with iterate-until-frozen scope and the
    terminal-checkpoint semantics — and no longer forbids committing prototype code
    (that claim contradicted REQ-067)."""
    advance = _skill("advance")

    assert _TERMINAL in advance
    assert "iterate" in advance.lower()
    assert "already-clean tree" in advance
    # the stale anti-REQ-067 claim is gone.
    assert "never commit prototype code" not in advance
