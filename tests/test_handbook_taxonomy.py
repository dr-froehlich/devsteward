"""REQ-027 AC3 — the handbook documents the taxonomy, its V-model mapping, the oracle
definition, and one fully-tagged example acceptance block."""

from __future__ import annotations

from importlib.resources import files

_HANDBOOK = files("devsteward") / "handbook"
_TEMPLATES = files("devsteward") / "templates"


def _read(name: str) -> str:
    return (_HANDBOOK / name).read_text(encoding="utf-8")


def test_handbook_documents_taxonomy_and_example():
    fmt = _read("_01-format.qmd")
    workflow = _read("_03-workflow.qmd")

    # the three-value taxonomy with check: as the contract field (01 · format).
    assert "`check:`" in fmt
    for value in ("`regression`", "`artifact`", "`manual`"):
        assert value in fmt

    # the oracle definition: decoupling, not the test's name, is what classifies.
    assert "Oracle" in fmt and "fixture" in fmt and "system under test" in fmt
    assert "cannot disconfirm" in fmt

    # one fully-tagged example block: all three values appear inside yaml acceptance.
    block = fmt.split("```yaml acceptance", 1)[1].split("```", 1)[0]
    for value in ("check: regression", "check: artifact", "check: manual"):
        assert value in block

    # the V-model phase mapping (03 · workflow): regression -> Build,
    # artifact/manual -> System-Test; the classification steers phase existence.
    assert "V-model" in workflow
    assert "verification" in workflow and "validation" in workflow
    assert "Build" in workflow and "System-Test" in workflow
    assert "phase existence" in workflow

    # the optional process: block is documented with its defaults (01 · format).
    assert "`process:` block" in fmt
    assert "develop: fused" in fmt and "concept: false" in fmt


def test_handbook_documents_environment_bound_regression():
    """REQ-064 AC2: the handbook taxonomy documents the environment-bound-`regression` smell,
    the screening question, and the oracle-coupling routing, with the FlowSteward REQ-043
    case as the worked example."""
    fmt = _read("_01-format.qmd")

    # the smell is named and tied to the worked example.
    assert "environment-bound" in fmt
    assert "REQ-043" in fmt

    # the screening dimension: a service/secret/network absent from a clean checkout.
    assert "secret" in fmt and "network" in fmt
    assert "skip-or-pass" in fmt

    # routing by oracle coupling.
    assert "decoupled" in fmt and "process.lab" in fmt
    assert "runtime" in fmt and "required environment" in fmt


def test_docs_document_live_lane_and_one_flavor():
    """REQ-068 AC5: the stamped ``/intake`` skill, the handbook taxonomy, and the stamped
    ``STEWARD.md`` document the four lanes (hermetic regression / live standing regression /
    one-time artifact / manual), the develop-gate routing, fail-hard-on-a-missing-declared-
    resource, the one-flavor ``python -m pytest`` rule, and the degrade (live → artifact +
    recorded successor) lifecycle."""
    fmt = _read("_01-format.qmd")
    workflow = _read("_03-workflow.qmd")
    intake = (_TEMPLATES / ".claude" / "skills" / "intake" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    steward = (_TEMPLATES / "STEWARD.md").read_text(encoding="utf-8")

    # 1. the fourth lane exists in every surface, distinguished from one-time artifact.
    for doc in (fmt, workflow, intake, steward):
        assert "`live`" in doc, "the live lane must be named"
        assert "standing" in doc, "live is a standing gate member, not one-time"

    # 2. the develop-gate routing: artifact/manual one-time validations are excluded.
    assert "develop gate" in steward.lower() or "develop-gate" in steward.lower()
    assert "deselect" in steward or "excluded" in steward
    assert "one-time" in steward

    # 3. fail-hard on a missing declared resource (a declared lane skip is a hard red).
    assert "hard red" in steward and "skip" in steward

    # 4. the one-flavor rule: every pytest acceptance command runs as `python -m pytest`.
    for doc in (fmt, intake, steward):
        assert "one flavor" in doc.lower() or "one-flavor" in doc.lower()
    assert "`python -m pytest`" in steward

    # 5. the degrade lifecycle: live → artifact reclassification, successor recorded.
    for doc in (intake, steward):
        assert "degrade" in doc.lower()
        assert "live → artifact" in doc or "live -> artifact" in doc
