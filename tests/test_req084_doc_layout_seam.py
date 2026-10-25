"""REQ-084 half A — the project's doc layout is configurable, and the engine follows it.

``requirements_dir``/``index_file`` were configurable; ``plans_dir``/``concepts_dir`` were
hardcoded to ``docs/plans``/``docs/concepts``, so a project whose ``docs/`` is owned by a docs
generator (recipes publishes it with mkdocs) could keep its REQ corpus out of that tree but not
its plans or concepts. These tests pin the seam end to end: the keys load, the land gates read
them, the refusals name the configured path, and no stamped surface hardcodes a doc path
behind the engine's back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from devsteward import skillsync
from devsteward.config import load_config
from devsteward.core.model import Step
from devsteward.profiles.req.checkpoint import ConceptArtifactGate, PlanArtifactGate

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATES = _REPO_ROOT / "devsteward" / "templates"

#: The doc-tree literals a stamped surface must not spell out unless it marks them a default.
_DOC_LITERALS = ("docs/plans", "docs/concepts", "docs/requirements")


def _write_config(root: Path, body: str) -> Path:
    (root / ".devsteward").mkdir(parents=True, exist_ok=True)
    (root / ".devsteward" / "config.yaml").write_text(body, encoding="utf-8")
    return root


# -- AC1 ----------------------------------------------------------------------


def test_config_keys(tmp_path):
    """Both new keys load and resolve under the repo root; absent keys keep the defaults;
    a legacy config that predates them still loads."""
    configured = _write_config(
        tmp_path / "configured",
        "profile: req\n"
        "requirements_dir: requirements\n"
        "index_file: requirements/REQUIREMENTS_INDEX.md\n"
        "plans_dir: requirements/plans\n"
        "concepts_dir: requirements/concepts\n",
    )
    cfg = load_config(configured)
    assert cfg.plans_dir == "requirements/plans"
    assert cfg.concepts_dir == "requirements/concepts"
    assert cfg.plans_path == configured / "requirements" / "plans"
    assert cfg.concepts_path == configured / "requirements" / "concepts"

    # A legacy config (neither key — every consumer stamped before REQ-084) loads and
    # resolves to the conventional layout: no migration verb, no warning.
    legacy = _write_config(tmp_path / "legacy", "profile: req\naccounts:\n  provider: clauder\n")
    cfg = load_config(legacy)
    assert cfg.plans_dir == "docs/plans"
    assert cfg.concepts_dir == "docs/concepts"
    assert cfg.plans_path == legacy / "docs" / "plans"
    assert cfg.concepts_path == legacy / "docs" / "concepts"


# -- AC2 ----------------------------------------------------------------------


def _req(root: Path, req_id: str, *, concept: bool, refs: list[str] | None = None) -> Path:
    req_dir = root / "requirements"
    req_dir.mkdir(parents=True, exist_ok=True)
    refs_block = "[" + ", ".join(refs or []) + "]"
    (req_dir / f"{req_id}.md").write_text(
        "---\n"
        f"id: {req_id}\n"
        "title: Fixture\n"
        "status: open\n"
        "kind: feature\n"
        "added: 2026-07-30\n"
        f"concept_refs: {refs_block}\n"
        + ("process:\n  concept: true\n" if concept else "")
        + "---\n\n## Context\n\nFixture.\n",
        encoding="utf-8",
    )
    return req_dir


def test_gates_follow_config(tmp_path):
    """Both land gates read the configured directories, and every refusal names the
    configured path *relative to the repo root* — not just its last segment."""
    root = _write_config(
        tmp_path,
        "profile: req\n"
        "requirements_dir: requirements\n"
        "index_file: requirements/REQUIREMENTS_INDEX.md\n"
        "plans_dir: requirements/plans\n"
        "concepts_dir: requirements/concepts\n",
    )
    cfg = load_config(root)
    req_dir = _req(root, "REQ-900", concept=True, refs=["requirements/concepts/REQ-900.md"])
    step = Step(id="REQ-900:develop", command="steward advance REQ-900 develop",
                req="REQ-900", phase="develop")

    plan_gate = PlanArtifactGate(cfg.plans_path, cfg.plans_dir)
    concept_gate = ConceptArtifactGate(cfg.concepts_path, req_dir, cfg.concepts_dir)

    # A plan/concept in the *conventional* place does not satisfy a project that configured
    # another one — the whole point of the seam.
    (root / "docs" / "plans").mkdir(parents=True)
    (root / "docs" / "plans" / "REQ-900-plan.md").write_text("REQ-900\n", encoding="utf-8")
    (root / "docs" / "concepts").mkdir(parents=True)
    (root / "docs" / "concepts" / "REQ-900.md").write_text("concept\n", encoding="utf-8")
    plan_refusal = plan_gate(step)
    concept_refusal = concept_gate(step)
    assert plan_refusal and concept_refusal

    # The refusal points at where the engine actually looked, root-relative. The bare last
    # segment ("plans/", "concepts/") would be ambiguous exactly when the layout is not the
    # conventional one.
    assert "requirements/plans/" in plan_refusal
    assert "requirements/concepts/" in concept_refusal

    # The same artifacts at the configured paths satisfy both gates.
    (root / "requirements" / "plans").mkdir(parents=True)
    (root / "requirements" / "plans" / "REQ-900-plan.md").write_text("REQ-900\n", encoding="utf-8")
    (root / "requirements" / "concepts").mkdir(parents=True)
    (root / "requirements" / "concepts" / "REQ-900.md").write_text("concept\n", encoding="utf-8")
    assert plan_gate(step) is None
    assert concept_gate(step) is None


def test_gate_display_defaults_to_directory_name(tmp_path):
    """A gate constructed without a display string keeps the pre-REQ-084 wording, so the
    seam is additive for every direct construction in the engine and its tests."""
    (tmp_path / "docs" / "plans").mkdir(parents=True)
    step = Step(id="REQ-901:develop", command="steward advance REQ-901 develop",
                req="REQ-901", phase="develop")
    refusal = PlanArtifactGate(tmp_path / "docs" / "plans")(step)
    assert refusal is not None and "no file in plans/ names REQ-901" in refusal


# -- AC3 ----------------------------------------------------------------------


def test_onboard_skill_places_docs_by_config():
    """The operator skill writes the doc-path keys *before* copying scaffolding, and places
    artifacts at those paths — the retrofit path recipes actually went through (``/onboard``
    hand-merges the scaffolding; it does not run ``steward new``)."""
    md = (_REPO_ROOT / ".claude" / "skills" / "onboard" / "SKILL.md").read_text(encoding="utf-8")

    # §0 decides the layout, naming all four keys.
    for key in ("requirements_dir", "index_file", "plans_dir", "concepts_dir"):
        assert key in md, f"the onboard skill must name {key}"

    # The stamp step writes the config first and then honours it. Located by *name*, not by
    # its number — REQ-086 inserted a commit step ahead of it and renumbered the sequence.
    rest = md.partition("## 4. Stamp the scaffold")[2]
    assert rest, "the stamp step must be present (as step 4 since REQ-086)"
    stamp_section = rest.split("\n## ", 1)[0]
    low = stamp_section.lower()
    assert "config first" in low or "before copying" in low, (
        "the stamp step must tell the session to write the config before copying artifacts"
    )
    assert "plans_dir" in stamp_section and "concepts_dir" in stamp_section
    assert "unless the config says" in low, (
        "the stamp step must forbid writing under docs/ unless the config says so"
    )


# -- AC4 ----------------------------------------------------------------------


def _stamped_surfaces() -> list[Path]:
    """What a consumer actually receives: the *shipped* skills (operator-only ones are
    filtered out, REQ-084 half B) plus the root manual."""
    names = skillsync.bundled_skill_names(_TEMPLATES)
    assert names, "the templates tree ships skills"
    return [_TEMPLATES / ".claude" / "skills" / n / "SKILL.md" for n in names] + [
        _TEMPLATES / "STEWARD.md"
    ]


@pytest.mark.parametrize("surface", _stamped_surfaces(), ids=lambda p: p.parent.name)
def test_no_hardcoded_doc_paths_in_stamped_prose(surface):
    """No stamped surface may spell a doc-tree path except where it marks it as the
    *default*. Instructions that name a literal path are how a consumer session writes into
    the wrong tree and the land gate then refuses it — a paid session lost to prose."""
    offenders = [
        f"{surface.name}:{n}: {line.strip()}"
        for n, line in enumerate(surface.read_text(encoding="utf-8").splitlines(), 1)
        if any(lit in line for lit in _DOC_LITERALS) and "default" not in line.lower()
    ]
    assert offenders == [], (
        "name the configured dir (and mark the conventional path a default) instead:\n"
        + "\n".join(offenders)
    )
