"""REQ-027 AC3 — the handbook documents the taxonomy, its V-model mapping, the oracle
definition, and one fully-tagged example acceptance block."""

from __future__ import annotations

from importlib.resources import files

_HANDBOOK = files("devsteward") / "handbook"


def _read(name: str) -> str:
    return (_HANDBOOK / name).read_text(encoding="utf-8")


def test_handbook_documents_taxonomy_and_example():
    fmt = _read("01-format.md")
    workflow = _read("03-workflow.md")

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
